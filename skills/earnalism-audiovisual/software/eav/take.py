"""ElevenLabs narration takes: tagged-script checks and sample-exact slicing (owner 2026-11-24).

The operator generates ONE continuous Eleven v3 take per plan scene from a tagged script (the
scene's exact text with audio tags such as "[softly]" or "[long pause]" between the words) and
downloads it. This module proves the script still carries every character of the book text and
cuts the take into one WAV per voice unit (the plan's sentence units) so that the WAVs, joined,
are the decoded take sample for sample. Cuts fall inside the take's own silences; where the take
has fewer usable silences than joins, the cut is estimated and recorded as such.
"""
import re
import subprocess
import wave
from pathlib import Path

import numpy as np

TAG = re.compile(r"(\[[^\[\]\n]*\])")
FRAME_S = 0.010            # energy frames for silence detection
SILENCE_REL_DB = 35.0      # a frame this far below the loudest frame is silence
MIN_SILENCE_S = 0.15       # shorter dips (commas, plosives) are not cut points
FALLBACK_FRAME_S = 0.020   # estimated cut: the quietest 20 ms frame ...
FALLBACK_WINDOW_S = 0.400  # ... within +-400 ms of the expected time
SILENT_TAKE_DB = -60.0     # a take whose loudest frame is below this is silent
_SKIP_COST = 1e6           # an estimated boundary costs more than any distance


def _norm(text: str) -> str:
    return " ".join((text or "").split())


def strip_tags(tagged: str, source: str = None) -> str:
    """The script without its audio tags. With `source`, a bracket run that the book text itself
    has at that position is kept as text; every other square-bracket run is a tag. A removed tag
    leaves one space only where it stood between two spaces ("word [sad] word"); glued to a word
    or punctuation on one side ("garden [pause].", "“[whispers] Who") it leaves nothing."""
    src = _norm(source) if source is not None else None
    parts = TAG.split(tagged or "")
    out, lstrip_next = "", False
    for i, part in enumerate(parts):
        if i % 2 == 0:
            out += part.lstrip() if lstrip_next else part
            lstrip_next = False
            continue
        if src is not None:
            done = _norm(out)
            if src.startswith(done) and src[len(done):].lstrip().startswith(part):
                out += part  # the book's own bracketed text
                continue
        nxt = parts[i + 1] if i + 1 < len(parts) else ""
        left = out[-1:].isspace() if out else False
        right = nxt[:1].isspace()
        if left and right:
            out = out.rstrip() + " "
            lstrip_next = True
        elif left:
            out = out.rstrip()
        elif right:
            lstrip_next = True
    return _norm(out)


def check_script(scene_text: str, tagged: str) -> str:
    """Refuse a tagged script whose words differ in any character from the scene text (tags
    removed, whitespace normalised). Returns the normalised scene text."""
    want = _norm(scene_text)
    if not want:
        raise ValueError("the scene has no text")
    if TAG.search(tagged or "") and any(not t.strip("[] ") for t in TAG.findall(tagged)):
        raise ValueError("empty audio tag [] in the script")
    got = strip_tags(tagged, scene_text)
    if got != want:
        k = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
        raise ValueError(f"script differs from the book text at character {k}: book "
                         f"{want[max(0, k - 30):k + 30]!r}, script {got[max(0, k - 30):k + 30]!r}; "
                         "tags may only be inserted between the words, never change them")
    return want


# ------------------------------------------------------------------------------ slicing
def _probe(path) -> tuple:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                          "stream=sample_rate,channels", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout.strip().splitlines()
    if not out:
        raise ValueError(f"{path} has no audio stream")
    rate, channels = (int(v) for v in out[0].split(",")[:2])
    return rate, channels


def decode(path) -> tuple:
    """(int16 samples [n, channels], rate): the take as ffmpeg decodes it, native rate/channels."""
    rate, channels = _probe(path)
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-f", "s16le",
                          "-acodec", "pcm_s16le", "-ac", str(channels), "-ar", str(rate), "-"],
                         check=True, capture_output=True).stdout
    x = np.frombuffer(raw, dtype="<i2")
    return x.reshape(-1, channels), rate


def _frame_db(x: np.ndarray, hop: int) -> np.ndarray:
    n = len(x) // hop
    mono = x[:n * hop].astype(np.float64).mean(axis=1) / 32768.0
    rms = np.sqrt((mono.reshape(n, hop) ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-6))


def _silences(db: np.ndarray, hop: int, rate: int) -> tuple:
    """Interior silences [(start, end) samples] of at least MIN_SILENCE_S, and the speech span."""
    loud = db.max()
    quiet = db < loud - SILENCE_REL_DB
    if loud < SILENT_TAKE_DB or quiet.all():
        raise ValueError("the take is silent")
    speech = np.flatnonzero(~quiet)
    first, last = speech[0], speech[-1]
    out, k = [], first
    while k <= last:
        if quiet[k]:
            j = k
            while quiet[j]:
                j += 1
            if (j - k) * hop >= MIN_SILENCE_S * rate:
                out.append((k * hop, j * hop))
            k = j
        else:
            k += 1
    return out, first * hop, (last + 1) * hop


def _assign(expected: list, mids: list, allow_skip: bool) -> list:
    """For each boundary the index of its silence (or None), strictly increasing, minimising the
    total distance to the expected times; with allow_skip as many boundaries as possible get one."""
    n, m, inf = len(expected), len(mids), float("inf")
    dp = [[0.0] * (m + 1)] + [[inf] * (m + 1) for _ in range(n)]
    how = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(m + 1):
            best, step = (dp[i - 1][j] + _SKIP_COST, "skip") if allow_skip else (inf, None)
            if j and dp[i][j - 1] < best:
                best, step = dp[i][j - 1], "unused"
            if j and dp[i - 1][j - 1] + abs(mids[j - 1] - expected[i - 1]) < best:
                best, step = dp[i - 1][j - 1] + abs(mids[j - 1] - expected[i - 1]), "take"
            dp[i][j], how[i][j] = best, step
    if dp[n][m] == inf:
        raise ValueError("no monotonic assignment of silences")
    picks, i, j = [None] * n, n, m
    while i:
        step = how[i][j]
        if step == "take":
            picks[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif step == "unused":
            j -= 1
        else:
            i -= 1
    return picks


def _estimate(x, rate, expected: int, lo: int, hi: int) -> int:
    """The centre of the quietest 20 ms frame (grid from the start of the take) within
    +-400 ms of the expected sample, kept strictly between lo and hi."""
    f = int(round(FALLBACK_FRAME_S * rate))
    w = int(round(FALLBACK_WINDOW_S * rate))
    a, b = max(expected - w, lo + 1), min(expected + w, hi - 1)
    starts = [s for s in range((a + f - 1) // f * f, b - f + 1, f)]
    if not starts:
        return min(max(expected, lo + 1), hi - 1)
    mono = x.astype(np.float64).mean(axis=1)
    energy = [float((mono[s:s + f] ** 2).mean()) for s in starts]
    return starts[int(np.argmin(energy))] + f // 2


def _write(path: Path, x: np.ndarray, rate: int):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.ascontiguousarray(x).astype("<i2").tobytes())


def slice_take(audio, units: list, out_dir) -> dict:
    """Write <unit_key>.wav for every unit into out_dir; joined, they are the decoded take.

    units: the plan's voice units of this scene, in order ({"unit_key", "text"}). The n-1 cuts
    sit at the midpoints of detected silences, each the nearest (in total) to its character-
    proportional expected time, monotonic, one per silence; without enough silences the rest
    are estimated (quietest 20 ms frame within +-400 ms) and listed in "estimated"."""
    if not units:
        raise ValueError("no units for this take")
    x, rate = decode(audio)
    n = len(x)
    hop = max(1, int(round(FRAME_S * rate)))
    if n < hop * 2:
        raise ValueError(f"{audio} is empty")
    sil, s0, s1 = _silences(_frame_db(x, hop), hop, rate)
    chars = [len(u["text"]) for u in units]
    total = sum(chars) or 1
    cum = np.cumsum(chars)[:-1]
    expected = [s0 + (s1 - s0) * c / total for c in cum]
    mids = [(a + b) // 2 for a, b in sil]
    picks = _assign(expected, mids, allow_skip=len(mids) < len(expected))
    cuts = [mids[p] if p is not None else None for p in picks]
    for i, c in enumerate(cuts):
        if c is None:
            lo = cuts[i - 1] if i else 0
            hi = next((c2 for c2 in cuts[i + 1:] if c2 is not None), n)
            cuts[i] = _estimate(x, rate, int(round(expected[i])), lo, hi)
    edges = [0] + cuts + [n]
    if any(b <= a for a, b in zip(edges, edges[1:])):
        raise ValueError("the take is too short for its units")
    out_dir = Path(out_dir)
    rows = []
    for u, a, b in zip(units, edges, edges[1:]):
        _write(out_dir / f"{u['unit_key']}.wav", x[a:b], rate)
        rows.append({"unit_key": u["unit_key"], "start_sample": int(a), "end_sample": int(b)})
    bounds = []
    for i, c in enumerate(cuts):
        b = {"after": units[i]["unit_key"], "before": units[i + 1]["unit_key"],
             "at_s": round(c / rate, 4), "expected_s": round(expected[i] / rate, 4),
             "method": "silence" if picks[i] is not None else "estimated"}
        if picks[i] is not None:
            a_, b_ = sil[picks[i]]
            b["silence_s"] = [round(a_ / rate, 4), round(b_ / rate, 4)]
        bounds.append(b)
    return {"rate": rate, "channels": int(x.shape[1]), "samples": n, "units": rows,
            "boundaries": bounds, "estimated": [b["after"] for b in bounds if b["method"] == "estimated"]}
