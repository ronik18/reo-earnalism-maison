"""Narration track, SRT subtitles and illustrated film assembly (ffmpeg subprocess)."""
import json
import subprocess
import tempfile
from pathlib import Path

from .voice import voice_units

RATE = 48000
FPS = 25
FADE_S = 0.8
END_CARD_S = 3.0
ZOOM_END = 0.06  # 1.00 -> 1.06
LOGO_WIDTH_FRAC = 0.09
LOGO_MARGIN_FRAC = 0.03
STILL_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _duration(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "json", str(path)], check=True, capture_output=True, text=True)
    return float(json.loads(r.stdout)["format"]["duration"])


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


def _check_timing(scenes: list, timing: list, language: str):
    """Timing must be unique and cover exactly the units the plan's scenes produce."""
    keys = [t["unit_key"] for t in timing]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate unit_key in timing")
    expected = []
    for sc in scenes:
        expected += [u["unit_key"] for u in voice_units(sc, {"description": ""}, None, language)]
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
             out: Path, size=(1920, 1080), film=None, language: str = "en") -> dict:
    """Zoompan-pushed stills joined by xfade on narration boundaries, logo top-right,
    END card appended once; exactly one film per call (film=index for a series plan);
    timing must match the plan's voice units exactly; audio is the mixed track (padded under the end card)."""
    W, H = size
    scenes = _scenes(plan, film)
    if not scenes:
        raise ValueError("plan has no scenes")
    _check_timing(scenes, timing, language)
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
    args += ["-i", str(logo), "-loop", "1", "-framerate", str(FPS),
             "-t", f"{END_CARD_S:.3f}", "-i", str(end_card), "-i", str(mixed_audio)]
    graph.append(f"[{base}:v]scale={lw}:-1[lg]")
    graph.append(f"[{cur}][lg]overlay=x=W-w-{mg}:y={mg}:format=auto,fps={FPS},"
                 f"trim=0:{total:.3f},setpts=PTS-STARTPTS[main]")
    graph.append(f"[{base + 1}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                 f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS},format=yuv420p,setsar=1[end]")
    graph.append("[main]format=yuv420p[mainf]")
    graph.append("[mainf][end]concat=n=2:v=1:a=0[v]")
    full = total + END_CARD_S
    graph.append(f"[{base + 2}:a]aresample={RATE},aformat=channel_layouts=stereo,"
                 f"atrim=0:{total:.3f},apad=whole_dur={full:.3f}[a]")
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "graph.txt"
        script.write_text(";".join(graph))
        _ffmpeg([*args, "-filter_complex_script", str(script), "-map", "[v]", "-map", "[a]",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "192k", "-t", f"{full:.3f}",
                 "-movflags", "+faststart", str(out)])
    return {"duration": full, "narration_end": narr_end, "scenes": len(scenes),
            "clips": n, "size": list(size), "path": str(out)}
