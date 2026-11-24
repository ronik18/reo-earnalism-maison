"""Reel quality checks: contact sheet and loop-closure SSIM (ffmpeg subprocess)."""
import math
import re
import subprocess
import tempfile
from pathlib import Path


def _duration(video) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(video)], check=True, capture_output=True, text=True)
    return float(r.stdout.strip())


def speech_onset(audio, threshold_db=-40.0, rate=16000):
    """Seconds before the first sample louder than threshold_db (None if it never is)."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", str(rate),
                          "-f", "f32le", "-"], check=True, capture_output=True).stdout
    samples = np.abs(np.frombuffer(raw, np.float32))
    loud = np.nonzero(samples >= 10 ** (threshold_db / 20))[0]
    return round(float(loud[0]) / rate, 4) if loud.size else None


def contact_sheet(video, out, every_s=1.0, cols=5, thumb_h=320, max_tiles=100):
    """Tile one thumbnail per `every_s` seconds into a single image; a long video is sampled
    more sparsely so the sheet holds at most `max_tiles` thumbnails (JPEG caps at 65500 px)."""
    duration = _duration(video)
    every_s = max(every_s, duration / max_tiles)
    n = max(1, int(math.ceil(duration / every_s)))
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
