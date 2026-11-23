"""Squint-grade reel: script rules, shot list, 9:16 assembly with loop dissolve, caption."""
import json
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


def validate_script(script: dict) -> None:
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


def shot_list(script: dict) -> list:
    """Uniform shots of about 6 s; each shot is tied to the script line spoken at its midpoint."""
    length = script["length"]
    lines = spoken(script)
    n = max(1, round(length / 6.0))
    sec = length / n
    if not 5.0 <= sec <= 7.5:
        raise ValueError("cannot split into 5-7.5 s shots")
    counts = [max(1, words(x)) for x in lines]
    total = float(sum(counts))
    ends, acc = [], 0
    for c in counts:
        acc += c
        ends.append(acc / total * length)
    shots = []
    for i in range(n):
        mid = (i + 0.5) * sec
        idx = next((k for k, e in enumerate(ends) if mid <= e), len(lines) - 1)
        if i == 0:
            idx = 0  # frame 1 carries the hook
        shots.append({"shot": i + 1, "line": lines[idx], "seconds": round(sec, 3)})
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
    s = json.loads(r.stderr[r.stderr.rindex("{"):])
    if any(str(s[k]).strip("-+").lower() in ("inf", "nan") for k in ("input_i", "input_tp")):
        raise ValueError("audio is silent or unmeasurable; cannot master to -14 LUFS")
    f = (f"{base}:measured_I={s['input_i']}:measured_TP={s['input_tp']}:"
         f"measured_LRA={s['input_lra']}:measured_thresh={s['input_thresh']}:"
         f"offset={s['target_offset']}:linear=true")
    _ff("-i", str(pre), "-af", f, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(out))


def assemble(clips: list, audio, out, label_text="AI-generated visuals",
             loop_dissolve_s=0.5) -> dict:
    clips = [Path(c) for c in clips]
    audio, out = Path(audio), Path(out)
    if not clips:
        raise ValueError("no clips")
    durs = [_probe(c)["duration"] for c in clips]
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
    parts.append(f"[{n - 1}:v]{norm},setpts=PTS-STARTPTS[vl]")
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
