"""Narration track, SRT subtitles and illustrated film assembly (ffmpeg subprocess); shot-based 24 fps
film assembly (render_shot, assemble_shots), WebVTT captions and title/credit cards for the cinematic film."""
import json
import math
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from .voice import voice_units

RATE = 48000
FPS = 25
FADE_S = 0.8
END_CARD_S = 3.0
TP_MAX = -1.0      # dBTP gate the encoded film must meet (eav.cli TP_MAX)
SHOT_TP_MAX = -1.5 # R10: the cinematic (shot-based) film's encoded true peak
TP_MARGIN = 0.2
LIMITER_START_MARGIN = 0.5   # first limiter ceiling: TP_MAX - this (dB)
LIMITER_RATE = 192000        # oversampled limiting so inter-sample peaks are caught
LIMITER_ATTACK_MS = 1
LIMITER_RELEASE_MS = 50
ZOOM_END = 0.06  # 1.00 -> 1.06
LOGO_WIDTH_FRAC = 0.19   # ~365 px at 1920: earnalism-video landscape lockup (x1510/y48)
LOGO_MARGIN_FRAC = 0.025
LOGO_ASPECT = 720 / 2400   # the production lockup is 2400x720
GLOW_ALPHA = 0.5           # peak strength of the light behind the lockup
GLOW_RGB = (246, 237, 220) # warm ivory
STILL_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _duration(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "json", str(path)], check=True, capture_output=True, text=True)
    return float(json.loads(r.stdout)["format"]["duration"])


VIDEO_SUFFIXES = (".mp4", ".mov", ".m4v", ".webm", ".mkv")


def _has_audio(path) -> bool:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                          "stream=index", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return bool(out.strip())


def _ffmpeg(args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-v", "error", *args], check=True)


def narration_track(units: list, wav_dir: Path, out: Path) -> list:
    """Concatenate <unit_key>.wav files with each unit's pause; no pause after the last.

    Returns [{"unit_key", "start", "end"}] measured from the real WAV durations.
    """
    wav_dir = Path(wav_dir)
    seen = set()
    for u in units:
        k = u["unit_key"]
        if k in seen:
            raise ValueError(f"duplicate unit_key {k!r}")
        seen.add(k)
        if not (wav_dir / f"{k}.wav").is_file():
            raise ValueError(f"missing narration WAV for unit {k!r}")
    if not units:
        raise ValueError("no units")
    timing, t = [], 0.0
    parts, args = [], []
    for i, u in enumerate(units):
        path = wav_dir / f"{u['unit_key']}.wav"
        dur = _duration(path)
        timing.append({"unit_key": u["unit_key"], "start": round(t, 3), "end": round(t + dur, 3)})
        pause = 0.0 if i == len(units) - 1 else u.get("pause_after_ms", 0) / 1000
        args += ["-i", str(path)]
        parts.append(f"[{i}:a]aresample={RATE},aformat=channel_layouts=mono,"
                     f"apad=pad_dur={pause:.3f}[a{i}]")
        t += dur + pause
    graph = ";".join(parts) + ";" + "".join(f"[a{i}]" for i in range(len(units))) + \
        f"concat=n={len(units)}:v=0:a=1[o]"
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "graph.txt"
        script.write_text(graph)
        _ffmpeg([*args, "-filter_complex_script", str(script), "-map", "[o]",
                 "-ar", str(RATE), "-c:a", "pcm_s16le", str(out)])
    return timing


def _ts(s: float) -> str:
    ms = int(round(s * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def subtitles(timing: list, units: list) -> str:
    text = {u["unit_key"]: u["text"] for u in units}
    cues = []
    for i, t in enumerate(timing, 1):
        if t["unit_key"] not in text:
            raise ValueError(f"no unit text for {t['unit_key']!r}")
        cues.append(f"{i}\n{_ts(t['start'])} --> {_ts(t['end'])}\n{text[t['unit_key']]}\n")
    return "\n".join(cues)


def _scenes(plan: dict, film=None) -> list:
    """Scenes of exactly one film: a film dict, or a plan plus a film index."""
    if "scenes" in plan:
        if film not in (None, 0):
            raise ValueError("film index given for a single-film dict")
        return plan["scenes"]
    films = plan["films"]
    if film is None:
        if len(films) != 1:
            raise ValueError("series plan has several films: pass film=<index>")
        film = 0
    if not isinstance(film, int) or not 0 <= film < len(films):
        raise ValueError(f"film index {film!r} out of range")
    return films[film]["scenes"]


def _check_timing(scenes: list, timing: list, language: str, style=None):
    """Timing must be unique and cover exactly the units the plan's scenes produce."""
    keys = [t["unit_key"] for t in timing]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate unit_key in timing")
    expected = []
    for sc in scenes:
        expected += [u["unit_key"] for u in voice_units(sc, {"description": ""}, None, language, style)]
    if set(keys) != set(expected):
        missing, extra = set(expected) - set(keys), set(keys) - set(expected)
        raise ValueError(f"timing does not match plan units: missing {sorted(missing)}, "
                         f"unexpected {sorted(extra)}")


def _stills(stills_dir: Path, scene_id: str) -> list:
    found = sorted(p for p in Path(stills_dir).iterdir()
                   if p.suffix.lower() in STILL_EXTS
                   and (p.stem == scene_id or p.stem.startswith(scene_id + "-")
                        or p.stem.startswith(scene_id + "_")))
    if not found:
        raise ValueError(f"no still for scene {scene_id!r} in {stills_dir}")
    return found


def assemble(plan, timing, stills_dir, mixed_audio, logo: Path, end_card: Path,
             out: Path, size=(1920, 1080), film=None, language: str = "en", style=None) -> dict:
    """Zoompan-pushed stills joined by xfade on narration boundaries, logo top-right,
    END card appended once; exactly one film per call (film=index for a series plan);
    timing must match the plan's voice units exactly; audio is the mixed track (padded under the end card)."""
    W, H = size
    scenes = _scenes(plan, film)
    if not scenes:
        raise ValueError("plan has no scenes")
    _check_timing(scenes, timing, language, style)  # style: the narration job's voice style
    narr_end = timing[-1]["end"] if timing else 0.0
    total = max(narr_end, _duration(mixed_audio))

    starts = []
    for sc in scenes:
        sid = sc["scene_id"]
        mine = [t for t in timing if t["unit_key"].startswith(sid + "-")]
        if not mine:
            raise ValueError(f"no narration timing for scene {sid!r}")
        starts.append(mine[0]["start"])
    stills = [_stills(stills_dir, sc["scene_id"]) for sc in scenes]
    starts[0] = 0.0
    ends = starts[1:] + [total]

    clips = []  # (path, duration)
    for i, files in enumerate(stills):
        span = (ends[i] - starts[i]) / len(files)
        clips += [(f, span) for f in files]
    if any(d <= 0 for _, d in clips):
        raise ValueError("non-positive scene duration")
    n = len(clips)
    fades = [min(FADE_S, clips[k][1], clips[k + 1][1]) for k in range(n - 1)]
    lens = [clips[k][1] + (fades[k - 1] if k else 0.0) for k in range(n)]
    bounds, acc = [], 0.0
    for _, d in clips[:-1]:
        acc += d
        bounds.append(acc)

    args, graph = [], []
    for k, (path, _) in enumerate(clips):
        frames = max(2, int(round(lens[k] * FPS)))
        args += ["-loop", "1", "-framerate", str(FPS), "-t", f"{lens[k]:.3f}", "-i", str(path)]
        graph.append(
            f"[{k}:v]scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,"
            f"crop={W * 2}:{H * 2},"
            f"zoompan=z='1+{ZOOM_END}*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={W}x{H}:fps={FPS},format=yuv420p,setsar=1[v{k}]")
    cur = "v0"
    for k in range(n - 1):
        nxt = f"x{k}"
        graph.append(f"[{cur}][v{k + 1}]xfade=transition=fade:duration={fades[k]:.3f}"
                     f":offset={bounds[k] - fades[k]:.3f}[{nxt}]")
        cur = nxt
    lw = int(W * LOGO_WIDTH_FRAC)
    mg = int(W * LOGO_MARGIN_FRAC)
    base = n  # input indices after clips
    # The approved END is a video with its own sound (earnalism-video): append it whole and keep
    # its audio; a still card is held END_CARD_S over silence.
    end_video = Path(end_card).suffix.lower() in VIDEO_SUFFIXES
    end_s = _duration(end_card) if end_video else END_CARD_S
    end_audio = end_video and _has_audio(end_card)
    end_input = ["-i", str(end_card)] if end_video else [
        "-loop", "1", "-framerate", str(FPS), "-t", f"{END_CARD_S:.3f}", "-i", str(end_card)]
    args += ["-i", str(logo), *end_input, "-i", str(mixed_audio)]
    lh = int(lw * LOGO_ASPECT)
    gx, gy = W - mg - lw // 2, mg + lh // 2  # the lockup's centre
    glow_png = Path(tempfile.mkdtemp()) / "logo-glow.png"
    glow = _logo_glow(lw, lh)
    glow.save(glow_png)
    args += ["-loop", "1", "-framerate", str(FPS), "-i", str(glow_png)]
    graph.append(f"[{base}:v]scale={lw}:-1[lg]")
    # A soft oval of ivory light under the lockup, fading into the scene (never a box).
    graph.append(f"[{cur}][{base + 3}:v]overlay=x={gx - glow.width // 2}:y={gy - glow.height // 2}"
                 f":format=auto:shortest=1[lit]")
    graph.append(f"[lit][lg]overlay=x=W-w-{mg}:y={mg}:format=auto,fps={FPS},"
                 f"trim=0:{total:.3f},setpts=PTS-STARTPTS[main]")
    graph.append(f"[{base + 1}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                 f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS},format=yuv420p,setsar=1[end]")
    graph.append("[main]format=yuv420p[mainf]")
    graph.append("[mainf][end]concat=n=2:v=1:a=0[v]")
    full = total + end_s
    lim = _body_ceiling_for_true_peak(mixed_audio, end_card if end_audio else None, total, end_s)
    graph += _audio_graph(base + 2, base + 1 if end_audio else None, total, end_s,
                          lim["ceiling_db"], lim["gain_db"])
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "graph.txt"
        script.write_text(";".join(graph))
        _ffmpeg([*args, "-filter_complex_script", str(script), "-map", "[v]", "-map", "[a]",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "192k", "-t", f"{full:.3f}",
                 "-movflags", "+faststart", str(out)])
    shutil.rmtree(glow_png.parent, ignore_errors=True)
    return {"duration": full, "narration_end": narr_end, "scenes": len(scenes),
            "clips": n, "size": list(size), "path": str(out), "body_ceiling_db": lim["ceiling_db"],
            "body_gain_db": lim["gain_db"], "body_gain_fallback": lim["fallback"]}


def _logo_glow(lw: int, lh: int):
    """Owner 2026-11-24: lighten the scene behind the lockup. A Gaussian oval of warm ivory,
    strongest at the lockup's centre and fading to nothing well before the image edge, so
    there is no rectangle, plate or feathered box (earnalism-video EDITORIAL_PRESENTATION)."""
    import numpy as np
    from PIL import Image
    gw, gh = max(4, 4 * lw), max(4, int(2.2 * lw))
    rx, ry = 0.8 * lw, 1.4 * lh
    y, x = np.mgrid[0:gh, 0:gw]
    a = GLOW_ALPHA * np.exp(-(((x - gw / 2) / rx) ** 2 + ((y - gh / 2) / ry) ** 2))
    rgba = np.zeros((gh, gw, 4), np.uint8)
    rgba[..., :3] = GLOW_RGB
    rgba[..., 3] = np.round(a * 255).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


def _audio_graph(mixed_idx, end_idx, total, end_s, ceiling_db=None, gain_db=0.0, shape=None):
    """The film's audio: the mixed body, then the END's own sound or silence. The body goes through
    an oversampled true-peak limiter at `ceiling_db` (transient peaks only; integrated loudness is
    kept), and a broadband `gain_db` only as the last-resort fallback. The END is never touched.
    `shape` (shot films): {"lead": seconds of silence before the mix, "fade_out": seconds, "fade_end": where the
    fade ends on the film's timeline}; the fade is the film's own last scene fade, never a drop to zero."""
    shape = shape or {}
    chain = f"aresample={RATE},aformat=channel_layouts=stereo"
    if ceiling_db is not None:
        lin = 10 ** (ceiling_db / 20)
        chain += (f",aresample={LIMITER_RATE},alimiter=limit={lin:.5f}:attack={LIMITER_ATTACK_MS}"
                  f":release={LIMITER_RELEASE_MS}:level=disabled,aresample={RATE}")
    if gain_db:
        chain += f",volume={gain_db:.2f}dB"
    if shape.get("lead"):
        chain += f",adelay={int(round(shape['lead'] * 1000))}:all=1"
    if shape.get("fade_out"):
        chain += f",afade=t=out:st={shape['fade_end'] - shape['fade_out']:.3f}:d={shape['fade_out']:.3f}"
    if end_idx is None:
        return [f"[{mixed_idx}:a]{chain},atrim=0:{total:.3f},apad=whole_dur={total + end_s:.3f}[a]"]
    return [f"[{mixed_idx}:a]{chain},atrim=0:{total:.3f},apad=whole_dur={total:.3f}[am]",
            f"[{end_idx}:a]aresample={RATE},aformat=channel_layouts=stereo,"
            f"atrim=0:{end_s:.3f},apad=whole_dur={end_s:.3f}[ae]",
            "[am][ae]concat=n=2:v=0:a=1[a]"]


def _body_ceiling_for_true_peak(mixed_audio, end_video, total, end_s, tries=4, shape=None, tp_max=TP_MAX) -> dict:
    """AAC encoding raises inter-sample peaks (বিচারক film-01: -1.5 dBTP mix, -0.9 encoded), and
    peaky narration used to force a broadband gain cut that dropped the film below the loudness
    target. Encode the audio alone, measure it, and lower the body's limiter ceiling (not its
    gain) until the encoded track meets tp_max; the END's own sound is never changed. Only if the
    limiter cannot get there is a gain cut applied. Returns {"ceiling_db", "gain_db", "fallback"}."""
    from .mix import measure
    ceiling, gain = tp_max - LIMITER_START_MARGIN, 0.0
    with tempfile.TemporaryDirectory() as td:
        trial = Path(td) / "audio.m4a"
        inputs = ["-i", str(mixed_audio)] + (["-i", str(end_video)] if end_video else [])

        def encoded_tp():
            graph = _audio_graph(0, 1 if end_video else None, total, end_s, ceiling, gain, shape)
            _ffmpeg([*inputs, "-filter_complex", ";".join(graph), "-map", "[a]",
                     "-c:a", "aac", "-b:a", "192k", str(trial)])
            return measure(trial)["true_peak"]

        for _ in range(tries):
            tp = encoded_tp()
            if tp <= tp_max:
                return {"ceiling_db": round(ceiling, 2), "gain_db": gain, "fallback": False}
            ceiling -= tp - tp_max + TP_MARGIN
        for _ in range(tries):  # the limiter alone cannot reach tp_max: cut the gain, and say so
            tp = encoded_tp()
            if tp <= tp_max:
                return {"ceiling_db": round(ceiling, 2), "gain_db": gain, "fallback": True}
            gain -= tp - tp_max + TP_MARGIN
    raise RuntimeError(f"encoded audio stays above {tp_max} dBTP after {2 * tries} attempts")


# ====================================================================== shot-based film (24 fps)
SHOT_FPS = 24
CODE_VERSION = "film-shots-1"   # part of every render_shot cache key: bump it when rendering changes
FADE_OUT_S = 1.6                # the film's last picture and sound fade (pilot spike); scene mixes have none
DISSOLVE_S = 0.8                # a "dissolve" transition_in; "cut" and "match" are hard cuts
TITLE_S, CREDITS_S = 4.0, 5.0
FRAME = (1920, 1080)
GLIDE_KEYS = ("zoom", "pan_x", "pan_y", "ease", "near_gain", "zoom0", "flat", "sweep", "drain")
NEAR_GAIN = 1.2                 # glide.render's default near-layer parallax gain
ENCODE_PRESET = "medium"        # libx264 preset of the finished film (tests lower it for speed)


def _sha256(path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _frames(seconds: float, fps: int) -> int:
    return int(round(seconds * fps))


def _glide_options(shot: dict) -> dict:
    cam = {k: v for k, v in (shot.get("camera") or {}).items() if k in GLIDE_KEYS}
    return {**cam, **{k: v for k, v in (shot.get("glide") or {}).items() if k in GLIDE_KEYS}}


def _check_pull_back(opts: dict) -> None:
    """glide.overscan() ignores a negative zoom, so a pull-back needs zoom0 to cover it: refuse any glide
    whose frame would not stay filled (an edge band) instead of rendering it."""
    zoom, zoom0 = opts.get("zoom", 0.12), opts.get("zoom0", 1.0)
    gain = opts.get("near_gain", NEAR_GAIN)
    if zoom0 * (1 + min(0.0, zoom) * gain) < 1.0:
        raise ValueError(f"a pull-back of zoom {zoom} with near_gain {gain} and zoom0 {zoom0} would expose an "
                         f"edge band (zoom0 * (1 + zoom * near_gain) = {zoom0 * (1 + min(0.0, zoom) * gain):.3f} "
                         f"< 1); raise zoom0 to at least {1 / (1 + min(0.0, zoom) * gain):.3f}")


def _shot_key(shot: dict, assets: dict, fps: int) -> str:
    import hashlib
    files = {}
    for name in sorted(assets):
        value = assets[name]
        listed = list(value) if isinstance(value, (list, tuple)) else [value]
        for p in listed:
            if p is None or not Path(p).is_file():
                raise ValueError(f"shot input {name!r} is not a file: {p}")
        files[name] = [_sha256(p) for p in listed]
    blob = json.dumps({"shot": shot, "inputs": files, "code": CODE_VERSION, "fps": fps},
                      sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _encode_still(image: Path, n: int, out: Path, fps: int):
    W, H = FRAME
    _ffmpeg(["-loop", "1", "-framerate", str(fps), "-i", str(image), "-vf",
             f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,format=yuv420p",
             "-frames:v", str(n), "-c:v", "libx264", "-preset", ENCODE_PRESET, "-crf", "15",
             "-pix_fmt", "yuv420p", "-r", str(fps), str(out)])


def _encode_wan(clips, n: int, out: Path, fps: int):
    """Native 24 fps Wan footage (no interpolation), black edge rows cropped away by a slight overscale, clips
    joined end to end (a continuation starts on the previous clip's last frame, so its first frame is dropped);
    a rare action shorter than the shot holds its last frame."""
    W, H = FRAME
    args, chain = [], []
    for k, c in enumerate(clips):
        args += ["-i", str(c)]
        trim = "trim=start_frame=1," if k else ""
        chain.append(f"[{k}:v]{trim}setpts=PTS-STARTPTS,scale=2016:-2:flags=lanczos,crop={W}:{H},"
                     f"fps={fps},setsar=1,format=yuv420p[c{k}]")
    chain.append("".join(f"[c{k}]" for k in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=0[cat]")
    chain.append(f"[cat]tpad=stop_mode=clone:stop_duration=4,trim=end_frame={n},setpts=PTS-STARTPTS[v]")
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "graph.txt"
        script.write_text(";".join(chain))
        _ffmpeg([*args, "-filter_complex_script", str(script), "-map", "[v]", "-c:v", "libx264",
                 "-preset", ENCODE_PRESET, "-crf", "15", "-pix_fmt", "yuv420p", "-r", str(fps), str(out)])


def render_shot(shot: dict, assets: dict, cache_dir: Path, fps: int = SHOT_FPS) -> Path:
    """One shot as a 1920x1080 clip of `shot["seconds"]` (whole frames), cached by sha256 of the shot's JSON,
    the hashes of its input files and CODE_VERSION: a hit never renders.

    shot    an approved shot-plan shot (motion wan|glide|static, camera {zoom, pan_x, ease, ...}) plus
            "seconds", the render length (the shot's span plus its dissolve halves, see edit_lengths); a glide
            may also carry camera zoom0/near_gain/pan_y/flat/sweep/drain (or a "glide" dict of the same).
    assets  glide: {"image", "depth"} (depth omitted with flat); static: {"image"}; wan: {"clips": [paths]},
            a take and its continuations in order."""
    motion = shot.get("motion")
    seconds = shot.get("seconds")
    if not isinstance(seconds, (int, float)) or seconds <= 0:
        raise ValueError("render_shot needs the shot's render length in shot['seconds']")
    n = _frames(seconds, fps)
    if n < 1:
        raise ValueError(f"shot {shot.get('n')} is shorter than one frame")
    if motion == "glide":
        opts = _glide_options(shot)
        _check_pull_back(opts)
        if not assets.get("image"):
            raise ValueError(f"glide shot {shot.get('n')} needs its still (assets['image'])")
        if not assets.get("depth") and not opts.get("flat"):
            raise ValueError(f"glide shot {shot.get('n')} needs a depth map (assets['depth']) unless flat")
    elif motion == "static":
        if not assets.get("image"):
            raise ValueError(f"static shot {shot.get('n')} needs its still (assets['image'])")
    elif motion == "wan":
        if not assets.get("clips"):
            raise ValueError(f"wan shot {shot.get('n')} has no imported clip; never replaced by a still")
    else:
        raise ValueError(f"shot {shot.get('n')} motion must be wan, glide or static, not {motion!r}")
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"{_shot_key(shot, assets, fps)}.mp4"
    if out.is_file():
        return out
    tmp = out.with_name(out.stem + ".part.mp4")
    try:
        if motion == "glide":
            from . import glide
            res = glide.render(Path(assets["image"]), Path(assets["depth"]) if assets.get("depth") else None,
                               tmp, n / fps, fps=fps, **opts)
            if res["frames"] != n:
                raise ValueError(f"glide rendered {res['frames']} frames, expected {n}")
        elif motion == "static":
            _encode_still(Path(assets["image"]), n, tmp, fps)
        else:
            _encode_wan([Path(c) for c in assets["clips"]], n, tmp, fps)
        tmp.rename(out)
    finally:
        tmp.unlink(missing_ok=True)
    return out


def pick_wan_clips(items: list, scene_id: str, n: int, picks: dict = None) -> list:
    """The item keys of a Wan shot, in order: the take and its `continue_from` chain.

    Candidates are the film_clips items that name shot `n` and whose key starts with `<scene_id>-` (a job's
    items carry no scene, so the key prefix binds them). One chain: it is the shot's clip. Several takes: the
    reviewer must name one in `picks` ({"<scene>/<n>": "<key of the take's last item>"}); never a guess."""
    picks = picks or {}
    mine = [i for i in items if i.get("shot") == n and str(i.get("key", "")).startswith(scene_id + "-")]
    if not mine:
        raise ValueError(f"no film_clips item for shot {n} of scene {scene_id}")
    by_key = {i["key"]: i for i in mine}
    continued = {i["continue_from"] for i in mine if i.get("continue_from")}
    ends = [i["key"] for i in mine if i["key"] not in continued]
    want = picks.get(f"{scene_id}/{n}")
    if want is not None:
        if want not in ends:
            raise ValueError(f"clip pick {want!r} for shot {n} of scene {scene_id} is not one of its takes "
                             f"({', '.join(sorted(ends))})")
        ends = [want]
    if len(ends) != 1:
        raise ValueError(f"shot {n} of scene {scene_id} has {len(ends)} takes ({', '.join(sorted(ends))}); name "
                         f"one in clip-picks.json as {{\"{scene_id}/{n}\": \"<key>\"}}")
    chain, key = [], ends[0]
    while key is not None:
        if key not in by_key or key in chain:
            raise ValueError(f"continue_from chain of {ends[0]!r} (shot {n}, scene {scene_id}) is broken at {key!r}")
        chain.insert(0, key)
        key = by_key[key].get("continue_from")
    return chain


def edit_lengths(durations: list, transitions: list, fps: int = SHOT_FPS):
    """Render lengths and overlaps that put every cut on its planned frame.

    durations   each shot's span in seconds (contiguous, from the shot plans)
    transitions seconds of dissolve between shot i and i+1 (0 = hard cut), len(durations) - 1
    Returns (lens, overlaps) in seconds for assemble_shots: a dissolve is centred on the boundary and limited to
    half of the shorter neighbour, a hard cut is a 1-frame xfade placed so the new shot's first shown frame is
    the boundary frame; the film's frame count is round(sum(durations) * fps)."""
    n = len(durations)
    if n < 1 or len(transitions) != n - 1:
        raise ValueError("edit_lengths needs one transition between each pair of shots")
    cum, b = 0.0, []
    for d in durations:
        cum += d
        b.append(_frames(cum, fps))
    over = []
    for i, t in enumerate(transitions):
        cap = 0.5 * min(durations[i], durations[i + 1])
        over.append(max(1, _frames(min(t, cap), fps)) if t > 0 else 1)
    starts = [b[i] - (over[i] - over[i] // 2) for i in range(n - 1)]   # first frame of overlap i
    frames = []
    for i in range(n):
        a = starts[i - 1] if i else 0
        z = starts[i] + over[i] if i < n - 1 else b[-1]
        frames.append(z - a)
    if any(f < 1 for f in frames):
        raise ValueError("a shot is shorter than its transitions")
    return [f / fps for f in frames], [o / fps for o in over]


def _probe_video(path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,nb_read_packets", "-of", "json", str(path)],
                       check=True, capture_output=True, text=True)
    st = json.loads(r.stdout)["streams"][0]
    return {"width": int(st["width"]), "height": int(st["height"]), "frames": int(st["nb_read_packets"])}


def _burn_track(vtt: Path, size: tuple, fonts_dir: Path, work: Path) -> Path:
    """The captions as a transparent picture sequence (concat list) drawn with the cards' raqm Bengali shaping:
    libass in the stock ffmpeg does not reorder Bengali clusters, so burned-in text is never left to it."""
    import re
    from PIL import Image, ImageDraw, ImageFont
    if not _shaping_available():
        raise ValueError("burned-in Bengali captions need Pillow with libraqm")
    W, H = size
    fonts_dir = Path(fonts_dir)
    px = max(14, round(H * 0.045))
    fonts = {"latin": ImageFont.truetype(str(fonts_dir / FONT_FILES["latin_text"]), px, layout_engine=ImageFont.Layout.RAQM),
             "bn": ImageFont.truetype(str(fonts_dir / FONT_FILES["bengali_text"]), px, layout_engine=ImageFont.Layout.RAQM)}
    cues = []
    for block in Path(vtt).read_text(encoding="utf-8").split("\n\n")[1:]:
        lines = block.strip("\n").split("\n")
        mt = re.fullmatch(r"(\d+):(\d\d):(\d\d)\.(\d{3}) --> (\d+):(\d\d):(\d\d)\.(\d{3})", lines[0]) if lines[0] else None
        if mt:
            g = list(map(int, mt.groups()))
            cues.append((g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000,
                         lines[1:]))
    work.mkdir(parents=True, exist_ok=True)
    blank = work / "blank.png"
    Image.new("RGBA", (W, H), (0, 0, 0, 0)).save(blank)
    rows, t = [], 0.0
    for k, (a, b, lines) in enumerate(cues):
        if a > t + 1e-6:
            rows.append((blank, a - t))
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        y0 = H - round(H * 0.07) - (len(lines) - 1) * round(px * 1.5)
        for n, ln in enumerate(lines):
            _draw_line(d, ln, y0 + n * round(px * 1.5), fonts, CARD_INK + (255,), W, stroke=max(2, px // 14))
        png = work / f"cue{k:04d}.png"
        img.save(png)
        rows.append((png, b - a))
        t = b
    if not rows:
        rows = [(blank, 1.0)]
    lst = work / "captions.txt"
    body = "".join(f"file '{p}'\nduration {d:.6f}\n" for p, d in rows) + f"file '{rows[-1][0]}'\n"
    lst.write_text(body, encoding="utf-8")
    return lst


def assemble_shots(shot_clips: list, lens: list, transitions: list, audio: Path, out: Path,
                   fps: int = SHOT_FPS, *, logo: Path = None, end_card: Path = None, title_card: Path = None,
                   credits_card: Path = None, title_s: float = TITLE_S, credits_s: float = CREDITS_S,
                   captions_vtt: Path = None, burn: bool = False, fade_out_s: float = FADE_OUT_S,
                   fonts_dir: Path = None, caption_lang: str = "ben") -> dict:
    """Join rendered shots into the film at `fps`: one xfade per transition (a 1-frame xfade is a hard cut), so
    the picture has sum(frames of lens) - sum(overlap frames) frames exactly (edit_lengths builds both lists).

    audio       the film's mix; it starts after the title card and fades out with the last picture (the last
                scene's fade only: scene joins never drop to zero)
    transitions overlap seconds between clip i and i+1 (len(shot_clips) - 1); 0 means a hard cut
    logo / end_card   the approved lockup (overlay only, top-right, the same placement and glow as `assemble`)
                and the approved END; title_card / credits_card (see cards()) are held title_s / credits_s
    captions_vtt  on the film's timeline (captions(..., offset=title_s)); muxed as a mov_text track, or burned in
                with burn=True (no soft track)."""
    n = len(shot_clips)
    if n < 1 or len(lens) != n or len(transitions) != n - 1:
        raise ValueError("assemble_shots needs one length per clip and one transition between each pair")
    F = [_frames(x, fps) for x in lens]
    O = [max(1, _frames(t, fps)) for t in transitions]
    if any(f < 1 for f in F):
        raise ValueError("a clip is shorter than one frame")
    for i in range(n):
        need = (O[i - 1] if i else 0) + (O[i] if i < n - 1 else 0)
        if F[i] < need:
            raise ValueError(f"clip {i + 1} has {F[i]} frames but its transitions overlap {need}: shorten the "
                             f"dissolve or lengthen the shot")
    sizes = [_probe_video(c) for c in shot_clips]
    if len({(s["width"], s["height"]) for s in sizes}) != 1:
        raise ValueError("shot clips differ in size")
    for i, (s, f) in enumerate(zip(sizes, F)):
        if s["frames"] < f:
            raise ValueError(f"clip {i + 1} has {s['frames']} frames, fewer than the {f} its length needs")
    W, H = sizes[0]["width"], sizes[0]["height"]
    pic_frames = sum(F) - sum(O)
    pic_s = pic_frames / fps
    fade_f = min(_frames(fade_out_s, fps), pic_frames) if fade_out_s else 0
    if burn and not captions_vtt:
        raise ValueError("burn needs captions_vtt")
    work = Path(tempfile.mkdtemp())
    if burn:
        cap_list = _burn_track(Path(captions_vtt), (W, H), Path(fonts_dir) if fonts_dir else _default_fonts_dir(),
                               work / "captions")

    args, graph = [], []
    for k, c in enumerate(shot_clips):
        args += ["-i", str(c)]
        graph.append(f"[{k}:v]settb=AVTB,fps={fps},format=yuv420p,setsar=1,trim=end_frame={F[k]},"
                     f"setpts=PTS-STARTPTS[v{k}]")
    cur, length = "v0", F[0]
    for k in range(n - 1):
        graph.append(f"[{cur}][v{k + 1}]xfade=transition=fade:duration={O[k] / fps:.6f}"
                     f":offset={(length - O[k]) / fps:.6f}[x{k}]")
        cur, length = f"x{k}", length + F[k + 1] - O[k]
    nxt = n
    if logo is not None:
        lw, mg = int(W * LOGO_WIDTH_FRAC), int(W * LOGO_MARGIN_FRAC)
        lh = int(lw * LOGO_ASPECT)
        glow = _logo_glow(lw, lh)
        glow_png = Path(tempfile.mkdtemp()) / "logo-glow.png"
        glow.save(glow_png)
        args += ["-i", str(logo), "-loop", "1", "-framerate", str(fps), "-i", str(glow_png)]
        graph.append(f"[{nxt}:v]scale={lw}:-1[lg]")
        graph.append(f"[{cur}][{nxt + 1}:v]overlay=x={W - mg - lw // 2 - glow.width // 2}"
                     f":y={mg + lh // 2 - glow.height // 2}:format=auto:shortest=1[lit]")
        graph.append(f"[lit][lg]overlay=x=W-w-{mg}:y={mg}:format=auto,format=yuv420p[lgo]")
        cur, nxt = "lgo", nxt + 2
    if fade_f:
        graph.append(f"[{cur}]fade=t=out:s={pic_frames - fade_f}:n={fade_f}[pf]")
        cur = "pf"
    parts, lead, tail = [], 0.0, 0.0

    def card(path, seconds, idx, name, fade_in, fade_out):
        frames = _frames(seconds, fps)
        fx = ""
        edge = min(_frames(0.5, fps), frames // 2)
        if fade_in:
            fx += f",fade=t=in:s=0:n={edge}"
        if fade_out:
            fx += f",fade=t=out:s={frames - edge}:n={edge}"
        graph.append(f"[{idx}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                     f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p,setsar=1,trim=end_frame={frames}"
                     f",setpts=PTS-STARTPTS{fx}[{name}]")
        return frames / fps

    if title_card is not None:
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{title_s:.3f}", "-i", str(title_card)]
        lead = card(title_card, title_s, nxt, "tc", True, True)
        parts.append("tc")
        nxt += 1
    parts.append(cur)
    if credits_card is not None:
        args += ["-loop", "1", "-framerate", str(fps), "-t", f"{credits_s:.3f}", "-i", str(credits_card)]
        tail = card(credits_card, credits_s, nxt, "cc", True, False)
        parts.append("cc")
        nxt += 1
    total = lead + pic_s + tail   # everything before the END
    graph.append("".join(f"[{p}]" for p in parts) + f"concat=n={len(parts)}:v=1:a=0[body]" if len(parts) > 1
                 else f"[{parts[0]}]null[body]")
    end_s, end_audio, end_idx = 0.0, False, None
    if end_card is not None:
        end_video = Path(end_card).suffix.lower() in VIDEO_SUFFIXES
        end_s = _duration(end_card) if end_video else END_CARD_S
        end_audio = end_video and _has_audio(end_card)
        args += ["-i", str(end_card)] if end_video else [
            "-loop", "1", "-framerate", str(fps), "-t", f"{END_CARD_S:.3f}", "-i", str(end_card)]
        end_idx = nxt
        nxt += 1
        graph.append(f"[{end_idx}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                     f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p,setsar=1[end]")
        graph.append("[body][end]concat=n=2:v=1:a=0[vv]")
    else:
        graph.append("[body]null[vv]")
    if burn:
        args += ["-f", "concat", "-safe", "0", "-i", str(cap_list)]
        graph.append(f"[{nxt}:v]fps={fps},format=rgba[cap]")
        nxt += 1
        graph.append("[vv][cap]overlay=format=auto:eof_action=pass[v]")
    else:
        graph.append("[vv]null[v]")
    full = total + end_s
    audio_idx = nxt
    args += ["-i", str(audio)]
    nxt += 1
    shape = {"lead": lead, "fade_out": fade_f / fps if fade_f else 0.0, "fade_end": lead + pic_s}
    lim = _body_ceiling_for_true_peak(audio, end_card if end_audio else None, total, end_s, shape=shape,
                                    tp_max=SHOT_TP_MAX)
    graph += _audio_graph(audio_idx, end_idx if end_audio else None, total, end_s,
                          lim["ceiling_db"], lim["gain_db"], shape)
    # room tone under the whole film (the title stretch, the credits stretch, a silent END, the fade tail): the
    # delivered audio never holds exact-zero samples (QC digital-zero gate); -62...-68 dBFS, from the mix itself
    from . import retime
    tone = work / "room-tone.wav"
    retime.write(tone, retime.room_tone(retime.read(audio), int((full + 1.0) * retime.SR)))
    args += ["-i", str(tone)]
    graph[-1] = graph[-1][:-3] + "[ab]"
    graph.append(f"[{nxt}:a]aresample={RATE},aformat=channel_layouts=stereo[tn]")
    graph.append("[ab][tn]amix=inputs=2:normalize=0:duration=first[a]")
    nxt += 1
    maps = ["-map", "[v]", "-map", "[a]"]
    if captions_vtt is not None and not burn:
        args += ["-i", str(captions_vtt)]
        maps += ["-map", f"{nxt}:s", "-c:s", "mov_text", "-metadata:s:s:0", f"language={caption_lang}"]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "graph.txt"
        script.write_text(";".join(graph))
        _ffmpeg([*args, "-filter_complex_script", str(script), *maps, "-c:v", "libx264", "-preset", ENCODE_PRESET,
                 "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", "192k",
                 "-t", f"{full:.4f}", "-movflags", "+faststart", str(out)])
    shutil.rmtree(work, ignore_errors=True)
    if logo is not None:
        shutil.rmtree(glow_png.parent, ignore_errors=True)
    return {"frames": pic_frames, "fps": fps, "duration": full, "picture_s": pic_s, "lead_s": lead,
            "overlap_frames": O, "size": [W, H], "path": str(out), "captions": captions_vtt is not None,
            "burned": bool(burn), "body_ceiling_db": lim["ceiling_db"], "body_gain_db": lim["gain_db"],
            "body_gain_fallback": lim["fallback"]}


# ====================================================================== captions (WebVTT)
CAP_LINES, CAP_LINE_CHARS = 2, 42
CAP_MIN_S, CAP_MAX_S = 1.0, 7.0
CAP_CPS = {"bn": 15.0}          # characters per second; other languages 20
CAP_CPS_DEFAULT = 20.0
_JOINERS = "‌‍"
_SPLIT_AFTER = ",;:!?।॥—–…-"   # punctuation after which a line may break
_VIRAMA = "্"


def _is_combining(ch: str) -> bool:
    return unicodedata.category(ch).startswith("M") or ch in _JOINERS


def _visible_len(text: str) -> int:
    """Characters as a reader counts them: marks (vowel signs, hasanta, nukta) and joiners add none."""
    return sum(1 for ch in text if not _is_combining(ch) and ch != "\n")


def _pieces(text: str) -> list:
    """[[word, sep]]: the text cut after whitespace and after punctuation, never inside a grapheme cluster;
    `sep` is the single space that followed it ('' after punctuation inside a word)."""
    out = []
    for tok in text.split():
        cut, start = [], 0
        for i, ch in enumerate(tok[:-1]):
            if ch in _SPLIT_AFTER and not _is_combining(tok[i + 1]) and tok[i + 1] not in _SPLIT_AFTER:
                cut.append(tok[start:i + 1])
                start = i + 1
        cut.append(tok[start:])
        out += [[c, ""] for c in cut]
        out[-1][1] = " "
    if out:
        out[-1][1] = ""
    for i in range(len(out) - 1, 0, -1):   # a piece may not start with a combining mark or end with a hasanta
        if _is_combining(out[i][0][0]) or out[i - 1][0][-1] in _VIRAMA + _JOINERS:
            out[i - 1] = [out[i - 1][0] + out[i - 1][1] + out[i][0], out[i][1]]
            del out[i]
    return out


def _wrap(text: str) -> list:
    """Lines of at most CAP_LINE_CHARS characters, as few and as even as possible."""
    pcs = _pieces(text)
    if not pcs:
        raise ValueError("a caption unit has no text")
    n = len(pcs)

    def width(i, j):   # pieces i..j-1 on one line
        return sum(len(p[0]) for p in pcs[i:j]) + sum(len(p[1]) for p in pcs[i:j - 1])

    for p in pcs:
        if len(p[0]) > CAP_LINE_CHARS:
            raise ValueError(f"{p[0]!r} is longer than {CAP_LINE_CHARS} characters and cannot be split at a "
                             f"space or punctuation")
    greedy, i = 0, 0
    while i < n:
        j = i + 1
        while j < n and width(i, j + 1) <= CAP_LINE_CHARS:
            j += 1
        greedy, i = greedy + 1, j
    # exactly `greedy` lines with the least raggedness (sum of squared distances from the even width)
    target = width(0, n) / greedy
    INF = float("inf")
    best = [[(INF, 0)] * (n + 1) for _ in range(greedy + 1)]
    best[0][0] = (0.0, 0)
    for k in range(1, greedy + 1):
        for j in range(1, n + 1):
            for i in range(j):
                w = width(i, j)
                if w <= CAP_LINE_CHARS and best[k - 1][i][0] < INF:
                    cost = best[k - 1][i][0] + (w - target) ** 2
                    if cost < best[k][j][0]:
                        best[k][j] = (cost, i)
    cuts, j = [], n
    for k in range(greedy, 0, -1):
        i = best[k][j][1]
        cuts.append((i, j))
        j = i
    return ["".join(p[0] + (p[1] if x < b - 1 else "") for x, p in enumerate(pcs[a:b], a))
            for a, b in reversed(cuts)]


def _vtt_ts(ms: int) -> str:
    h, ms = divmod(ms, 3600000)
    m_, ms = divmod(ms, 60000)
    s_, ms = divmod(ms, 1000)
    return f"{h:02d}:{m_:02d}:{s_:02d}.{ms:03d}"


CAP_LEAD_S, CAP_HOLD_S = 0.3, 1.0   # a cue may start this much before its speech and end this much after
CAP_HOLD_HEADING_S = 1.5            # ... when a chapter heading follows (the long chapter-break pause)


def _is_heading(text: str) -> bool:
    """A chapter heading line ("প্রথম পরিচ্ছেদ।"): the recognition retime.py uses. Headings keep their own cue."""
    from .retime import _HEADING_LINE
    return bool(_HEADING_LINE.match(text.strip()))


def _split_span(key, lines, t0, t1):
    """[(start_ms, end_ms, [lines])] for the span t0..t1 (ms): lines grouped 2 per cue (1 when a 2-line cue would
    run past CAP_MAX_S), the span shared by characters; ValueError when no grouping keeps 1-7 s per cue."""
    chars = sum(_visible_len(ln) for ln in lines)
    for per in (CAP_LINES, 1):
        groups = [lines[i:i + per] for i in range(0, len(lines), per)]
        edges, acc = [t0], 0
        for g in groups:
            acc += sum(_visible_len(ln) for ln in g)
            edges.append(t0 + round((t1 - t0) * acc / chars))
        if all(CAP_MIN_S * 1000 <= b - a <= CAP_MAX_S * 1000 for a, b in zip(edges, edges[1:])):
            return [(a, b, g) for a, b, g in zip(edges, edges[1:], groups)]
    raise ValueError(f"unit {key}: its {len(lines)} caption line(s) cannot be shown for {CAP_MIN_S:g}-"
                     f"{CAP_MAX_S:g} s each within {(t1 - t0) / 1000:.2f} s")


def _place(key, text, start, end, prev_end, next_start, cps, single, hold=CAP_HOLD_S):
    """The cues of one unit (or of merged units when `single`: one cue only). The span starts at the speech
    and runs to max(speech end, enough time for `cps`); when that does not fit before the next unit it may
    start up to CAP_LEAD_S earlier and end up to CAP_HOLD_S later, never into the previous cue nor the next
    unit's speech. Raises ValueError when it cannot meet every limit."""
    lines = _wrap(text)
    if single and len(lines) > CAP_LINES:
        raise ValueError(f"{key}: {len(lines)} lines do not fit one cue")
    chars = sum(_visible_len(ln) for ln in lines)
    need = max(math.ceil(chars / cps * 1000), round(CAP_MIN_S * 1000))
    s0, e0 = round(start * 1000), round(end * 1000)
    s_min = max(s0 - round(CAP_LEAD_S * 1000), prev_end)
    e_max = e0 + round(hold * 1000)
    if next_start is not None:
        e_max = min(e_max, round(next_start * 1000))
    if s0 < prev_end:
        s0 = prev_end
    t0, t1 = s0, max(e0, s0 + need)
    if t1 > e_max:                       # use the lead as well
        t1 = e_max
        t0 = min(s0, t1 - need)
        if t0 < s_min:
            raise ValueError(f"{key}: {chars} characters need {need / 1000:.2f} s at {cps:g} characters/s but "
                             f"only {(e_max - s_min) / 1000:.2f} s are free around them")
    return _split_span(key, lines, t0, t1)


def _caption_cues(timing: list, units: list, lang: str, offset: float) -> list:
    text = {u["unit_key"]: u["text"] for u in units}
    cps = CAP_CPS.get(lang, CAP_CPS_DEFAULT)
    order = sorted(timing, key=lambda t: t["start"])
    for i, t in enumerate(order):
        if t["unit_key"] not in text:
            raise ValueError(f"no unit text for {t['unit_key']!r}")
        if i + 1 < len(order) and t["end"] > order[i + 1]["start"] + 1e-9:
            raise ValueError(f"unit {t['unit_key']} ends after the next unit starts")
    groups = []                          # [(first, last, cues)]
    i = 0
    while i < len(order):
        prev_end = groups[-1][2][-1][1] if groups else 0
        nxt = lambda j: order[j + 1]["start"] if j + 1 < len(order) else None
        head = lambda j: j + 1 < len(order) and _is_heading(text[order[j + 1]["unit_key"]])
        hold = lambda j: CAP_HOLD_HEADING_S if head(j) else CAP_HOLD_S
        t = order[i]
        is_h = lambda j: _is_heading(text[order[j]["unit_key"]])
        try:
            cues = _place(t["unit_key"], text[t["unit_key"]], t["start"], t["end"], prev_end, nxt(i), cps, False,
                          hold(i))
            groups.append((i, i, cues))
            i += 1
            continue
        except ValueError as first:
            err = first
        merged = None
        if i + 1 < len(order) and not is_h(i) and not is_h(i + 1):   # merge with the next unit; never a heading
            n = order[i + 1]
            try:
                merged = (i, i + 1, _place(f"{t['unit_key']}+{n['unit_key']}",
                                           text[t["unit_key"]] + " " + text[n["unit_key"]], t["start"], n["end"],
                                           prev_end, nxt(i + 1), cps, True, hold(i + 1)))
            except ValueError:
                merged = None
        if (merged is None and groups and len(groups[-1][2]) == 1 and not is_h(i)
                and not any(is_h(k) for k in range(groups[-1][0], i))):   # or with the previous one
            f, l, _ = groups[-1]
            p_end = groups[-2][2][-1][1] if len(groups) > 1 else 0
            joined = " ".join(text[order[k]["unit_key"]] for k in range(f, i + 1))
            try:
                merged = (f, i, _place("+".join(order[k]["unit_key"] for k in range(f, i + 1)), joined,
                                       order[f]["start"], t["end"], p_end, nxt(i), cps, True, hold(i)))
                groups.pop()
            except ValueError:
                merged = None
        if merged is None:
            raise ValueError(f"{err}; merging with a neighbouring unit does not fit either (re-time the "
                             f"narration or split the unit)")
        groups.append(merged)
        i = merged[1] + 1
    shift = round(offset * 1000)
    return [(a + shift, b + shift, g) for _, _, cues in groups for a, b, g in cues]


def captions(timing: list, units: list, lang: str, offset: float = 0.0, fmt: str = "vtt") -> str:
    """Captions (fmt "vtt" WebVTT or "srt"): cues of at most 2 lines of 42 characters, 1-7 s each, at most 15
    characters/s for bn, split only at spaces or punctuation and never inside a grapheme cluster. The text is
    the source text, only split (whitespace at the splits is dropped). A unit narrated faster than that gets its
    cue started up to 0.3 s early and held up to 1.0 s late (never over a neighbouring cue); failing that it is
    merged with an adjacent unit into one cue that meets every limit; failing that it is refused, never squeezed
    or cut. `offset` shifts the film timeline."""
    if fmt not in ("vtt", "srt"):
        raise ValueError("captions fmt must be vtt or srt")
    cues = _caption_cues(timing, units, lang, offset)
    if fmt == "srt":
        return "\n".join(f"{i}\n{_vtt_ts(a).replace('.', ',')} --> {_vtt_ts(b).replace('.', ',')}\n" + "\n".join(g) + "\n"
                         for i, (a, b, g) in enumerate(cues, 1))
    body = "\n\n".join(f"{_vtt_ts(a)} --> {_vtt_ts(b)}\n" + "\n".join(g) for a, b, g in cues)
    return "WEBVTT\n\n" + body + "\n"


def scene_frames(seconds: list, fps: int = SHOT_FPS) -> list:
    """Frames of each scene with the same cumulative rounding as the picture (edit_lengths): boundary k is
    round(sum of the first k scenes * fps), so scene lengths add up to the film's frame count with no drift."""
    out, cum, prev = [], 0.0, 0
    for sec in seconds:
        cum += sec
        b = _frames(cum, fps)
        out.append(b - prev)
        prev = b
    return out


def check_shot_coverage(scene_id: str, shots: list, seconds: float, tol: float = 1e-6) -> None:
    """A scene's shots must start at 0, follow each other with no gap or overlap and end at the scene's seconds
    (the picture is built from the shot spans, the audio and captions from the scene's seconds)."""
    if not shots:
        raise ValueError(f"scene {scene_id} has no shots")
    at = 0.0
    for s in sorted(shots, key=lambda x: x["start"]):
        if abs(s["start"] - at) > tol:
            raise ValueError(f"scene {scene_id} shot {s['n']} starts at {s['start']:g} s but the previous "
                             f"shot ends at {at:g} s (gap or overlap)")
        at = s["end"]
    if abs(at - seconds) > tol:
        raise ValueError(f"scene {scene_id}'s shots end at {at:g} s but the scene is {seconds:g} s")


def join_scene_mixes(mixes: list, frames: list, out: Path, fps: int = SHOT_FPS) -> Path:
    """Scene mixes joined into the film's mix, each held exactly to its frame-aligned scene length (cut or
    padded with silence), so audio and picture cannot drift apart however many scenes there are."""
    if len(mixes) != len(frames) or not mixes:
        raise ValueError("join_scene_mixes needs one frame count per mix")
    parts, args = [], []
    for i, (m_, f) in enumerate(zip(mixes, frames)):
        length = f / fps
        args += ["-i", str(m_)]
        parts.append(f"[{i}:a]aresample={RATE},aformat=channel_layouts=stereo,"
                     f"apad=whole_dur={length:.6f},atrim=0:{length:.6f},asetpts=PTS-STARTPTS[a{i}]")
    graph = ";".join(parts) + ";" + "".join(f"[a{i}]" for i in range(len(mixes))) + \
        f"concat=n={len(mixes)}:v=0:a=1[o]"
    _ffmpeg([*args, "-filter_complex", graph, "-map", "[o]", "-c:a", "pcm_f32le", str(out)])
    return Path(out)


# ====================================================================== title and credit cards
DISCLOSURE_EN = "Illustrations and narration are AI-generated"
DISCLOSURE_BN = "ছবি ও কণ্ঠ এআই-নির্মিত"
CARD_BG, CARD_INK, CARD_GOLD = (25, 18, 22), (250, 242, 228), (215, 186, 130)   # Maison canvas, ink, gold
FONT_FILES = {   # role -> self-hosted OFL font of the Maison design (static/maison/fonts)
    "latin_display": "cormorant-garamond-latin-wght-normal.woff2",
    "latin_text": "dm-sans-latin-standard-normal.woff2",
    "bengali_display": "noto-serif-bengali-bengali-500-normal.woff2",
    "bengali_text": "noto-sans-bengali-bengali-400-normal.woff2",
}


def _default_fonts_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        d = parent / "static" / "maison" / "fonts"
        if d.is_dir():
            return d
    raise ValueError("the Maison fonts (static/maison/fonts) were not found; pass fonts_dir")


def _shaping_available() -> bool:
    from PIL import features
    return bool(features.check("raqm"))


def _is_bengali(ch: str) -> bool:
    return "ঀ" <= ch <= "৿" or ch in "।॥" + _JOINERS


def _runs(text: str) -> list:
    """[(bengali?, text)]: Bengali (and its danda and joiners) apart from everything else, which the Latin
    fonts draw (spaces and the em dash included)."""
    out = []
    for ch in text:
        b = _is_bengali(ch)
        if out and out[-1][0] == b:
            out[-1][1] += ch
        else:
            out.append([b, ch])
    return [(b, t) for b, t in out]


def _draw_line(draw, text, y, fonts, fill, width, stroke=0):
    """Centre one line of mixed Bengali and Latin text; each run in its own font, shaped with raqm."""
    parts = [(fonts["bn" if b else "latin"], t) for b, t in _runs(text)]
    total = sum(f.getlength(t) for f, t in parts)
    x = (width - total) / 2
    for f, t in parts:
        draw.text((x, y), t, font=f, fill=fill, anchor="ls", stroke_width=stroke,
                  stroke_fill=(CARD_BG + (255,)) if stroke else None)
        x += f.getlength(t)
    return total


def _fit(text, make_fonts, size, max_w):
    while size > 24:
        fonts = make_fonts(size)
        if sum(fonts["bn" if b else "latin"].getlength(t) for b, t in _runs(text)) <= max_w:
            return fonts, size
        size -= 4
    return make_fonts(size), size


def cards(title: str, author: str, voice: str, out_dir: Path, fonts_dir: Path = None) -> dict:
    """The title card ("<title> — <author>") and the credits card (author, narration voice and the AI-generation
    disclosure in English and Bengali) as 1920x1080 PNGs in the Maison fonts, shaped with Pillow's raqm engine
    (Bengali conjuncts need it: without it the cards are refused). Writes cards.json beside them with the strings,
    the font files and their sha256 and returns it."""
    import hashlib
    from PIL import Image, ImageDraw, ImageFont
    if not _shaping_available():
        raise ValueError("Pillow was built without libraqm, which Bengali needs to shape conjuncts; install "
                         "libraqm (Pillow wheels bundle it) before making cards")
    fonts_dir = Path(fonts_dir) if fonts_dir else _default_fonts_dir()
    files = {}
    for role, name in FONT_FILES.items():
        p = fonts_dir / name
        if not p.is_file():
            raise ValueError(f"font {p} is missing")
        files[role] = p
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    W, H = FRAME

    def make(latin, bengali):
        def build(size):
            f = {"latin": ImageFont.truetype(str(files[latin]), size, layout_engine=ImageFont.Layout.RAQM),
                 "bn": ImageFont.truetype(str(files[bengali]), size, layout_engine=ImageFont.Layout.RAQM)}
            return f
        return build

    display, text = make("latin_display", "bengali_display"), make("latin_text", "bengali_text")
    title_line = f"{title} — {author}"
    combined = f"{DISCLOSURE_EN} / {DISCLOSURE_BN}"

    def canvas():
        img = Image.new("RGB", (W, H), CARD_BG)
        return img, ImageDraw.Draw(img)

    img, d = canvas()
    fonts, _ = _fit(title_line, display, 96, W * 0.8)
    _draw_line(d, title_line, H * 0.52, fonts, CARD_INK, W)
    d.line([(W * 0.44, H * 0.58), (W * 0.56, H * 0.58)], fill=CARD_GOLD, width=2)
    title_png = out_dir / "title.png"
    img.save(title_png)

    img, d = canvas()
    fonts, _ = _fit(author, display, 80, W * 0.8)
    _draw_line(d, author, H * 0.36, fonts, CARD_INK, W)
    d.line([(W * 0.44, H * 0.42), (W * 0.56, H * 0.42)], fill=CARD_GOLD, width=2)
    narr = f"Narration — {voice}"
    fonts, _ = _fit(narr, text, 40, W * 0.8)
    _draw_line(d, narr, H * 0.55, fonts, CARD_INK, W)
    fonts, _ = _fit(DISCLOSURE_EN, text, 34, W * 0.8)
    _draw_line(d, DISCLOSURE_EN, H * 0.74, fonts, CARD_GOLD, W)
    fonts, _ = _fit(DISCLOSURE_BN, text, 38, W * 0.8)
    _draw_line(d, DISCLOSURE_BN, H * 0.80, fonts, CARD_GOLD, W)
    credits_png = out_dir / "credits.png"
    img.save(credits_png)

    meta = {"title": title, "author": author, "voice": voice, "title_line": title_line,
            "disclosure": {"en": DISCLOSURE_EN, "bn": DISCLOSURE_BN, "text": combined},
            "fonts": {role: {"file": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                      for role, p in files.items()},
            "cards": {"title": str(title_png), "credits": str(credits_png)}, "size": [W, H],
            "engine": "pillow-raqm"}
    (out_dir / "cards.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return meta
