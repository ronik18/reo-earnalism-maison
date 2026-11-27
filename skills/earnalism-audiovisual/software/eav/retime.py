"""Pause re-timing: narration pauses are re-set by punctuation and filled with the take's own room tone.

TTS takes come with commas and sentence ends too short, and joins filled with digital silence. Here
`detect_pauses` finds the gaps (ffmpeg silencedetect), `plan_pauses` maps them in order to the
punctuation of the script text and picks a seeded target length, and `retime` rebuilds the take: each
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


def plan_pauses(text: str, pauses: list[tuple[float, float]], rng_seed: int) -> list[tuple[float, float, float]]:
    """(start, end, target_s) per detected pause: pauses map in order to the text's punctuation, each target
    is drawn from its kind's range and varied +-15 % (seeded). A pause with no punctuation keeps its length."""
    rng = random.Random(rng_seed)
    kinds = _kinds(text)
    plan = []
    for i, (s, e) in enumerate(pauses):
        if i < len(kinds):
            lo, hi = TARGETS[kinds[i]]
            target = rng.uniform(lo, hi) * rng.uniform(1 - JITTER, 1 + JITTER)
        else:
            target = e - s
        plan.append((s, e, round(target, 4)))
    return plan


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
