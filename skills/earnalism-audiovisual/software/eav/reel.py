"""Squint-grade reel: script rules, shot list, 9:16 assembly with loop dissolve, caption."""
import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

from . import mix
from .text import words

W, H = 1080, 1920
FPS = 24
BUDGET = {60: (100, 125), 120: (200, 245)}
REQUIRED_TAGS = ["#earnalism", "#learnalism", "#theearnalism"]
MAX_TAGS = 5
LABEL_SECONDS = 3.0
AUDIO_TOLERANCE_S = 0.25
# One pinned Wan l4-balanced-v2 clip: 121 frames at 24 fps (eav.colab_jobs.reel_clip_seconds).
CLIP_SECONDS = 121 / 24
FIT_TOLERANCE_S = 3.0  # measured reel narration must land within length +- 3 s
TAIL_S = 0.5  # picture after the last word (the loop dissolve)
MIN_LAST_S = 1.5  # a trimmed last shot is never shorter than this (or the full clip)
_FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
          "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"]
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]️?")


def spoken(script: dict) -> list:
    """The narrated lines, defined once: lines[0] is the hook, lines[-1] the loop close."""
    lines = script.get("lines")
    if not isinstance(lines, list) or not lines or not all(isinstance(x, str) for x in lines):
        raise ValueError("lines must be a non-empty list of strings")
    if not script.get("language"):
        raise ValueError("language is required")
    if lines[0] != script.get("hook"):
        raise ValueError("lines[0] must equal hook")
    if lines[-1] != script.get("loop_close"):
        raise ValueError("lines[-1] must equal loop_close")
    return list(lines)


def validate_script(script: dict, narration_seconds=None) -> None:
    """Script rules; once the reel narration is measured, it must also fit length +- 3 s."""
    length = script.get("length")
    if length not in BUDGET:
        raise ValueError(f"length must be 60 or 120, got {length!r}")
    lines = spoken(script)
    if words(script["hook"]) > 8 or not script["hook"].strip():
        raise ValueError("hook must be 1-8 words")
    total = sum(words(x) for x in lines)
    lo, hi = BUDGET[length]
    if not lo <= total <= hi:
        raise ValueError(f"{total} spoken words outside {lo}-{hi} for a {length}s reel")
    if narration_seconds is not None and abs(narration_seconds - length) > FIT_TOLERANCE_S:
        raise ValueError(f"measured narration {narration_seconds:.2f} s does not fit a {length} s reel "
                         f"(+- {FIT_TOLERANCE_S:g} s); change the script's words, never the narration")


def shot_list(script: dict, clip_seconds: float = CLIP_SECONDS, narration_seconds=None,
              line_ends=None) -> list:
    """ceil(narration / clip) shots of one real Wan clip each; only the last is trimmed (never
    stretched) so the picture ends TAIL_S after the last word. Each shot carries the line spoken
    at its midpoint: line_ends are the measured end times per line (else word-proportional)."""
    lines = spoken(script)
    if not isinstance(narration_seconds, (int, float)) or not narration_seconds > 0:
        raise ValueError("shots are planned from the measured reel narration: pass narration_seconds")
    if not clip_seconds > 0:
        raise ValueError("clip_seconds must be positive")
    n = max(1, math.ceil(narration_seconds / clip_seconds - 1e-9))
    rest = narration_seconds - (n - 1) * clip_seconds
    last = min(clip_seconds, max(rest + TAIL_S, MIN_LAST_S))
    if line_ends is None:
        counts = [max(1, words(x)) for x in lines]
        acc, line_ends = 0, []
        for c in counts:
            acc += c
            line_ends.append(acc / sum(counts) * narration_seconds)
    if len(line_ends) != len(lines):
        raise ValueError("line_ends must give one end time per line")
    shots, start = [], 0.0
    for i in range(n):
        sec = clip_seconds if i < n - 1 else last
        mid = start + sec / 2
        idx = 0 if i == 0 else next((k for k, e in enumerate(line_ends) if mid <= e), len(lines) - 1)
        shots.append({"shot": i + 1, "id": f"shot-{i + 1:02d}", "line": lines[idx],
                      "seconds": math.floor(sec * 1e6) / 1e6})  # never above the clip
        start += sec
    return shots


def _probe(path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:format=duration", "-of", "json", str(path)],
                       check=True, capture_output=True, text=True)
    j = json.loads(r.stdout)
    return {"duration": float(j["format"]["duration"])}


def _label_png(text: str, path: Path):
    from PIL import Image, ImageDraw, ImageFont
    font = None
    for f in _FONTS:
        try:
            font = ImageFont.truetype(f, 44)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default(44)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    l, t, r, b = probe.textbbox((0, 0), text, font=font)
    w, h = r - l + 40, b - t + 28
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, w - 1, h - 1), 14, fill=(0, 0, 0, 150))
    d.text((20 - l, 14 - t), text, font=font, fill=(255, 255, 255, 255))
    img.save(path)
    return w, h


def _ff(*args):
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-v", "error", *args], check=True)


def _audio_seconds(path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                        "stream=duration:format=duration", "-of", "json", str(path)],
                       check=True, capture_output=True, text=True)
    j = json.loads(r.stdout)
    vals = [x.get("duration") for x in (j.get("streams") or [{}]) + [j.get("format", {})]]
    vals = [float(v) for v in vals if v not in (None, "N/A")]
    if not vals:
        raise ValueError("audio has no readable duration")
    return vals[0]


def _master_audio(audio: Path, seconds: float, out: Path):
    """Pad (within tolerance) to the video length and land at -14 LUFS / <= -2.0 dBTP."""
    have = _audio_seconds(audio)
    if abs(have - seconds) > AUDIO_TOLERANCE_S:
        raise ValueError(f"audio is {have:.2f}s but video is {seconds:.2f}s "
                         f"(tolerance {AUDIO_TOLERANCE_S}s); narration is never trimmed")
    pre = out.with_name("pre.wav")
    _ff("-i", str(audio), "-af", f"apad,atrim=0:{seconds:.3f},asetpts=PTS-STARTPTS",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(pre))
    base = "loudnorm=I=-14:TP=-2.0:LRA=11"
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(pre), "-af",
                        base + ":print_format=json", "-f", "null", "-"],
                       check=True, capture_output=True, text=True)
    s = mix.loudnorm_stats(r.stderr)
    if any(str(s[k]).strip("-+").lower() in ("inf", "nan") for k in ("input_i", "input_tp")):
        raise ValueError("audio is silent or unmeasurable; cannot master to -14 LUFS")
    f = (f"{base}:measured_I={s['input_i']}:measured_TP={s['input_tp']}:"
         f"measured_LRA={s['input_lra']}:measured_thresh={s['input_thresh']}:"
         f"offset={s['target_offset']}:linear=true")
    _ff("-i", str(pre), "-af", f, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out))


def assemble(clips: list, audio, out, label_text="AI-generated visuals",
             loop_dissolve_s=0.5, last_seconds=None) -> dict:
    """last_seconds trims the last clip to the planned shot (shot_list); it is never stretched."""
    clips = [Path(c) for c in clips]
    audio, out = Path(audio), Path(out)
    if not clips:
        raise ValueError("no clips")
    durs = [_probe(c)["duration"] for c in clips]
    if last_seconds is not None:
        if last_seconds > durs[-1] + 1 / FPS:
            raise ValueError(f"last shot {last_seconds:.3f} s is longer than its clip "
                             f"{durs[-1]:.3f} s; a clip is never stretched")
        durs[-1] = min(durs[-1], last_seconds)
    d = loop_dissolve_s
    if durs[-1] <= d:
        raise ValueError("last clip shorter than the loop dissolve")
    total = sum(durs)
    # exact 9:16: scale to cover, centre-crop, then sharpen
    norm = (f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={W}:{H},unsharp=5:5:0.6,setsar=1,format=yuv420p")
    n = len(clips)
    parts, labels = [], []
    for i in range(n - 1):
        parts.append(f"[{i}:v]{norm},setpts=PTS-STARTPTS[v{i}]")
        labels.append(f"[v{i}]")
    parts.append(f"[{n - 1}:v]{norm},trim=duration={durs[-1]:.4f},setpts=PTS-STARTPTS[vl]")
    # still of clip 1's first frame to dissolve into
    parts.append(f"[{n}:v]{norm},trim=end_frame=1,loop=loop=-1:size=1,"
                 f"trim=duration={d + 1:.3f},setpts=PTS-STARTPTS[st]")
    parts.append(f"[vl][st]xfade=transition=fade:duration={d - 1 / FPS:.4f}:offset={durs[-1] - d:.3f},"
                 f"trim=duration={durs[-1]:.3f},setpts=PTS-STARTPTS[v{n - 1}]")
    labels.append(f"[v{n - 1}]")
    parts.append("".join(labels) + f"concat=n={n}:v=1:a=0[cat]")
    args = []
    for c in clips + [clips[0]]:
        args += ["-i", str(c)]
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        label_box = None
        if label_text:
            png = td / "label.png"
            lw, lh = _label_png(label_text, png)
            label_box = {"x": 60, "y": int(H * 0.74), "w": lw, "h": lh}
            args += ["-loop", "1", "-framerate", str(FPS), "-i", str(png)]
            parts.append(f"[cat][{n + 1}:v]overlay=x={label_box['x']}:y={label_box['y']}:"
                         f"enable='lt(t,{LABEL_SECONDS})'[vo]")
            vmap = "[vo]"
        else:
            vmap = "[cat]"
        mastered = td / "master.wav"
        _master_audio(audio, total, mastered)
        _ff(*args, "-i", str(mastered), "-filter_complex", ";".join(parts),
            "-map", vmap, "-map", f"{n + 2 if label_text else n + 1}:a",
            "-t", f"{total:.3f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
            "-qp", "20", "-x264-params", "mbtree=0:rc-lookahead=0:scenecut=0", "-g", "48", "-bf", "0", "-force_key_frames", f"{LABEL_SECONDS}",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            str(out))
    m = mix.measure(out)
    if abs(m["lufs"] + 14) > 1 or m["true_peak"] > -1.0:
        raise ValueError(f"reel audio misses gate: {m}")
    return {"width": W, "height": H, "seconds": total, "lufs": m["lufs"],
            "true_peak": m["true_peak"], "bytes": out.stat().st_size, "label_box": label_box, "clips": n}


def _title(s: str) -> str:
    return " ".join(w[:1].upper() + w[1:].lower() for w in s.split())


def caption(script: dict, hashtags: list) -> str:
    hook = script["hook"]
    lines = spoken(script)
    emoji = next(iter(_EMOJI.findall(" ".join(lines))), "\U0001F4D6")
    head = _title(_EMOJI.sub("", hook).strip()) + " " + emoji
    tags = list(REQUIRED_TAGS)
    for t in hashtags:
        t = "#" + t.strip().lstrip("#").lower()
        if len(t) > 1 and t not in tags and len(tags) < MAX_TAGS:
            tags.append(t)
    return head + "\n\n" + "\n".join(lines[1:]) + "\n\n" + " ".join(tags)
