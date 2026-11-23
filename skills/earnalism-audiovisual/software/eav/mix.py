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


def loudnorm_stats(stderr: str) -> dict:
    """Parse the print_format=json block emitted by ffmpeg's loudnorm filter on stderr.

    Locates the last "[Parsed_loudnorm" marker, then the first "{" after it, and decodes one
    JSON object, ignoring any trailing text (ffmpeg 8 appends an output summary)."""
    i = stderr.rfind("[Parsed_loudnorm")
    j = stderr.find("{", i) if i >= 0 else -1
    if j < 0:
        raise ValueError("no loudnorm JSON block found in ffmpeg stderr")
    try:
        return json.JSONDecoder().raw_decode(stderr[j:])[0]
    except json.JSONDecodeError as e:
        raise ValueError(f"unparseable loudnorm JSON block: {e}") from e


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


FRAME = RATE // 100          # 10 ms analysis frames
CHUNK_FRAMES = 3000          # 30 s of audio per chunk (stereo float32 ~ 11 MB)


def _stream(path, chunk_samples: int):
    """Yield (n, 2) float32 chunks decoded by ffmpeg; memory stays bounded."""
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le",
                          "-ac", "2", "-ar", str(RATE), "-"],
                         stdout=subprocess.PIPE)
    try:
        while True:
            buf = p.stdout.read(chunk_samples * 8)
            if not buf:
                break
            yield np.frombuffer(buf, dtype=np.float32).reshape(-1, 2)
    finally:
        p.stdout.close()
        if p.wait() != 0:
            raise RuntimeError(f"ffmpeg failed decoding {path}")


def _writer(path):
    return subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(RATE),
                             "-ac", "2", "-i", "-", "-c:a", "pcm_f32le", str(path)],
                            stdin=subprocess.PIPE)


def _close(w):
    w.stdin.close()
    if w.wait() != 0:
        raise RuntimeError("ffmpeg failed writing audio")


def _frame_gain_db(speech: Path, duck_db: float) -> np.ndarray:
    """Per-10ms-frame gain in dB (0 in pauses, -duck_db while speech plays), float32."""
    levels = []
    for chunk in _stream(speech, CHUNK_FRAMES * FRAME):
        frames = len(chunk) // FRAME
        if frames:
            x = np.abs(chunk[:frames * FRAME]).max(axis=1).reshape(frames, FRAME)
            levels.append(np.sqrt((x * x).mean(axis=1)))
    rms = np.concatenate(levels) if levels else np.zeros(0, dtype=np.float32)
    active = (rms > 10 ** (-50 / 20)).astype(np.float32)
    # close (dilate 300 ms, erode 150 ms): bridges gaps under 300 ms, holds 150 ms
    dil = np.convolve(active, np.ones(30, dtype=np.float32), mode="same") > 0
    held = np.convolve(dil.astype(np.float32), np.ones(15, dtype=np.float32),
                       mode="same") >= 15
    held = held | (active > 0)
    target = np.where(held, -duck_db, 0.0).astype(np.float32)
    k = 15  # 150 ms ramps
    pad = np.pad(target, (k // 2, k - k // 2 - 1), mode="edge")
    smooth = np.convolve(pad, np.ones(k, dtype=np.float32) / k, mode="valid")
    smooth = np.where(held, np.minimum(smooth, target), smooth)
    return smooth.astype(np.float32)


def _gain_for(start: int, n: int, frame_db: np.ndarray) -> np.ndarray:
    """Linear float32 gain for samples [start, start+n), interpolated from frame gains."""
    if not len(frame_db):
        return np.ones(n, dtype=np.float32)
    centers = np.arange(len(frame_db), dtype=np.float32) * FRAME + FRAME / 2
    idx = np.arange(start, start + n, dtype=np.float32)
    db = np.interp(idx, centers, frame_db).astype(np.float32)
    return (10 ** (db / 20)).astype(np.float32)


def duck_and_master(speech: Path, score: Path, out: Path, target_lufs: float,
                    duck_db=19) -> dict:
    if not 18 <= duck_db <= 20:
        raise ValueError("duck_db must be within 18-20 dB")
    speech, score, out = Path(speech), Path(score), Path(out)
    frame_db = _frame_gain_db(speech, duck_db)
    score_gain = np.float32(10 ** (SCORE_GAIN_DB / 20))
    chunk = CHUNK_FRAMES * FRAME
    stem = out.with_name(out.stem + ".score-ducked.wav")

    def pad(a, n):
        return a if a is None else np.pad(a, ((0, n - len(a)), (0, 0)))

    with tempfile.TemporaryDirectory() as td:
        pre = Path(td) / "pre.wav"
        w_stem, w_pre = _writer(stem), _writer(pre)
        try:
            gs, gc, pos = _stream(speech, chunk), _stream(score, chunk), 0
            while True:
                a, b = next(gs, None), next(gc, None)
                if a is None and b is None:
                    break
                n = max(len(a) if a is not None else 0, len(b) if b is not None else 0)
                a = np.zeros((n, 2), np.float32) if a is None else pad(a, n)
                b = np.zeros((n, 2), np.float32) if b is None else pad(b, n)
                b = b * score_gain * _gain_for(pos, n, frame_db)[:, None]
                w_stem.stdin.write(b.astype(np.float32).tobytes())
                w_pre.stdin.write((a + b).astype(np.float32).tobytes())
                pos += n
        finally:
            _close(w_stem)
            _close(w_pre)
        res = _loudnorm_gated(pre, out, target_lufs)
    res.update({"score_stem": str(stem), "duck_db": duck_db, "target_lufs": target_lufs})
    return res


def _loudnorm_gated(pre: Path, out: Path, target_lufs: float) -> dict:
    """Two-pass linear loudnorm to target_lufs; raises ValueError unless the result meets
    target +-1 LU and true peak <= -1.0 dBTP."""
    tp = TRUE_PEAK_LIMIT
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(pre), "-af",
                        f"loudnorm=I={target_lufs}:TP={tp}:LRA=11:print_format=json",
                        "-f", "null", "-"], check=True, capture_output=True, text=True)
    stats = loudnorm_stats(r.stderr)
    if any(str(stats[k]).strip("-+").lower() in ("inf", "nan") for k in ("input_i", "input_tp")):
        raise ValueError("master misses gate: input is silent or unmeasurable")
    f = (f"loudnorm=I={target_lufs}:TP={tp}:LRA=11:"
         f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
         f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
         f"offset={stats['target_offset']}:linear=true")
    _run(["-i", str(pre), "-af", f, "-ar", str(RATE), "-ac", "2",
          "-c:a", "pcm_s16le", str(out)])
    res = measure(out)
    if res["true_peak"] > -1.0 or abs(res["lufs"] - target_lufs) > 1:
        raise ValueError(f"master misses gate: {res} (target {target_lufs} LUFS, TP <= -1.0)")
    return res


def master(speech: Path, out: Path, target_lufs: float) -> dict:
    """Narration-only master with the same gate as duck_and_master (no score)."""
    res = _loudnorm_gated(Path(speech), Path(out), target_lufs)
    res["target_lufs"] = target_lufs
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
