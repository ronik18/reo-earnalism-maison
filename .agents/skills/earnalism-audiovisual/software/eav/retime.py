"""Pause re-timing: narration pauses are re-set by punctuation and filled with the take's own room tone.

TTS takes come with commas and sentence ends too short, and joins filled with digital silence. Here
`detect_pauses` finds the gaps (ffmpeg silencedetect), `plan_pauses` matches them by position to the
punctuation of the script text (`match_pauses`: an unpunctuated breath keeps its place and length) and picks a
seeded target length, and `retime` rebuilds the take: each
pause keeps 40 ms of the original at both sides, the middle becomes room tone, and every join is a
40 ms equal-power crossfade, so there is no click and no digital zero. `room_tone` loops the quietest
0.25 s of the take (30 ms crossfades), level-matched to -62...-68 dBFS; a take whose quietest part is
digital silence gets a smooth synthetic floor at -65 dBFS instead. Needs numpy and ffmpeg.
"""
import random
import re
import subprocess
from pathlib import Path

import numpy as np

from .text import sentences

SR = 48000
KEEP_S = 0.04   # original kept at each side of a pause; equals the join crossfade
XF_S = 0.04     # equal-power join crossfade (30-50 ms)
LOOP_XF_S = 0.03
TONE_DB = (-68.0, -62.0)
TONE_FALLBACK_DB = -65.0

# target pause (seconds) by kind, before the +-15 % seeded jitter
TARGETS = {"comma": (0.40, 0.55), "sentence": (0.80, 1.00), "turn": (1.40, 1.60),
           "scene": (2.00, 2.00), "heading_before": (2.50, 3.00), "heading_after": (1.50, 1.50)}
JITTER = 0.15
_STRENGTH = {"comma": 1, "sentence": 2, "turn": 3}
_MARK = {",": "comma", ";": "comma", "—": "comma", "।": "sentence", "?": "sentence", "!": "turn"}
_TAG = re.compile(r"\[[^\]]*\]")
_SCENE_LINE = re.compile(r"^\s*(\*{3,}|-{3,}|—{3,}|#\s*scene.*)\s*$", re.I)
# a short heading line: an ordinal then পরিচ্ছেদ ("প্রথম পরিচ্ছেদ।"), or পরিচ্ছেদ with a number; not prose
_HEADING_LINE = re.compile(r"^\s*(#+\s*)?(\S+\s+পরিচ্ছেদ|পরিচ্ছেদ(\s+[\d০-৯]+)?)\s*[।.]?\s*$")


def _kinds(text: str) -> list[str]:
    """Pause kinds in reading order. [audio tags] are ignored; a run of marks counts once, as its
    strongest; a scene break or পরিচ্ছেদ heading line replaces the sentence end just before it."""
    kinds: list[str] = []
    fresh = False  # a mark was the last thing seen (no words since)
    for line in _TAG.sub("", text).splitlines():
        if _SCENE_LINE.match(line):
            if fresh and kinds and kinds[-1] in ("sentence", "turn"):
                kinds.pop()
            kinds.append("scene")
            fresh = False
            continue
        if _HEADING_LINE.match(line):
            if fresh and kinds and kinds[-1] in ("sentence", "turn"):
                kinds.pop()
            kinds += ["heading_before", "heading_after"]
            fresh = False
            continue
        run = None
        for ch in line:
            kind = _MARK.get(ch)
            if kind:
                run = kind if run is None or _STRENGTH[kind] > _STRENGTH[run] else run
            elif not ch.isspace() and ch not in "\"'“”‘’()…":
                if run:
                    kinds.append(run)
                    run = None
                fresh = False
                continue
            if ch in _MARK:
                fresh = True
        if run:
            kinds.append(run)
            fresh = True
    return kinds


def clauses(text: str) -> list[tuple[str, str | None]]:
    """The text cut at exactly the pause points `_kinds` counts, in order: [(clause text, kind of the pause after
    it)], the last clause's kind being its own closing mark's (or None). The clauses joined with spaces spell the
    text (whitespace aside); a heading line is its own clause between heading_before and heading_after. A scene-
    break line is not spoken: it only sets the pause before the next clause."""
    out: list[list] = []
    cur: list[str] = []
    fresh = False

    def flush(kind):
        body = " ".join("".join(cur).split())
        if body:
            out.append([body, kind])
        cur.clear()
    for line in _TAG.sub("", text).splitlines():
        if _SCENE_LINE.match(line):
            if fresh and out and out[-1][1] in ("sentence", "turn"):
                out[-1][1] = "scene"
            else:
                flush("scene")
            fresh = False
            continue
        if _HEADING_LINE.match(line):
            if fresh and out and out[-1][1] in ("sentence", "turn"):
                out[-1][1] = "heading_before"
            else:
                flush("heading_before")
            out.append([" ".join(line.split()), "heading_after"])
            fresh = False
            continue
        run = None
        for ch in line:
            kind = _MARK.get(ch)
            if kind:
                run = kind if run is None or _STRENGTH[kind] > _STRENGTH[run] else run
                cur.append(ch)
                fresh = True
                continue
            if run and ch in "“‘(":   # an opening quote belongs to the clause it opens
                flush(run)
                run = None
            if not ch.isspace() and ch not in "\"'“”‘’()…":
                if run:
                    flush(run)
                    run = None
                fresh = False
            cur.append(ch)
        if run:
            flush(run)
            fresh = True
        cur.append(" ")
    flush(None)
    return [tuple(c) for c in out]


# Pause mapping (G3, I1): a pause is matched to a punctuation mark by POSITION, never by order alone.
# 1. Proposal: each mark's place is estimated from its character offset over the take's speech time (pauses
#    excluded) and a monotonic alignment proposes pairs within a wide window (POS_PROPOSE_*): |estimated - measured|
#    seconds per pair, POS_SKIP_PER_S per second of a pause left unmatched (a long pause is likelier punctuation than
#    a breath), more than any pair for a mark left unmatched.
# 2. Acceptance: every proposed pair is re-checked against its LOCAL estimate, interpolated by characters between
#    the neighbouring accepted pairs (the local speaking rate), within a tight window: POS_TOL_CHARS characters at
#    that local rate, clamped to POS_TOL_MIN_S..POS_TOL_MAX_S (about 1.5 Bengali words). A pause that is already
#    as long as its mark's own shortest target (TARGETS low end less the jitter: a held "!" of 1.6 s, say) is
#    stronger evidence and gets POS_TOL_LONG times that window (at most 0.9 s); a breath never does unless it is that
#    long. The worst pair outside its window is dropped and the rest re-checked until none is. A mark left without a
#    pause stays unmatched and is reported; a breath is never stretched into its pause.
# An unmatched pause is a breath and keeps its place and length.
POS_PROPOSE_S, POS_PROPOSE_FRAC = 2.5, 0.12
POS_TOL_CHARS, POS_TOL_MIN_S, POS_TOL_MAX_S, POS_TOL_LONG = 10, 0.3, 0.6, 1.5
POS_SKIP_PER_S = 2.0
_SPOKEN = re.compile(r"[\s\"'“”‘’()…]")


def _spoken_len(text: str) -> int:
    return len(_SPOKEN.sub("", text))


def match_pauses(text: str, pauses: list[tuple[float, float]], bounds: tuple[float, float] | None = None) -> list[dict]:
    """The text's interior pause marks (`clauses`, every clause boundary in order) matched to the measured pauses by
    position. `bounds` is the take's speech (first, last) in seconds; without it the speech is taken to run from 0
    to the last pause's end. Returns one row per boundary: {"clause": index of the clause the mark ends, "kind",
    "pause": index into `pauses` or None (no pause inside its window: reported, never stretched), "expected_s": the
    mark's local estimate in the take, "error_s": measured pause start minus expected (None when unmatched),
    "tol_s": its acceptance window, "local_s_per_char": the local speaking rate it was scaled by}. The final clause's own closing mark is not a boundary: the
    trailing silence of a take is never a pause."""
    cl = clauses(text)
    marks = cl[:-1]
    pauses = sorted(pauses)
    if bounds is None:
        bounds = (0.0, max((e for _, e in pauses), default=0.0))
    t0, t1 = bounds
    inner = [(s, e) for s, e in pauses]
    speech = max((t1 - t0) - sum(e - s for s, e in inner), 1e-6)
    total = max(sum(_spoken_len(c) for c, _ in cl), 1)
    expected, cum = [], 0
    for c, _ in marks:
        cum += _spoken_len(c)
        expected.append(cum / total * speech)
    at, spoken, prev = [], 0.0, t0
    for s, e in inner:
        spoken += max(0.0, s - prev)
        at.append(spoken)
        prev = max(prev, e)
    tol = max(POS_PROPOSE_S, POS_PROPOSE_FRAC * speech)   # proposal only; acceptance is local and tight
    miss = tol + 1.0
    k_n, p_n = len(marks), len(inner)
    inf = float("inf")
    cost = [[inf] * (p_n + 1) for _ in range(k_n + 1)]
    back = [[None] * (p_n + 1) for _ in range(k_n + 1)]
    cost[0][0] = 0.0
    for k in range(k_n + 1):
        for j in range(p_n + 1):
            c = cost[k][j]
            if c == inf:
                continue
            if j < p_n:   # pause j is a breath
                v = c + POS_SKIP_PER_S * (inner[j][1] - inner[j][0])
                if v < cost[k][j + 1]:
                    cost[k][j + 1], back[k][j + 1] = v, "breath"
            if k < k_n:   # mark k has no pause
                v = c + miss
                if v < cost[k + 1][j]:
                    cost[k + 1][j], back[k + 1][j] = v, "unpaused"
            if k < k_n and j < p_n and abs(expected[k] - at[j]) <= tol:
                v = c + abs(expected[k] - at[j])
                if v < cost[k + 1][j + 1]:
                    cost[k + 1][j + 1], back[k + 1][j + 1] = v, "pair"
    pair = [None] * k_n
    k, j = k_n, p_n
    while k or j:
        step = back[k][j]
        if step == "pair":
            k, j = k - 1, j - 1
            pair[k] = j
        elif step == "breath":
            j -= 1
        else:
            k -= 1

    cum = []
    c = 0
    for txt, _ in marks:
        c += _spoken_len(txt)
        cum.append(c)

    def local(k):   # (estimate in speech time, s per char) of mark k between its accepted neighbours
        a = next(((at[pair[i]], cum[i]) for i in range(k - 1, -1, -1) if pair[i] is not None), (0.0, 0))
        b = next(((at[pair[i]], cum[i]) for i in range(k + 1, k_n) if pair[i] is not None), (speech, total))
        rate = (b[0] - a[0]) / max(b[1] - a[1], 1)
        return a[0] + (cum[k] - a[1]) * rate, rate

    def window(rate, k=None, j=None):
        w = min(max(POS_TOL_CHARS * rate, POS_TOL_MIN_S), POS_TOL_MAX_S)
        if j is not None and inner[j][1] - inner[j][0] >= TARGETS[marks[k][1]][0] * (1 - JITTER):
            w *= POS_TOL_LONG   # a pause already as long as its mark's punctuation pause
        return w
    for _ in range(k_n + 1):   # drop the worst pair outside its local window until every pair is inside
        worst, worst_by = None, 0.0
        for k in range(k_n):
            if pair[k] is None:
                continue
            est, rate = local(k)
            over = abs(at[pair[k]] - est) - window(rate, k, pair[k])
            if over > worst_by:
                worst, worst_by = k, over
        if worst is None:
            break
        pair[worst] = None

    def timeline(sp):   # a speech time back on the take's timeline (the pauses before it added back)
        t, before = t0 + sp, 0.0
        for (s, e), a in zip(inner, at):
            if a <= sp:
                before += e - s
        return t + before
    rows = []
    for k, (c, kind) in enumerate(marks):
        j = pair[k]
        est, rate = local(k)
        err = None if j is None else at[j] - est          # in speech time: the pauses between are not speech
        exp_t = timeline(est) if j is None else inner[j][0] - err
        rows.append({"clause": k, "kind": kind, "pause": j, "expected_s": round(exp_t, 3),
                     "error_s": None if err is None else round(err, 3),
                     "tol_s": round(window(rate, k, j), 3), "local_s_per_char": round(rate, 4)})
    return rows


def plan_pauses(text: str, pauses: list[tuple[float, float]], rng_seed: int,
                bounds: tuple[float, float] | None = None) -> list[tuple[float, float, float]]:
    """(start, end, target_s) per detected pause: each pause matched by position to the punctuation mark nearest
    its place in the text (`match_pauses`; never by order alone) gets a target drawn from that mark's kind range and
    varied +-15 % (seeded). A pause matched to no mark (an unpunctuated breath) keeps its place and length."""
    rng = random.Random(rng_seed)
    pauses = sorted(pauses)
    kind_of = {r["pause"]: r["kind"] for r in match_pauses(text, pauses, bounds) if r["pause"] is not None}
    plan = []
    for i, (s, e) in enumerate(pauses):
        if i in kind_of:
            lo, hi = TARGETS[kind_of[i]]
            target = rng.uniform(lo, hi) * rng.uniform(1 - JITTER, 1 + JITTER)
        else:
            target = e - s
        plan.append((s, e, round(target, 4)))
    return plan


def sentence_spans(text: str, start: float, end: float, pauses: list[tuple[float, float]],
                   tol: float = 0.02) -> tuple[list[tuple[float, float]], str] | None:
    """(start, end) seconds of each sentence of `text` (eav.text.sentences) inside a passage that runs
    start..end, cut at the measured pauses: a sentence ends where its pause begins and the next starts where
    it ends. Pauses are matched by position to the text's punctuation (`match_pauses`, as plan_pauses does), keeping
    the ones at a sentence end; when a sentence end matched no pause, the n-1 longest pauses inside the passage are
    the sentence ends (a heuristic choice among measured pauses). Returns (spans, mapping) with mapping
    "single" | "punctuation" | "longest", or None when the passage holds fewer pauses than sentence ends."""
    n = len(sentences(text))
    if n <= 1:
        return [(start, end)], "single"
    inner = sorted((s, e) for s, e in pauses if s >= start - tol and e <= end + tol)
    rows = match_pauses(text, inner, (start, end))
    ends = [r for r in rows if r["kind"] in ("sentence", "turn")]
    if len(ends) == n - 1 and all(r["pause"] is not None for r in ends):
        cuts, mapping = [inner[r["pause"]] for r in ends], "punctuation"
    elif len(inner) >= n - 1:
        cuts, mapping = sorted(sorted(inner, key=lambda p: p[0] - p[1])[:n - 1]), "longest"
    else:
        return None
    marks = [start] + [t for c in cuts for t in c] + [end]
    return [(marks[i], marks[i + 1]) for i in range(0, len(marks), 2)], mapping


def detect_pauses(path: Path, threshold_db: float = -38, min_s: float = 0.18) -> list[tuple[float, float]]:
    """Interior pauses (start, end) in seconds; leading and trailing silence is not a pause."""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
                        f"silencedetect=noise={threshold_db}dB:d={min_s}", "-f", "null", "-"],
                       capture_output=True, text=True, check=True)
    pauses, start = [], None
    for line in r.stderr.splitlines():
        m = re.search(r"silence_start: (-?[\d.]+)", line)
        if m:
            start = max(0.0, float(m.group(1)))
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m and start is not None:
            if start > 0.01:
                pauses.append((start, float(m.group(1))))
            start = None
    return pauses


def read(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def write(path: Path, y: np.ndarray) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-", str(path)],
                   input=y.astype(np.float32).tobytes(), check=True)


def _crossfade(a: np.ndarray, b: np.ndarray, xf: int) -> np.ndarray:
    """Join b after a with an equal-power overlap of xf samples (shortens the result by xf)."""
    if len(a) == 0:
        return b.copy()
    xf = min(xf, len(a), len(b))
    if xf <= 0:
        return np.concatenate([a, b])
    th = np.linspace(0, np.pi / 2, xf, dtype=np.float32)
    mid = a[-xf:] * np.cos(th) + b[:xf] * np.sin(th)
    return np.concatenate([a[:-xf], mid, b[xf:]])


def _db(x: np.ndarray) -> float:
    return 20 * np.log10(max(float(np.sqrt(np.mean(x.astype(np.float64) ** 2))), 1e-12))


def _tone_seed(x: np.ndarray) -> np.ndarray:
    """The level-matched seed segment (quietest 0.25 s of the take) that room tone loops."""
    w = min(int(0.25 * SR), len(x))
    hop = int(0.05 * SR)
    if len(x) > w:  # window energies from a cumulative sum: one pass over the take
        c = np.concatenate([[0.0], np.cumsum(x.astype(np.float64) ** 2)])
        starts = np.arange(0, len(x) - w + 1, hop)
        i = int(starts[int(np.argmin(c[starts + w] - c[starts]))])
    else:
        i = 0
    seg = x[i:i + w].astype(np.float32)
    seg = seg - np.float32(np.mean(seg))
    if w < int(0.1 * SR) or _db(seg) < -100:  # digital silence (or no usable audio): smooth synthetic floor
        noise = np.random.default_rng(0).standard_normal(int(0.25 * SR) + 15).astype(np.float32)
        seg = np.convolve(noise, np.ones(16, np.float32) / 16, mode="valid")[:int(0.25 * SR)]
        target = TONE_FALLBACK_DB
    else:
        target = min(max(_db(seg), TONE_DB[0]), TONE_DB[1])
    return seg * np.float32(10 ** ((target - _db(seg)) / 20))


def _loop(seg: np.ndarray, n: int) -> np.ndarray:
    xf = int(LOOP_XF_S * SR)
    pieces = [seg]
    total = len(seg)
    while total < n:
        pieces.append(seg[xf:])
        total += len(seg) - xf
    out = seg
    if len(pieces) > 1:  # equal-power loop joins, built once
        th = np.linspace(0, np.pi / 2, xf, dtype=np.float32)
        fade_out, fade_in = np.cos(th), np.sin(th)
        body = [seg[:-xf]]
        for _ in range(len(pieces) - 1):
            body.append(seg[-xf:] * fade_out + seg[:xf] * fade_in)
            body.append(seg[xf:-xf])
        body.append(seg[-xf:])
        out = np.concatenate(body)
    return out[:n]


def room_tone(x: np.ndarray, n: int) -> np.ndarray:
    """n samples of the take's quietest 0.25 s, looped with 30 ms crossfades, level-matched to -62...-68 dBFS."""
    return _loop(_tone_seed(x), n)


def retime(src: Path, dst: Path, plan: list[tuple[float, float, float]], cuts: list[float]) -> dict:
    """Rebuild src with each planned pause set to its target length (room tone inside, 40 ms equal-power
    joins) and write dst. Returns {"cuts": cut times mapped into the new timeline, "duration": seconds}."""
    x = read(src)
    seed = _tone_seed(x) if plan else None
    parts: list[np.ndarray] = []
    total = 0

    def join(b: np.ndarray, xf: int) -> None:
        """Append b, overlapping its head with the tail of what is built by an equal-power xf-sample fade."""
        nonlocal total
        while parts and xf > 0 and len(parts[-1]) < xf and len(parts) > 1:
            parts[-2:] = [np.concatenate(parts[-2:])]  # a tiny piece: fade across it into the one before
        xf = min(xf, len(b), len(parts[-1])) if parts else 0
        if xf > 0:
            th = np.linspace(0, np.pi / 2, xf, dtype=np.float32)
            mid = parts[-1][-xf:] * np.cos(th) + b[:xf] * np.sin(th)
            parts[-1] = parts[-1][:-xf]
            parts.extend([mid, b[xf:]])
        else:
            parts.append(b)
        total += len(b) - xf

    last, join_xf = 0, 0
    anchors = [(0.0, 0.0)]  # (old_t, new_t) at the middle of each pause
    for s, e, target in sorted(plan):
        a, b = int(s * SR), int(e * SR)
        keep = min(int(KEEP_S * SR), (b - a) // 2)
        xf = min(int(XF_S * SR), keep)
        join(x[last:a + keep], join_xf)
        new_start = total - keep
        fill = int(target * SR) - 2 * keep
        if fill > 0:
            join(_loop(seed, fill + 2 * xf), xf)
            new_len = 2 * keep + fill
        else:
            new_len = 2 * keep - xf
        anchors.append(((s + e) / 2, (new_start + new_len / 2) / SR))
        last, join_xf = b - keep, xf
    join(x[last:], join_xf)
    y = np.concatenate(parts) if parts else x[:0]
    write(dst, y)
    anchors.append((len(x) / SR, len(y) / SR))
    old, new = zip(*anchors)
    return {"cuts": [round(float(np.interp(c, old, new)), 3) for c in cuts],
            "duration": round(len(y) / SR, 3)}
