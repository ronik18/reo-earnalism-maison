"""Narration track, SRT subtitles and illustrated film assembly (ffmpeg subprocess)."""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .voice import voice_units

RATE = 48000
FPS = 25
FADE_S = 0.8
END_CARD_S = 3.0
TP_MAX = -1.0      # dBTP gate the encoded film must meet (eav.cli TP_MAX)
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


def _audio_graph(mixed_idx, end_idx, total, end_s, ceiling_db=None, gain_db=0.0):
    """The film's audio: the mixed body, then the END's own sound or silence. The body goes through
    an oversampled true-peak limiter at `ceiling_db` (transient peaks only; integrated loudness is
    kept), and a broadband `gain_db` only as the last-resort fallback. The END is never touched."""
    chain = f"aresample={RATE},aformat=channel_layouts=stereo"
    if ceiling_db is not None:
        lin = 10 ** (ceiling_db / 20)
        chain += (f",aresample={LIMITER_RATE},alimiter=limit={lin:.5f}:attack={LIMITER_ATTACK_MS}"
                  f":release={LIMITER_RELEASE_MS}:level=disabled,aresample={RATE}")
    if gain_db:
        chain += f",volume={gain_db:.2f}dB"
    if end_idx is None:
        return [f"[{mixed_idx}:a]{chain},atrim=0:{total:.3f},apad=whole_dur={total + end_s:.3f}[a]"]
    return [f"[{mixed_idx}:a]{chain},atrim=0:{total:.3f},apad=whole_dur={total:.3f}[am]",
            f"[{end_idx}:a]aresample={RATE},aformat=channel_layouts=stereo,"
            f"atrim=0:{end_s:.3f},apad=whole_dur={end_s:.3f}[ae]",
            "[am][ae]concat=n=2:v=0:a=1[a]"]


def _body_ceiling_for_true_peak(mixed_audio, end_video, total, end_s, tries=4) -> dict:
    """AAC encoding raises inter-sample peaks (বিচারক film-01: -1.5 dBTP mix, -0.9 encoded), and
    peaky narration used to force a broadband gain cut that dropped the film below the loudness
    target. Encode the audio alone, measure it, and lower the body's limiter ceiling (not its
    gain) until the encoded track meets TP_MAX; the END's own sound is never changed. Only if the
    limiter cannot get there is a gain cut applied. Returns {"ceiling_db", "gain_db", "fallback"}."""
    from .mix import measure
    ceiling, gain = TP_MAX - LIMITER_START_MARGIN, 0.0
    with tempfile.TemporaryDirectory() as td:
        trial = Path(td) / "audio.m4a"
        inputs = ["-i", str(mixed_audio)] + (["-i", str(end_video)] if end_video else [])

        def encoded_tp():
            graph = _audio_graph(0, 1 if end_video else None, total, end_s, ceiling, gain)
            _ffmpeg([*inputs, "-filter_complex", ";".join(graph), "-map", "[a]",
                     "-c:a", "aac", "-b:a", "192k", str(trial)])
            return measure(trial)["true_peak"]

        for _ in range(tries):
            tp = encoded_tp()
            if tp <= TP_MAX:
                return {"ceiling_db": round(ceiling, 2), "gain_db": gain, "fallback": False}
            ceiling -= tp - TP_MAX + TP_MARGIN
        for _ in range(tries):  # the limiter alone cannot reach TP_MAX: cut the gain, and say so
            tp = encoded_tp()
            if tp <= TP_MAX:
                return {"ceiling_db": round(ceiling, 2), "gain_db": gain, "fallback": True}
            gain -= tp - TP_MAX + TP_MARGIN
    raise RuntimeError(f"encoded audio stays above {TP_MAX} dBTP after {2 * tries} attempts")
