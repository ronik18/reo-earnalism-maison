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
# A voice needs this many measured rows (units or segments) for its own rate median.
MIN_VOICE_ROWS = 5


def truncation_suspects(rows) -> list:
    """rows: [{"unit_key", "chars", "seconds"}] of one narration job (a multi-voice unit gives one
    row per segment, with "segment" (1-based) and "voice"). Returns the suspect_truncated ones,
    each with its measurements and reasons (duration at the cap, no audio, or speech too fast for a
    row of at least MIN_RATIO_CHARS characters). The rate median is taken per voice (rows with no
    voice share one median: a single-voice job is measured exactly as before)."""
    by_voice = {}
    for r in rows:
        if r["seconds"] > 0:
            by_voice.setdefault(r.get("voice"), []).append(r["chars"] / r["seconds"])
    every = [x for xs in by_voice.values() for x in xs]
    overall = statistics.median(every) if every else 0.0
    # a voice heard in only a few rows (a minor character) is measured against the job median: its
    # own median would be the suspect row itself
    medians = {v: statistics.median(x) if v is None or len(x) >= MIN_VOICE_ROWS else overall
               for v, x in by_voice.items()}
    out = []
    for r in rows:
        median = medians.get(r.get("voice"), 0.0)
        cps = r["chars"] / r["seconds"] if r["seconds"] > 0 else float("inf")
        reasons = []
        if r["seconds"] >= TRUNCATION_CAP_S:
            reasons.append(f"duration {r['seconds']:.2f} s >= {TRUNCATION_CAP_S} s")
        if r["seconds"] <= 0:
            reasons.append("no audio (0 s)")
        elif median and r["chars"] >= MIN_RATIO_CHARS and cps > CPS_RATIO * median:
            own = r.get("voice") is not None and len(by_voice[r["voice"]]) >= MIN_VOICE_ROWS
            what = f"{r['voice']} median" if own else "job median"
            reasons.append(f"{cps:.1f} chars/s > {CPS_RATIO} x {what} {median:.1f}")
        if reasons:
            row = {"unit_key": r["unit_key"], "chars": r["chars"],
                   "seconds": round(r["seconds"], 3), "chars_per_s": round(cps, 2),
                   "reasons": reasons}
            for k in ("segment", "voice"):
                if r.get(k) is not None:
                    row[k] = r[k]
            out.append(row)
    return out


# A joined unit whose length differs from its reported segments (+ gaps) by more than this is
# measured whole instead (the report does not describe the file).
SEGMENT_SLACK_S = 0.25


def narration_rows(units, wav_dir, voices=None) -> list:
    """The rows truncation_suspects measures. voices (from the job's own job.json rows): unit_key ->
    {"voice": the unit's (narrator's) voice, "segments": [{"text", "voice"}], "segment_seconds":
    [seconds] or None}. A multi-voice unit with reported segment seconds that match its WAV gives
    one row per segment, so a segment cut off inside a joined unit is still caught; otherwise a
    unit is one row (with its voice, if known). Without voices: one row per unit, as always."""
    from .film import unit_wav
    from .narration_join import joined_seconds
    rows = []
    for u in units:
        k = u["unit_key"]
        seconds = _duration(unit_wav(wav_dir, k))
        info = (voices or {}).get(k) or {}
        segs, seg_s = info.get("segments"), info.get("segment_seconds")
        if segs and seg_s and len(seg_s) == len(segs) \
                and abs(joined_seconds(seg_s, gaps_ms=info.get("segment_gaps_ms")) - seconds) \
                <= SEGMENT_SLACK_S:
            rows += [{"unit_key": k, "segment": i, "voice": s.get("voice"), "chars": len(s["text"]),
                      "seconds": float(x)} for i, (s, x) in enumerate(zip(segs, seg_s), 1)]
            continue
        rows.append({"unit_key": k, "voice": info.get("voice"), "chars": len(u["text"]),
                     "seconds": seconds})
    return rows


def narration_suspects(units, wav_dir, voices=None) -> list:
    """truncation_suspects over a job's units and WAVs (one folder or a chunk group's folders);
    voices: see narration_rows (multi-voice jobs)."""
    return truncation_suspects(narration_rows(units, wav_dir, voices))


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
