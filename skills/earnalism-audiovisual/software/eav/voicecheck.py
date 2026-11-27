"""Narration redo gate: flags robotic, monotone or flawed TTS takes so only the failures are regenerated.

`profile(takes)` takes the book's running medians (pitch, rate, brightness, spectral-jump rate, click
rate); `check(take, expected_s, prof, prev_tail)` measures one take and returns
{"pass", "failures", "metrics"}. A profile-relative check is skipped when `prof` lacks its key (the
first take of a book). numpy only; the pitch tracker is the YIN tracker of the 26 Nov voice review.

Approximations, stated: pitch spread is the 10th-90th percentile range of voiced frames in semitones
about the take's median; monotone windows are non-overlapping 2 s windows with >= 60 voiced frames;
`join` compares RMS-based loudness of the speech frames (a LU approximation, not BS.1770 gating) and
median pitch of the last ~2 s of `prev_tail` against the first ~2 s of the take; true peak is the
maximum of a 4x FFT-oversampled signal; the jump-rate profile has a floor of JUMP_FLOOR per speech
second so a jump-free profile does not fail every later take.
"""
import json
from pathlib import Path

import numpy as np

from .retime import SR, detect_pauses, read

HOP = 0.010
WIN = 0.025
NFFT = 2048
MIN_VOICED_WIN = 60          # voiced 10 ms frames needed in a 2 s window to judge it
LIMITS = {"duration_pct": 0.12, "pitch_median_st": 1.5, "pitch_spread_st": 3.0, "monotone_st": 1.5,
          "monotone_frac": 0.20, "max_run_s": 9.0, "pause_s": 0.15, "tail_db": -50.0, "brightness_db": 2.0,
          "jump_ratio": 1.5, "clicks_per_s": 0.2, "zero_run_s": 0.05, "join_lu": 1.5, "join_st": 1.5,
          "true_peak_db": -0.1}
JUMP_FLOOR = 0.1
CODES = ("duration", "pitch_median", "pitch_spread", "monotone", "no_breath", "tail", "brightness", "jumps",
         "clicks", "digital_zero", "join", "true_peak")


def _frames(x: np.ndarray, win: int, hop: int) -> np.ndarray:
    n = 1 + max(0, (len(x) - win) // hop)
    return x[np.arange(win)[None, :] + hop * np.arange(n)[:, None]]


def yin(x: np.ndarray, sr: int = SR, fmin=65, fmax=400, hop=HOP, win=0.040, thr=0.15):
    """Per-10 ms (f0 Hz or nan, confidence). Works at sr/3 for speed."""
    k = sr // 16000
    x16 = x[:len(x) // k * k].reshape(-1, k).mean(1)
    s = sr // k
    W, H = int(win * s), int(hop * s)
    tmax, tmin = int(s / fmin), int(s / fmax)
    F = _frames(x16, W + tmax + 2, H) if len(x16) >= W + tmax + 2 else np.zeros((0, W + tmax + 2))
    f0 = np.full(len(F), np.nan)
    conf = np.zeros(len(F))
    N = 1 << int(np.ceil(np.log2(2 * F.shape[1])))
    for i, fr in enumerate(F):
        a = fr[:W]
        if np.sqrt(np.mean(a ** 2)) < 1e-3:
            continue
        cs = np.cumsum(np.concatenate([[0], fr ** 2]))
        cc = np.fft.irfft(np.conj(np.fft.rfft(a, N)) * np.fft.rfft(fr, N), N)[:tmax + 1]
        d = np.sum(a ** 2) + cs[np.arange(tmax + 1) + W] - cs[np.arange(tmax + 1)] - 2 * cc
        d[0] = 0
        cm = np.ones_like(d)
        cm[1:] = d[1:] * np.arange(1, tmax + 1) / np.maximum(np.cumsum(d[1:]), 1e-12)
        cand = np.where(cm[tmin:] < thr)[0]
        if len(cand) == 0:
            continue
        t = cand[0] + tmin
        while t + 1 <= tmax and cm[t + 1] < cm[t]:
            t += 1
        off = 0.0
        if 1 <= t < tmax:
            den = cm[t - 1] - 2 * cm[t] + cm[t + 1]
            off = 0.5 * (cm[t - 1] - cm[t + 1]) / den if den != 0 else 0.0
        f0[i] = s / (t + off)
        conf[i] = 1 - cm[t]
    return f0, conf


def _runs(m: np.ndarray) -> list[tuple[int, int]]:
    d = np.diff(np.concatenate([[0], m.astype(np.int8), [0]]))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def _spectral(x: np.ndarray):
    """Per 10 ms frame: rms dB, 4-8 kHz/0.1-4 kHz energy ratio (dB), 0.3-2.5 kHz envelope (dB), spectral
    flux (log spectrum). Chunked so a chapter-length take stays small."""
    win, hop = int(WIN * SR), int(HOP * SR)
    n = 1 + max(0, (len(x) - win) // hop)
    hann = np.hanning(win)
    fr = np.fft.rfftfreq(NFFT, 1 / SR)
    lo_m, hf_m, bd_m = (fr > 100) & (fr < 4000), (fr > 4000) & (fr < 8000), (fr > 300) & (fr < 2500)
    rms, ratio, band, flux = (np.zeros(n) for _ in range(4))
    prev = None
    for a in range(0, n, 1500):
        b = min(n, a + 1500)
        F = _frames(x[a * hop:(b - 1) * hop + win], win, hop) * hann
        sp = np.abs(np.fft.rfft(F, NFFT)) + 1e-10
        rms[a:b] = 10 * np.log10(np.mean(F ** 2, 1) + 1e-12)
        ratio[a:b] = 10 * np.log10((np.sum(sp[:, hf_m] ** 2, 1) + 1e-12) / (np.sum(sp[:, lo_m] ** 2, 1) + 1e-12))
        band[a:b] = 10 * np.log10(np.sum(sp[:, bd_m] ** 2, 1))
        ls = np.log(sp).astype(np.float32)
        ext = ls if prev is None else np.vstack([prev, ls])
        d = np.sqrt(np.mean(np.diff(ext, axis=0) ** 2, 1))
        flux[a + (1 if prev is None else 0):b] = d
        prev = ls[-1:]
    return rms, ratio, band, flux


def _speech_mask(rms: np.ndarray) -> np.ndarray:
    m = rms > np.percentile(rms, 95) - 35
    for a, b in _runs(~m):
        if b - a < 8 and a > 0:
            m[a:b] = True
    for a, b in _runs(m):
        if b - a < 5:
            m[a:b] = False
    return m


def _true_peak_db(x: np.ndarray) -> float:
    if len(x) == 0:
        return -120.0
    up = np.fft.irfft(np.fft.rfft(x), 4 * len(x)) * 4
    return float(20 * np.log10(max(float(np.max(np.abs(up))), 1e-12)))


def _zero_run_s(x: np.ndarray) -> float:
    z = np.concatenate([[0], (np.abs(x) < 1e-9).astype(np.int8), [0]])
    d = np.diff(z)
    s, e = np.where(d == 1)[0], np.where(d == -1)[0]
    return float(np.max(e - s)) / SR if len(s) else 0.0


def _clicks(x: np.ndarray) -> int:
    if len(x) < 400:
        return 0
    hpd = np.diff(x.astype(np.float64), 2)
    lr = np.sqrt(np.convolve(hpd ** 2, np.ones(320) / 320, "same")) + 1e-6
    idx = np.where(np.abs(hpd) / lr > 9)[0]
    n, last = 0, -10 ** 9
    for c in idx:
        if c - last > 0.02 * SR:
            n += 1
        last = c
    return n


def _pitch(x: np.ndarray):
    """(st vs median, voiced mask, median Hz); octave errors beyond 10 st dropped."""
    f0, _ = yin(x)
    ok = ~np.isnan(f0)
    if not ok.any():
        return np.full(len(f0), np.nan), ok, None
    med = float(np.median(f0[ok]))
    st = 12 * np.log2(f0 / med)
    st[np.abs(st) > 10] = np.nan
    return st, ~np.isnan(st), med


def measure(path: Path) -> dict:
    """All per-take measurements the gate and profile use."""
    x = read(path)
    dur = len(x) / SR
    if len(x) < int(0.2 * SR):
        return {"duration_s": dur, "empty": True, "true_peak_dbfs": _true_peak_db(x),
                "zero_run_s": _zero_run_s(x), "tail_dbfs": -120.0}
    rms, ratio, band, flux = _spectral(x)
    m = _speech_mask(rms)
    n = len(rms)
    st, voiced, med = _pitch(x)
    k = min(n, len(st))
    vm = voiced[:k] & m[:k]
    sv = st[:k][vm]
    spread = float(np.percentile(sv, 90) - np.percentile(sv, 10)) if len(sv) >= 5 else 0.0
    wins = []
    for a in range(0, k - 199, 200):
        seg = st[a:a + 200]
        seg = seg[~np.isnan(seg)]
        if len(seg) >= MIN_VOICED_WIN:
            wins.append(float(np.percentile(seg, 90) - np.percentile(seg, 10)))
    mono_frac = float(np.mean([w < LIMITS["monotone_st"] for w in wins])) if wins else 0.0
    sruns = _runs(m)
    t0, t1 = (sruns[0][0] * HOP, sruns[-1][1] * HOP) if sruns else (0.0, dur)
    speech_s = max(float(m.sum()) * HOP, 1e-3)
    # run without a pause: speech start/end and every pause of >= 0.15 s (ffmpeg silencedetect)
    pauses = [(a, b) for a, b in detect_pauses(path, -38, LIMITS["pause_s"]) if t0 < a and b < t1]
    edges = [t0] + [v for p in pauses for v in p] + [t1]
    max_run = max(edges[i + 1] - edges[i] for i in range(0, len(edges), 2))
    # syllable nuclei: peaks of the smoothed 0.3-2.5 kHz envelope inside speech
    kern = np.hanning(7) / np.hanning(7).sum()
    bes = np.convolve(band, kern, "same")
    ref = np.percentile(rms, 95)
    nuclei, last = 0, -100
    for i in range(2, n - 2):
        if m[i] and bes[i] >= bes[i - 1] and bes[i] > bes[i + 1] and bes[i] > ref - 25:
            if bes[i] - bes[max(0, i - 12):i].min() >= 2 and bes[i] - bes[i + 1:i + 13].min() >= 2 and i - last >= 9:
                nuclei, last = nuclei + 1, i
    # spectral jumps: flux outliers inside speech with no level change (not an onset)
    fm = flux[m]
    med_f = np.median(fm) if len(fm) else 0.0
    mad = max(1.4826 * (np.median(np.abs(fm - med_f)) if len(fm) else 0.0), 0.1)
    z = (flux - med_f) / mad
    jumps = sum(1 for i in range(2, n - 2) if m[i - 2] and m[i + 2] and z[i] > 6 and abs(rms[i] - rms[i - 1]) < 4)
    return {
        "duration_s": dur, "speech_s": speech_s, "empty": False,
        "pitch_median_hz": med, "pitch_spread_st": spread, "monotone_frac": mono_frac, "monotone_windows": len(wins),
        "max_run_s": max_run, "rate": nuclei / speech_s,
        "tail_dbfs": float(20 * np.log10(max(float(np.sqrt(np.mean(x[-int(0.05 * SR):] ** 2))), 1e-12))),
        "brightness_db": float(np.median(ratio[m])) if m.any() else None,
        "jump_rate": jumps / speech_s, "click_rate": _clicks(x) / speech_s,
        "zero_run_s": _zero_run_s(x), "true_peak_dbfs": _true_peak_db(x),
    }


def profile(takes: list[Path]) -> dict:
    """The book's running medians over the takes (keys with no measurable value are left out)."""
    ms = [measure(Path(t)) for t in takes]
    prof = {}
    for key in ("pitch_median_hz", "rate", "brightness_db", "jump_rate", "click_rate"):
        v = [m[key] for m in ms if m.get(key) is not None]
        if v:
            prof[key] = float(np.median(v))
    return prof


def _edge(path: Path, tail: bool):
    """(loudness dB of speech frames, median Hz or None) of the last/first ~2 s of speech of a take."""
    x = read(path)
    rms, *_ = _spectral(x) if len(x) >= int(WIN * SR) else (np.zeros(0),)
    m = _speech_mask(rms) if len(rms) else np.zeros(0, bool)
    runs = _runs(m)
    if not runs:
        return None, None
    a, b = runs[0][0] * int(HOP * SR), runs[-1][1] * int(HOP * SR)
    seg = x[max(a, b - 2 * SR):b] if tail else x[a:a + 2 * SR]
    r, *_ = _spectral(seg) if len(seg) >= int(WIN * SR) else (np.zeros(0),)
    sm = r > np.percentile(r, 95) - 35 if len(r) else np.zeros(0, bool)
    loud = float(10 * np.log10(np.mean(10 ** (r[sm] / 10)))) if sm.any() else None
    _, _, med = _pitch(seg)
    return loud, med


def check(take: Path, expected_s: float, prof: dict, prev_tail: Path | None = None) -> dict:
    """Measure one take and list failure codes; pass is True when none fail."""
    take = Path(take)
    m = measure(take)
    fails: list[str] = []
    L = LIMITS
    if abs(m["duration_s"] - expected_s) > L["duration_pct"] * expected_s:
        fails.append("duration")
    if not m.get("empty"):
        if "pitch_median_hz" in prof and abs(12 * np.log2(m["pitch_median_hz"] / prof["pitch_median_hz"])) > L["pitch_median_st"]:
            fails.append("pitch_median")
        if m["pitch_spread_st"] < L["pitch_spread_st"]:
            fails.append("pitch_spread")
        if m["monotone_frac"] > L["monotone_frac"]:
            fails.append("monotone")
        if m["max_run_s"] > L["max_run_s"]:
            fails.append("no_breath")
    if m["tail_dbfs"] > L["tail_db"]:
        fails.append("tail")
    if not m.get("empty"):
        if "brightness_db" in prof and m["brightness_db"] is not None and abs(m["brightness_db"] - prof["brightness_db"]) > L["brightness_db"]:
            fails.append("brightness")
        if "jump_rate" in prof and m["jump_rate"] > L["jump_ratio"] * max(prof["jump_rate"], JUMP_FLOOR):
            fails.append("jumps")
        if m["click_rate"] > L["clicks_per_s"]:
            fails.append("clicks")
    if m["zero_run_s"] > L["zero_run_s"]:
        fails.append("digital_zero")
    if prev_tail is not None and not m.get("empty"):
        pl, pp = _edge(Path(prev_tail), tail=True)
        tl, tp = _edge(take, tail=False)
        join = {}
        if pl is not None and tl is not None:
            join["lu_diff"] = tl - pl
        if pp and tp:
            join["st_diff"] = float(12 * np.log2(tp / pp))
        m["join"] = join
        if abs(join.get("lu_diff", 0)) > L["join_lu"] or abs(join.get("st_diff", 0)) > L["join_st"]:
            fails.append("join")
    if m["true_peak_dbfs"] >= L["true_peak_db"]:
        fails.append("true_peak")
    fails.sort(key=CODES.index)
    return {"pass": not fails, "failures": fails, "metrics": json.loads(json.dumps(m, default=float))}
