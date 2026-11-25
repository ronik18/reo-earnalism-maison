"""Bounded public preview clip: the opening of chapter 1, cut at a silence, 96 kbps MP3.

Maison serves this clip publicly (podcast enclosure, title-page sample); the bounds below mirror
library/audio_preview.py (MAX_DURATION_MS, MAX_BYTES, audio/mpeg, 96 kbps). The measurement record
carries the proof fields prepared_clip() checks. `asset_id` is assigned when the server stages the
clip as a preview_audio asset, so it is deliberately absent here; this module never marks clearance.
"""
import re
import subprocess
from pathlib import Path

from . import film
from .record import sha256_file

MAX_DURATION_MS = 120000
MAX_BYTES = 2 * 1024 * 1024
QUALITY_KBPS = 96
SAFETY_MS = 1000       # encoder padding must never push the clip past MAX_DURATION_MS
MIN_CUT_S = 10.0       # a preview shorter than this is not a useful sample
SILENCE_DB, SILENCE_S = -35, 0.2


def silences(path, window_s: float) -> list:
    """(start, end) of each silence in the first window_s seconds."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-v", "info", "-t", f"{window_s + 5:.3f}", "-i", str(path),
                        "-af", f"silencedetect=n={SILENCE_DB}dB:d={SILENCE_S}", "-f", "null", "-"],
                       check=True, capture_output=True, text=True)
    out, start = [], None
    for line in r.stderr.splitlines():
        if m := re.search(r"silence_start: (-?[0-9.]+)", line):
            start = max(0.0, float(m[1]))
        elif (m := re.search(r"silence_end: ([0-9.]+)", line)) and start is not None:
            out.append((start, float(m[1])))
            start = None
    return out


def cut_point(path) -> float:
    """Latest silence midpoint within the bound; ValueError when none qualifies."""
    limit = (MAX_DURATION_MS - SAFETY_MS) / 1000
    mids = [(a + b) / 2 for a, b in silences(path, limit) if MIN_CUT_S <= (a + b) / 2 <= limit]
    if not mids:
        raise ValueError(f"no silence between {MIN_CUT_S:.0f} s and {limit:.0f} s to end the preview on")
    return max(mids)


def cut_preview(src, out, unit_id: str) -> dict:
    """Cut src (the chapter-1 narration) to out (MP3) and return the measurement record."""
    out = Path(out)
    end = cut_point(src)
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-v", "error", "-i", str(src), "-t", f"{end:.3f}",
                    "-ar", "48000", "-ac", "2", "-c:a", "libmp3lame", "-b:a", f"{QUALITY_KBPS}k", str(out)],
                   check=True)
    duration_ms, size = round(film._duration(out) * 1000), out.stat().st_size
    if not 1 <= duration_ms <= MAX_DURATION_MS or not 0 < size <= MAX_BYTES:
        out.unlink()
        raise ValueError(f"preview out of bounds: {duration_ms} ms, {size} bytes "
                         f"(limits {MAX_DURATION_MS} ms, {MAX_BYTES} bytes)")
    return {"unit_id": unit_id, "sha256": sha256_file(out), "bytes": size, "duration_ms": duration_ms,
            "quality_kbps": QUALITY_KBPS, "content_type": "audio/mpeg", "prepared": True,
            "cut_at_ms": round(end * 1000),
            "measurement_evidence": (f"ffprobe duration {duration_ms} ms, {size} bytes; ended at a silence "
                                     f"({SILENCE_DB} dB, >= {SILENCE_S} s) found by ffmpeg silencedetect; "
                                     f"ffmpeg libmp3lame {QUALITY_KBPS} kbps")}
