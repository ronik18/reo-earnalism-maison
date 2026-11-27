"""Quality checks: contact sheet, loop-closure SSIM, speech onset and truncated narration (ffmpeg)."""
import math
import re
import statistics
import subprocess
import tempfile
from pathlib import Path


def _duration(video) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(video)], check=True, capture_output=True, text=True)
    return float(r.stdout.strip())


# Parler-TTS stops at a hard ~30.2 s per generate(): a unit this long was probably cut off.
TRUNCATION_CAP_S = 29.0
# A unit whose characters/second exceed this multiple of the job's median lost words.
CPS_RATIO = 1.6
# Below this many characters a unit's chars/s is dominated by its leading/trailing breath, so the
# ratio test never flags it (the job median, over every unit, is robust to a few of them); the
# duration test still applies, and a unit with no audio at all is always suspect.
MIN_RATIO_CHARS = 40


def truncation_suspects(rows) -> list:
    """rows: [{"unit_key", "chars", "seconds"}] of one narration job. Returns the suspect_truncated
    ones, each with its measurements and reasons (duration at the cap, no audio, or speech too
    fast for a unit of at least MIN_RATIO_CHARS characters)."""
    rates = [r["chars"] / r["seconds"] for r in rows if r["seconds"] > 0]
    median = statistics.median(rates) if rates else 0.0
    out = []
    for r in rows:
        cps = r["chars"] / r["seconds"] if r["seconds"] > 0 else float("inf")
        reasons = []
        if r["seconds"] >= TRUNCATION_CAP_S:
            reasons.append(f"duration {r['seconds']:.2f} s >= {TRUNCATION_CAP_S} s")
        if r["seconds"] <= 0:
            reasons.append("no audio (0 s)")
        elif median and r["chars"] >= MIN_RATIO_CHARS and cps > CPS_RATIO * median:
            reasons.append(f"{cps:.1f} chars/s > {CPS_RATIO} x job median {median:.1f}")
        if reasons:
            out.append({"unit_key": r["unit_key"], "chars": r["chars"],
                        "seconds": round(r["seconds"], 3), "chars_per_s": round(cps, 2),
                        "reasons": reasons})
    return out


def narration_suspects(units, wav_dir) -> list:
    """truncation_suspects over a job's units and WAVs (one folder or a chunk group's folders)."""
    from .film import unit_wav
    return truncation_suspects([{"unit_key": u["unit_key"], "chars": len(u["text"]),
                                 "seconds": _duration(unit_wav(wav_dir, u["unit_key"]))}
                                for u in units])


def speech_onset(audio, threshold_db=-40.0, rate=16000):
    """Seconds before the first sample louder than threshold_db (None if it never is)."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", str(rate),
                          "-f", "f32le", "-"], check=True, capture_output=True).stdout
    samples = np.abs(np.frombuffer(raw, np.float32))
    loud = np.nonzero(samples >= 10 ** (threshold_db / 20))[0]
    return round(float(loud[0]) / rate, 4) if loud.size else None


MAX_SHEET_FRAMES = 120  # 24 rows of 5 at 320 px: 7,680 px tall


def contact_sheet(video, out, every_s=1.0, cols=5, thumb_h=320):
    """Tile one thumbnail per `every_s` seconds into a single image. A long film is sampled
    more sparsely so the sheet stays at most MAX_SHEET_FRAMES thumbnails (JPEG caps a side at
    65,500 px; a 21-minute film at 1 s per thumbnail would need 80,640 px)."""
    every_s = max(every_s, _duration(video) / MAX_SHEET_FRAMES)
    n = max(1, int(math.ceil(_duration(video) / every_s)))
    rows = math.ceil(n / cols)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf",
                    f"fps=1/{every_s},scale=-2:{thumb_h},tile={min(cols, n)}x{rows}",
                    "-frames:v", "1", "-update", "1", str(out)], check=True)
    return Path(out)


def loop_score(video) -> float:
    """SSIM between the last and the first frame, clamped to [0, 1]."""
    with tempfile.TemporaryDirectory() as td:
        first, last = Path(td) / "first.png", Path(td) / "last.png"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-frames:v", "1",
                        str(first)], check=True)
        # -update keeps overwriting one file, so it ends on the final frame
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-sseof", "-0.5", "-i", str(video),
                        "-update", "1", str(last)], check=True)
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(last), "-i", str(first),
                            "-lavfi", "ssim", "-f", "null", "-"], check=True,
                           capture_output=True, text=True)
    m = re.search(r"All:(-?[\d.]+|nan|inf)", r.stderr)
    if not m:
        raise RuntimeError("could not parse ssim output")
    return min(1.0, max(0.0, float(m.group(1))))
