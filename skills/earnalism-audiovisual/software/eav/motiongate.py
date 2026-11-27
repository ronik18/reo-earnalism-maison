"""Per-clip motion gate for Wan video takes (spec section 3, "Motion gate per clip").

`check_clip(mp4)` decodes the clip to small grey frames with ffmpeg, takes the mean absolute difference
between consecutive frames and looks for two defects:

  * periodic near-duplicate frames (the frame-interpolation stutter signature): pairs whose difference is far
    below the clip's median, recurring at a regular spacing at least MIN_PERIODIC_RUNS times;
  * difference spikes: a single pair far above the median, not sustained (a run of high pairs is fast motion
    or a cut, not a glitch).

It returns {"near_duplicate_runs", "diff_spikes", "contact_sheet", "pass", "needs_review", ...}. `pass` is
False only for a clear defect; a borderline reading sets needs_review with pass True, so the assembler
(`film --shots`) never refuses it. A clip that cannot be decoded is needs_review, never a pass without a
look. The contact sheet tiles every 4th frame into one PNG next to the clip (spec: hands-and-eyes review).

`gate_clip(mp4)` also writes `<key>.motion.json` (verdict, thresholds, measured values) beside the clip so
the thresholds can be calibrated later. A gated clip is never modified: only new sibling files are written.
"""
import json
import math
import subprocess
from pathlib import Path

import numpy as np

# ALL UNCALIBRATED: first-guess values from the 27 Nov ruling, to be tuned on real Wan takes from the
# measured values kept in <key>.motion.json. The assembler only refuses a clear fail (pass False).
THRESHOLDS = {
    "frame_w": 160,             # decode size (grey); the height is 90, aspect is irrelevant to a difference
    "frame_h": 90,
    "sheet_every": 4,           # contact sheet: every 4th frame
    "sheet_cols": 8,
    "min_frames": 8,            # fewer decoded frames than this cannot be judged: needs_review
    "min_median": 0.1,          # median difference (0-255 scale) below this: nearly static (needs_review; still measured)
    "dup_rel": 0.2,             # a pair is a near-duplicate when its difference < dup_rel * median
    "min_periodic_runs": 3,     # stutter: at least this many duplicate runs ...
    "period_tolerance": 1,      # ... whose spacing varies by at most this many frames
    "spike_rel": 6.0,           # a pair is a clear spike above spike_rel * median ...
    "spike_abs": 3.0,           # ... and above this absolute difference (real Wan takes: median 0.08-1.2, peak <= 8.8)
    "review_spike_rel": 4.0,    # borderline spike (needs_review) above this * median (and review_spike_abs)
    "review_spike_abs": 1.5,    # ... and above this absolute difference
    "sustained_pairs": 3,       # three or more adjacent high pairs are sustained motion, not a glitch
}


def _frames(mp4: Path, t: dict) -> np.ndarray:
    w, h = t["frame_w"], t["frame_h"]
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-vf", f"scale={w}:{h}", "-pix_fmt", "gray",
                        "-f", "rawvideo", "-"], capture_output=True)
    if p.returncode != 0:
        raise ValueError((p.stderr or b"ffmpeg failed").decode("utf-8", "replace").strip()[:300])
    n = len(p.stdout) // (w * h)
    return np.frombuffer(p.stdout, dtype=np.uint8)[: n * w * h].reshape(n, h, w)


def _runs(idx: list) -> list:
    """[(start, length)] of consecutive indices."""
    out = []
    for i in idx:
        if out and i == out[-1][0] + out[-1][1]:
            out[-1][1] += 1
        else:
            out.append([i, 1])
    return [tuple(r) for r in out]


def _periodic(starts: list, tol: int, need: int) -> list:
    """The longest stretch of consecutive run starts whose gaps differ by at most tol; [] if shorter than need."""
    best = []
    for i in range(len(starts)):
        cur = [starts[i]]
        lo = hi = None
        for s in starts[i + 1:]:
            gap = s - cur[-1]
            nlo, nhi = (gap, gap) if lo is None else (min(lo, gap), max(hi, gap))
            if nhi - nlo > tol:
                break
            lo, hi = nlo, nhi
            cur.append(s)
        if len(cur) > len(best):
            best = cur
    return best if len(best) >= need else []


def _sheet(mp4: Path, out: Path, n_frames: int, t: dict) -> None:
    every, cols, w = t["sheet_every"], t["sheet_cols"], t["frame_w"]
    rows = max(1, math.ceil(math.ceil(n_frames / every) / cols))
    vf = f"select='not(mod(n\\,{every}))',scale={w}:-2,tile={cols}x{rows}:padding=2:margin=2"
    p = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(mp4), "-vf", vf, "-vsync", "0", "-frames:v", "1",
                        str(out)], capture_output=True)
    if p.returncode != 0 or not out.is_file():
        raise ValueError((p.stderr or b"contact sheet failed").decode("utf-8", "replace").strip()[:300])


def check_clip(mp4, sheet=True, thresholds: dict = None) -> dict:
    """Gate one clip. `sheet` True writes <stem>.contact.png beside it (a path writes there; False/None skips)."""
    mp4 = Path(mp4)
    t = {**THRESHOLDS, **(thresholds or {})}
    res = {"near_duplicate_runs": [], "diff_spikes": [], "contact_sheet": None, "pass": True,
           "needs_review": False, "notes": [], "frames": 0, "measured": {}}
    try:
        fr = _frames(mp4, t)
    except (ValueError, OSError) as e:
        res.update({"needs_review": True, "notes": [f"clip could not be decoded: {e}"]})
        return res
    res["frames"] = int(len(fr))
    if len(fr) < t["min_frames"]:
        res.update({"needs_review": True, "notes": [f"only {len(fr)} frames: too short to judge"]})
        return res
    if sheet:
        out = Path(sheet) if not isinstance(sheet, bool) else mp4.with_name(mp4.stem + ".contact.png")
        try:
            _sheet(mp4, out, len(fr), t)
            res["contact_sheet"] = str(out)
        except (ValueError, OSError) as e:
            res["notes"].append(f"contact sheet failed: {e}")
            res["needs_review"] = True
    f = fr.astype(np.float32)
    d = np.abs(f[1:] - f[:-1]).mean(axis=(1, 2))
    med = float(np.median(d))
    res["measured"] = {"median_diff": round(med, 4), "max_diff": round(float(d.max()), 4),
                       "min_diff": round(float(d.min()), 4), "pairs": int(len(d))}
    static = med < t["min_median"]
    if static:
        res["needs_review"] = True
        res["notes"].append(f"nearly static (median difference {med:.3f}); detectors still run")
    base = max(med, t["min_median"])  # ratios never divide by a tiny median
    res["measured"]["ratio_base"] = round(base, 4)
    dup = [int(i) for i in np.nonzero(d < t["dup_rel"] * base)[0]]
    runs = _runs(dup)
    res["near_duplicate_runs"] = [{"start": s, "length": n} for s, n in runs]
    periodic = _periodic([s for s, _ in runs], t["period_tolerance"], t["min_periodic_runs"])
    res["measured"]["periodic_starts"] = periodic
    if periodic:
        res["pass"] = False
        res["notes"].append(f"periodic near-duplicate frames: {len(periodic)} runs, spacing "
                            f"{min(b - a for a, b in zip(periodic, periodic[1:]))}-"
                            f"{max(b - a for a, b in zip(periodic, periodic[1:]))} frames (stutter)")
    elif len(runs) >= t["min_periodic_runs"]:
        res["needs_review"] = True
        res["notes"].append(f"{len(runs)} near-duplicate runs without a regular spacing")
    high = [int(i) for i in np.nonzero((d > t["review_spike_rel"] * base) & (d > t["review_spike_abs"]))[0]]
    for s, n in _runs(high):
        if n >= t["sustained_pairs"]:
            continue  # sustained: fast motion, not a glitch
        peak = float(d[s:s + n].max())
        clear = peak > t["spike_rel"] * base and peak > t["spike_abs"]
        res["diff_spikes"].append({"index": s, "length": n, "diff": round(peak, 3),
                                   "ratio": round(peak / base, 2), "clear": clear})
        if clear:
            res["pass"] = False
            res["notes"].append(f"difference spike at frame {s + 1}: {peak:.1f} = {peak / base:.1f}x the median")
        else:
            res["needs_review"] = True
            res["notes"].append(f"borderline difference spike at frame {s + 1}: {peak / base:.1f}x the median")
    res["measured"]["peak_diff"] = round(float(d.max()), 4)
    if not res["pass"]:
        res["needs_review"] = False  # a clear fail is not advisory
    return res


def gate_clip(mp4, out_dir=None) -> dict:
    """check_clip plus <key>.motion.json (and the contact sheet) in out_dir (default: beside the clip)."""
    mp4 = Path(mp4)
    out_dir = Path(out_dir) if out_dir else mp4.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    res = check_clip(mp4, sheet=out_dir / (mp4.stem + ".contact.png"))
    if res["contact_sheet"]:
        res["contact_sheet"] = Path(res["contact_sheet"]).name
    res["clip"] = mp4.name
    res["thresholds"] = dict(THRESHOLDS)
    res["thresholds_calibrated"] = False
    (out_dir / (mp4.stem + ".motion.json")).write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n",
                                                       encoding="utf-8")
    return res
