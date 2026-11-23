"""Speech-ducked score mastering (ffmpeg subprocess + numpy envelope)."""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np

RATE = 48000
TRUE_PEAK_LIMIT = -1.5   # loudnorm ceiling; leaves headroom under the -1.0 dBTP gate
SCORE_GAIN_DB = -12.0    # score sits this far under speech before ducking
CROSSFADE_S = 1.0


def _run(args, **kw):
    return subprocess.run(["ffmpeg", "-y", "-hide_banner", *args], check=True,
                          capture_output=True, text=kw.pop("text", True), **kw)


def measure(path) -> dict:
    """Integrated loudness and true peak via ebur128."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                        "ebur128=peak=true", "-f", "null", "-"],
                       check=True, capture_output=True, text=True)
    summary = r.stderr.rsplit("Summary:", 1)[-1]
    lufs = re.search(r"I:\s+(-?[\d.]+|-inf)\s+LUFS", summary)
    peak = re.search(r"True peak:\s+Peak:\s+(-?[\d.]+|-inf)\s+dBFS", summary)
    if not lufs or not peak:
        raise RuntimeError("could not parse ebur128 output")
    return {"lufs": float(lufs.group(1)), "true_peak": float(peak.group(1))}


def _decode(path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le",
                          "-ac", "2", "-ar", str(RATE), "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).copy()


def _write(path, x: np.ndarray):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(RATE),
                    "-ac", "2", "-i", "-", "-c:a", "pcm_f32le", str(path)],
                   input=np.ascontiguousarray(x, dtype=np.float32).tobytes(), check=True)


def _gain_envelope(speech: np.ndarray, n: int, duck_db: float) -> np.ndarray:
    """Per-sample gain: 1.0 in pauses, 10**(-duck_db/20) while speech plays."""
    win = RATE // 100  # 10 ms frames
    mono = np.abs(speech).max(axis=1) if len(speech) else np.zeros(0)
    frames = len(mono) // win
    rms = np.sqrt((mono[:frames * win].reshape(frames, win) ** 2).mean(axis=1)) if frames else np.zeros(0)
    active = rms > 10 ** (-50 / 20)
    # close (dilate 300 ms then erode 150 ms): bridges gaps under 300 ms, holds 150 ms
    dil = np.convolve(active.astype(float), np.ones(30), mode="same") > 0
    held = np.convolve(dil.astype(float), np.ones(15), mode="same") >= 15
    held = held | active
    target = np.where(held, 10 ** (-duck_db / 20), 1.0)
    target = np.repeat(target, win)
    if len(target) < n:
        target = np.concatenate([target, np.ones(n - len(target))])
    target = target[:n]
    # smooth ramp (150 ms attack/release) in dB-linear domain
    k = int(0.15 * RATE)
    db = 20 * np.log10(target)
    pad = np.pad(db, (k // 2, k - k // 2 - 1), mode="edge")
    smooth = np.convolve(pad, np.ones(k) / k, mode="valid")
    # never let smoothing leave the score above the ducked level inside speech
    smooth = np.where(db <= -duck_db + 1e-6, np.minimum(smooth, db), smooth)
    return 10 ** (smooth[:n] / 20)


def duck_and_master(speech: Path, score: Path, out: Path, target_lufs: float,
                    duck_db=19) -> dict:
    speech, score, out = Path(speech), Path(score), Path(out)
    s = _decode(speech)
    sc = _decode(score) * 10 ** (SCORE_GAIN_DB / 20)
    n = max(len(s), len(sc))
    s = np.pad(s, ((0, n - len(s)), (0, 0)))
    sc = np.pad(sc, ((0, n - len(sc)), (0, 0)))
    env = _gain_envelope(s, n, duck_db)
    sc = sc * env[:, None].astype(np.float32)

    stem = out.with_name(out.stem + ".score-ducked.wav")
    _write(stem, sc)
    with tempfile.TemporaryDirectory() as td:
        pre = Path(td) / "pre.wav"
        _write(pre, s + sc)
        tp = TRUE_PEAK_LIMIT
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(pre), "-af",
                            f"loudnorm=I={target_lufs}:TP={tp}:LRA=11:print_format=json",
                            "-f", "null", "-"], check=True, capture_output=True, text=True)
        stats = json.loads(r.stderr[r.stderr.rindex("{"):])
        f = (f"loudnorm=I={target_lufs}:TP={tp}:LRA=11:"
             f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
             f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
             f"offset={stats['target_offset']}:linear=true")
        _run(["-i", str(pre), "-af", f, "-ar", str(RATE), "-ac", "2",
              "-c:a", "pcm_s16le", str(out)])
    res = measure(out)
    res.update({"score_stem": str(stem), "duck_db": duck_db, "target_lufs": target_lufs})
    return res


def arrange_cues(cues: list, boundaries_s: list, total_s: float, out: Path):
    """Place cue i at boundaries_s[i], crossfading into the next; loop short cues."""
    if not cues or len(cues) != len(boundaries_s):
        raise ValueError("cues and boundaries_s must be non-empty and the same length")
    b = [float(x) for x in boundaries_s]
    if b[0] < 0 or any(y <= x for x, y in zip(b, b[1:])) or b[-1] >= total_s:
        raise ValueError("boundaries must be increasing, >= 0 and before total_s")
    args, parts, labels = [], [], []
    for i, cue in enumerate(cues):
        end = b[i + 1] if i + 1 < len(b) else total_s
        xf = min(CROSSFADE_S, (end - b[i]) / 2)
        last = i == len(cues) - 1
        length = end - b[i] + (0 if last else xf)
        args += ["-stream_loop", "-1", "-i", str(cue)]
        f = (f"[{i}:a]aformat=sample_rates={RATE}:channel_layouts=stereo,"
             f"atrim=0:{length:.3f},asetpts=PTS-STARTPTS")
        if i > 0:
            f += f",afade=t=in:d={min(CROSSFADE_S, (b[i] - b[i - 1]) / 2):.3f}"
        if not last:
            f += f",afade=t=out:st={length - xf:.3f}:d={xf:.3f}"
        f += f",adelay={int(round(b[i] * 1000))}:all=1[a{i}]"
        parts.append(f)
        labels.append(f"[a{i}]")
    parts.append("".join(labels) + f"amix=inputs={len(cues)}:normalize=0:duration=longest,"
                 f"apad=whole_dur={total_s:.3f},atrim=0:{total_s:.3f}[o]")
    _run([*args, "-filter_complex", ";".join(parts), "-map", "[o]", "-ar", str(RATE),
          "-ac", "2", "-c:a", "pcm_s16le", str(out)])
    return Path(out)
