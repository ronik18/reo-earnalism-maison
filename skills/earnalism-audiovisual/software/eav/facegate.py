"""Face and eye anomaly gate for Wan clips and stills (owner request 28 Nov 2026: "review these minute anomalies
very cautiously"). Scene 14 v7 shot 11 (take f01s014-9p) showed the veiled mother with two pupils in one eye and
nothing caught it; earlier misses were a mole that came and went, a face that changed age between shots and a cyan
LED-like glow in the background.

Method: classical OpenCV on the flat 2-D house style, no model and no download (MediaPipe needs a downloaded
.task model and is built for photographs; DINOv2 needs torch, which this container does not have). Per frame (every
`step`-th frame of a clip) or per still:

  * eye candidates: bright, low-saturation "sclera" components that stand out from their surroundings, ringed by
    dark outline, with skin around them (an eye on a face);
  * pupils: thick, round, near-black discs (distance-transform maxima) whose centre lies inside the sclera hull and
    that sclera surrounds on part of their edge; a specular highlight inside a pupil is filled first;
  * double pupil: two such discs in one eye, of comparable size, apart, with sclera between them (an extra eyeball);
  * missing pupil: an open eye of a convincing pair (the other eye has a clear pupil) with no dark iris mass at all;
  * asymmetry: the two eyes of a convincing pair differ strongly in sclera area or pupil size;
  * eye off the face (clips only, persistent): an eye with a pupil, almost no skin round it, outside the face of a
    detected eye pair;
  * morphing: a tracked eye with a pupil whose sclera area jumps between consecutive samples (blinks excluded);
  * glow: a small, compact cyan light brighter than a darker surround, away from the eyes (an LED-like light; the
    house palette is warm).

A clip's double or missing pupil is a clear fail when it persists over several sampled frames at one place, else
needs_review; on a still a double pupil is a fail and a missing pupil needs review. Identity and age drift against the
character anchors is NOT measured here (no DINOv2 without torch): the face close-up sheet is where a reviewer checks
it, with moles, marks, jewellery and costume.

`gate(path, out_dir)` writes `<key>.face.json` (per-frame measurements, thresholds marked uncalibrated, findings and
verdict) and `<key>.faces.png` (face crops enlarged about 3x, flagged frames boxed in red). Sources are never
modified. Every threshold is UNCALIBRATED beyond the scene 14 evidence recorded in CALIBRATION.
"""
import hashlib
import json
import math
import subprocess
from pathlib import Path

import numpy as np

try:  # fail closed: without OpenCV the gate cannot run, and the caller records it as not run
    import cv2
except ImportError:  # pragma: no cover - the container ships opencv-python-headless
    cv2 = None

VERSION = 1
METHOD = ("classical OpenCV (sclera/pupil geometry on flat 2-D art), no model, no download; OpenCV is Apache-2.0 "
          "(references/model-licences.md)")
IDENTITY = ("not measured: the DINOv2 anchor similarity needs torch, which this container lacks; identity, age, "
            "moles and marks are judged on the face close-up sheet")
CALIBRATION = ("28 Nov 2026, scene 14 v7: take f01s014-9p (the veiled mother, two pupils in her left eye) fails in "
               "53 of 61 sampled frames (0-106, the owner's 0:51 is about frame 55); its start still "
               "pilot/v6/art/f01s014-9.png has the same double pupil (FLUX drew it, Wan kept it) and fails too; takes "
               "12a, 13s, 13t, 14x and the scene's other picked stills raise nothing; the pale cyan LED of the original "
               "take 12a and of anchor-hem.png is a glow. False-positive sweep over 406 other stills and pilot takes of "
               "both titles (r9 candidates, pilot clips): see references/film-recipe.md. Uncalibrated beyond that.")

THRESHOLDS = {
    "step": 2,                    # clip: every 2nd frame
    "sclera_max_sat": 70,         # HSV (OpenCV 0-255) saturation of eye whites
    "sclera_min_v": 110,          # ... their brightness
    "sclera_local_contrast": 18,  # ... and how much brighter than the local mean ...
    "local_win_frac": 0.03,       # ... over a window this fraction of the frame diagonal (or the large one)
    "local_win_frac_large": 0.10,
    "eye_min_area": 60,           # sclera pixels: smaller eyes (crowd faces) are not judged
    "eye_max_frac": 0.02,         # sclera area at most this fraction of the frame (larger: a wall, a sheet)
    "eye_min_aspect": 0.2,        # sclera box width / height
    "eye_max_aspect": 5.0,
    "ring_dark_min": 0.35,        # the band just outside the sclera hull is at least this dark (eye outline)
    "dark_rel": 0.5,              # "dark" = below this fraction of the sclera's median brightness
    "skin_hue_lo": 5,             # skin: warm brown hues (OpenCV 0-180) ...
    "skin_hue_hi": 22,
    "skin_min_sat": 90,           # ... of moderate saturation (a red border or blouse is more saturated)
    "skin_max_sat": 215,
    "skin_min": 0.6,              # skin fraction round an eye that counts as on a face
    "off_face_skin_max": 0.3,     # an eye with a pupil, less skin than this round it and outside the face of a
    "off_face_ring_dark": 0.5,    # detected eye pair (a full dark outline): eye off the face
    "pupil_min_r_px": 3.0,        # pupil radius at least this (px) ...
    "pupil_min_r_rel": 0.11,      # ... and this fraction of the sclera box's short side
    "pupil_min_cov": 0.3,         # sclera on at least this fraction of the directions round the pupil
    "pupil_core_max": 0.25,       # pupil core median brightness / sclera brightness (near-black)
    "pupil_elong_max": 2.1,       # pupil disc elongation (a stroke or fold is longer)
    "double_min_r_ratio": 0.5,    # the second pupil is at least half the radius of the first
    "double_min_sep": 1.15,       # centres apart by at least this x (r1 + r2)
    "double_between_sclera": 0.3, # sclera on at least this fraction of the gap between them
    "double_persist": 3,          # clip: a double pupil at one place in >= this many sampled frames fails
    "missing_persist": 4,         # clip: a missing pupil at one place in >= this many sampled frames fails
    "missing_min_side": 18,       # missing pupil is judged only on eyes at least this many px on their short side
    "missing_dark_rel": 0.8,      # missing: no dark mass thicker than this x the minimum pupil radius in the eye
    "open_min_ratio": 0.35,       # an eye is open when its sclera hull is at least this tall for its width
    "pair_min_sep": 1.0,          # two eyes are a pair: centres 1-5 eye widths apart ...
    "pair_max_sep": 5.0,
    "pair_max_dy": 1.2,           # ... at most this many eye heights apart vertically
    "pair_max_area_ratio": 10.0,   # ... and their whites differ at most this much in area
    "strict_ring_dark": 0.5,      # a pair judged for missing pupils and asymmetry: mutual nearest, both outlined,
    "strict_max_dy": 0.8,         # level within this many eye heights, and one eye with a clear pupil:
    "strict_pupil_cov": 0.5,      # sclera on half its edge ...
    "strict_pupil_core": 0.15,    # ... and a near-black core
    "asym_area_ratio": 8.0,       # pair sclera areas differ more than this: needs_review (a 3/4 view's far eye,
                                  # its white split by the iris, measures up to ~6.3x smaller: scene 14 still 6)
    "asym_pupil_ratio": 2.5,      # pair pupil radii differ more than this: needs_review
    "morph_area_ratio": 2.2,      # a tracked eye's sclera area changes more than this between two samples
    "glow_hue_lo": 81,            # cyan (OpenCV hue 0-180): the scene 14 LEDs measure 84-88; an emerald jewel is ~79,
    "glow_hue_hi": 92,            # sky through a window 93-98, moonlight blue ~105
    "glow_min_sat": 40,           # a pale LED glow (anchor-hem: hue 85, saturation 50-70, brightness 230-250)
    "glow_min_v": 200,
    "glow_min_area": 40,          # px (a tear or a catchlight is smaller)
    "glow_min_solidity": 0.8,     # a lamp-like compact shape (sky, water and spray are ragged)
    "glow_surround_rel": 0.6,     # the surround is at most this bright relative to the light
    "glow_max_frac": 0.003,       # a glow is small: at most this fraction of the frame
    "glow_persist": 3,            # clip: in >= this many sampled frames to be listed
    "off_face_persist": 3,        # clip: an eye off the face in >= this many sampled frames is listed (stills:
                                  # never; crowds and other people's eyes made it noise on the r9 stills)
    "sheet_every": 4,             # close-up sheet: every 4th frame of a clip, plus every flagged frame
    "sheet_scale": 3.0,           # face crops enlarged this much ...
    "sheet_tile": 300,            # ... and fitted into tiles this many px square
    "sheet_cols": 6,
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
CLIP_EXTS = {".mp4", ".mov", ".webm", ".mkv"}


class Unavailable(RuntimeError):
    """The gate cannot run here (OpenCV missing, media unreadable)."""


def available() -> bool:
    return cv2 is not None


def _require():
    if cv2 is None:
        raise Unavailable("OpenCV (opencv-python-headless) is not importable: the face gate cannot run")


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------------------------------------------ per image
def _fill_small_holes(mask, max_area):
    """Fill enclosed holes up to max_area (a pupil's specular highlight)."""
    inv = (1 - mask).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    out = mask.copy()
    h, w = mask.shape
    for i in range(1, n):
        x, y, ww, hh, a = st[i]
        if a <= max_area and x > 0 and y > 0 and x + ww < w and y + hh < h:
            out[lab == i] = 1
    return out


_ANGLES = np.linspace(0, 2 * np.pi, 48, endpoint=False)


def _pupils(M, hull, Vc, dark, sv, size, ww, hh, t):
    """Round near-black discs inside the eye: [{x, y, r, cov, core, elong}] in crop coordinates."""
    ha = max(1, int(cv2.contourArea(hull)))
    df = _fill_small_holes(dark, max(6, 0.08 * ha))
    dt = cv2.distanceTransform(df, cv2.DIST_L2, 5)
    rmin = max(t["pupil_min_r_px"], t["pupil_min_r_rel"] * min(ww, hh))
    peaks = (dt == cv2.dilate(dt, np.ones((3, 3), np.uint8))) & (dt >= rmin)
    ys, xs = np.nonzero(peaks)
    cands = sorted(((float(dt[y, x]), int(x), int(y)) for y, x in zip(ys, xs)), reverse=True)
    out = []
    H, W = M.shape
    for r, x, y in cands:
        if cv2.pointPolygonTest(hull, (float(x), float(y)), True) < -0.05 * size:
            continue
        if any(math.hypot(x - p["x"], y - p["y"]) < (r + p["r"]) * 0.85 for p in out):
            continue
        hits = 0
        for a in _ANGLES:
            for d in (r + 1.5, r + 3, r + 3 + 0.3 * r):
                px, py = int(round(x + d * math.cos(a))), int(round(y + d * math.sin(a)))
                if 0 <= py < H and 0 <= px < W and M[py, px]:
                    hits += 1
                    break
        cov = hits / len(_ANGLES)
        if cov < t["pupil_min_cov"]:
            continue
        R = int(math.ceil(2 * r))
        y0, x0 = max(0, y - R), max(0, x - R)
        win = df[y0:y + R + 1, x0:x + R + 1]
        disk = np.zeros_like(win)
        cv2.circle(disk, (x - x0, y - y0), R, 1, -1)
        _, lab = cv2.connectedComponents((win & disk).astype(np.uint8), connectivity=8)
        comp = (lab == lab[y - y0, x - x0]).astype(np.uint8)
        m = cv2.moments(comp, True)
        elong = 99.0
        if m["m00"] > 0:
            a20, a02, a11 = m["mu20"] / m["m00"], m["mu02"] / m["m00"], m["mu11"] / m["m00"]
            s = math.sqrt(((a20 - a02) / 2) ** 2 + a11 ** 2)
            l1, l2 = (a20 + a02) / 2 + s, (a20 + a02) / 2 - s
            elong = math.sqrt(l1 / max(l2, 1e-6))
        cd = np.zeros_like(Vc, np.uint8)
        cv2.circle(cd, (x, y), max(1, int(0.6 * r)), 1, -1)
        core = float(np.median(Vc[cd > 0])) / max(sv, 1.0)
        if core > t["pupil_core_max"] or elong > t["pupil_elong_max"]:
            continue
        out.append({"x": x, "y": y, "r": round(r, 1), "cov": round(cov, 2), "core": round(core, 2),
                    "elong": round(elong, 2)})
    return out


def _doubles(M, pupils, t):
    """Pairs of pupils in one eye that are two eyeballs, not one: [(i, j, separation ratio, sclera between)]."""
    out = []
    ps = sorted(range(len(pupils)), key=lambda i: -pupils[i]["r"])
    for a_i, a in enumerate(ps):
        for b in ps[a_i + 1:]:
            A, B = pupils[a], pupils[b]
            if B["r"] < t["double_min_r_ratio"] * A["r"]:
                continue
            d = math.hypot(A["x"] - B["x"], A["y"] - B["y"])
            if d < t["double_min_sep"] * (A["r"] + B["r"]):
                continue
            hit = tot = 0
            for s in np.linspace(0, 1, 21):
                px, py = A["x"] + (B["x"] - A["x"]) * s, A["y"] + (B["y"] - A["y"]) * s
                if math.hypot(px - A["x"], py - A["y"]) < A["r"] or math.hypot(px - B["x"], py - B["y"]) < B["r"]:
                    continue
                tot += 1
                hit += int(M[int(round(py)), int(round(px))])
            if tot and hit / tot >= t["double_between_sclera"]:
                out.append((a, b, round(d / (A["r"] + B["r"]), 2), round(hit / tot, 2)))
    return out


def analyse_image(rgb, thresholds: dict = None) -> dict:
    """One frame or still (H x W x 3 RGB uint8): {"eyes": [...], "findings": [...], "glows": [...]}.
    Eye and pupil coordinates are in image pixels."""
    _require()
    t = {**THRESHOLDS, **(thresholds or {})}
    bgr = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    Hh, S, V = hsv[..., 0], hsv[..., 1].astype(np.int16), hsv[..., 2].astype(np.int16)
    h, w = V.shape
    lift = np.zeros(V.shape, bool)
    for frac in (t["local_win_frac"], t["local_win_frac_large"]):   # small eyes and close-up eyes alike
        win = int(math.hypot(h, w) * frac) | 1
        lift |= V - cv2.blur(V.astype(np.float32), (win, win)) > t["sclera_local_contrast"]
    sclera = ((S < t["sclera_max_sat"]) & (V > t["sclera_min_v"]) & lift).astype(np.uint8)
    skin_all = ((Hh >= t["skin_hue_lo"]) & (Hh <= t["skin_hue_hi"]) & (S >= t["skin_min_sat"])
                & (S <= t["skin_max_sat"]) & (V >= 50)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(sclera, connectivity=8)
    eyes = []
    for i in range(1, n):
        x, y, ww, hh, area = (int(v) for v in st[i])
        if area < t["eye_min_area"] or area > t["eye_max_frac"] * h * w:
            continue
        if not t["eye_min_aspect"] < ww / hh < t["eye_max_aspect"]:
            continue
        size = max(ww, hh)
        pad = max(3, int(0.35 * size))
        x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(w, x + ww + pad), min(h, y + hh + pad)
        M = (lab[y0:y1, x0:x1] == i).astype(np.uint8)
        cnts, _ = cv2.findContours(M, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        hull = cv2.convexHull(np.vstack(cnts))
        HM = np.zeros_like(M)
        cv2.fillConvexPoly(HM, hull, 1)
        Vc = V[y0:y1, x0:x1]
        sv = float(np.median(Vc[M > 0]))
        k = max(2, int(0.12 * size))
        ring = cv2.dilate(HM, np.ones((k, k), np.uint8)) - HM
        dark = (Vc < t["dark_rel"] * sv).astype(np.uint8)
        ring_dark = float(dark[ring > 0].mean()) if ring.any() else 0.0
        if ring_dark < t["ring_dark_min"]:
            continue
        k2 = max(3, int(0.5 * size))
        outer = cv2.dilate(HM, np.ones((k2, k2), np.uint8)) - cv2.dilate(HM, np.ones((k, k), np.uint8))
        skin = float(skin_all[y0:y1, x0:x1][outer > 0].mean()) if outer.any() else 0.0
        pupils = _pupils(M, hull, Vc, dark, sv, size, ww, hh, t)
        # the thickest dark mass anywhere in the eye opening: a pupil pressed into a corner still has one
        near = cv2.dilate(HM, np.ones((k, k), np.uint8))
        dt = cv2.distanceTransform(_fill_small_holes(dark, max(6, 0.08 * int(HM.sum()))), cv2.DIST_L2, 5)
        thick = float(dt[near > 0].max()) if near.any() else 0.0
        hx, hy, hw, hhh = cv2.boundingRect(hull)
        eye = {"box": [x, y, ww, hh], "sclera_area": area, "sclera_v": round(sv, 1), "ring_dark": round(ring_dark, 2),
               "skin": round(skin, 2), "open": round(hhh / max(hw, 1), 2),
               "dark_r": round(thick, 1), "pupil_r_min": round(max(t["pupil_min_r_px"], t["pupil_min_r_rel"] * min(ww, hh)), 1),
               "iris": bool(pupils) or thick >= max(t["pupil_min_r_px"], t["pupil_min_r_rel"] * min(ww, hh)),
               "pupils": [{**p, "x": p["x"] + x0, "y": p["y"] + y0} for p in pupils]}
        eye["_doubles"] = _doubles(M, pupils, t)
        eyes.append(eye)
    findings = []
    face_eyes = [e for e in eyes if e["skin"] >= t["skin_min"]]
    for e in face_eyes:
        for a, b, sep, between in e.pop("_doubles"):
            pa, pb = e["pupils"][a], e["pupils"][b]
            findings.append({"kind": "double_pupil", "box": e["box"],
                             "detail": f"two pupils in one eye: r {pa['r']} at ({pa['x']},{pa['y']}) and r {pb['r']} "
                                       f"at ({pb['x']},{pb['y']}), {sep}x apart, sclera between {between}"})
            break
    for e in eyes:
        e.pop("_doubles", None)
    # pairs: two face eyes side by side of comparable size
    pairs = []
    for i, a in enumerate(face_eyes):
        for b in face_eyes[i + 1:]:
            wa, wb = a["box"][2], b["box"][2]
            ca = (a["box"][0] + a["box"][2] / 2, a["box"][1] + a["box"][3] / 2)
            cb = (b["box"][0] + b["box"][2] / 2, b["box"][1] + b["box"][3] / 2)
            ew, eh = max(wa, wb), max(a["box"][3], b["box"][3])
            if not t["pair_min_sep"] * ew <= abs(ca[0] - cb[0]) <= t["pair_max_sep"] * ew:
                continue
            if abs(ca[1] - cb[1]) > t["pair_max_dy"] * eh:
                continue
            if max(a["sclera_area"], b["sclera_area"]) > t["pair_max_area_ratio"] * min(a["sclera_area"], b["sclera_area"]):
                continue
            if not (a["iris"] or b["iris"]):
                continue
            pairs.append((a, b))
    for a, b in _strict_pairs(pairs, t):   # missing pupils and asymmetry only on a convincing pair
        for e, other in ((a, b), (b, a)):
            if (not e["pupils"] and other["pupils"] and e["open"] >= t["open_min_ratio"]
                    and min(e["box"][2], e["box"][3]) >= t["missing_min_side"]
                    and e["dark_r"] < t["missing_dark_rel"] * e["pupil_r_min"]):
                findings.append({"kind": "missing_pupil", "box": e["box"],
                                 "detail": f"open eye ({e['open']} tall for its width) with no pupil and no thick dark "
                                           f"mass (radius {e['dark_r']} px); the other eye has {len(other['pupils'])}"})
        ar = max(a["sclera_area"], b["sclera_area"]) / max(1, min(a["sclera_area"], b["sclera_area"]))
        if ar > t["asym_area_ratio"]:
            findings.append({"kind": "asymmetry", "box": _union(a["box"], b["box"]),
                             "detail": f"eye whites differ {ar:.1f}x in area"})
        if a["pupils"] and b["pupils"]:
            ra, rb = max(p["r"] for p in a["pupils"]), max(p["r"] for p in b["pupils"])
            pr = max(ra, rb) / max(0.1, min(ra, rb))
            if pr > t["asym_pupil_ratio"]:
                findings.append({"kind": "asymmetry", "box": _union(a["box"], b["box"]),
                                 "detail": f"pupils differ {pr:.1f}x in radius"})
    faces = [_face_box(a["box"], b["box"]) for a, b in pairs]
    for e in eyes:
        if (faces and e["pupils"] and e["skin"] < t["off_face_skin_max"] and e["ring_dark"] >= t["off_face_ring_dark"]
                and e["sclera_area"] >= 2 * t["eye_min_area"]
                and not any(_inside(_centre(e["box"]), fb) for fb in faces)):
            findings.append({"kind": "eye_off_face", "box": e["box"],
                             "detail": f"an eye with a pupil outside the face of the eye pair, {e['skin']:.0%} skin "
                                       "round it"})
    glows = _glows(hsv, t, face_eyes)
    for g in glows:
        findings.append({"kind": "glow", "box": g["box"],
                         "detail": f"small cyan/blue-green light, {g['area']} px (hue {g['hue']}, LED-like?)"})
    return {"eyes": eyes, "pairs": [[eyes.index(a), eyes.index(b)] for a, b in pairs], "findings": findings,
            "glows": glows}


def _strict_pairs(pairs, t):
    """Pairs convincing enough to judge one eye against the other: mutual best partners (nearest), both outlined,
    level with each other, and at least one with a clear pupil (sclera all round it, near-black)."""
    def dist(a, b):
        (ax, ay), (bx, by) = _centre(a["box"]), _centre(b["box"])
        return math.hypot(ax - bx, ay - by)
    best = {}
    for a, b in pairs:
        for e, o in ((a, b), (b, a)):
            if id(e) not in best or dist(e, o) < dist(e, best[id(e)]):
                best[id(e)] = o
    out = []
    for a, b in pairs:
        if best.get(id(a)) is not b or best.get(id(b)) is not a:
            continue
        if min(a["ring_dark"], b["ring_dark"]) < t["strict_ring_dark"]:
            continue
        if abs(_centre(a["box"])[1] - _centre(b["box"])[1]) > t["strict_max_dy"] * max(a["box"][3], b["box"][3]):
            continue
        if not any(p["cov"] >= t["strict_pupil_cov"] and p["core"] <= t["strict_pupil_core"]
                   for e in (a, b) for p in e["pupils"]):
            continue
        out.append((a, b))
    return out


def _glows(hsv, t, eyes=()):
    """Small, compact, pale-to-saturated cyan lights that stand out of a darker surround (an LED between dark
    slats), away from every eye (catchlights and tears are not glows)."""
    h, w = hsv.shape[:2]
    V = hsv[..., 2].astype(np.float32)
    m = ((hsv[..., 0] >= t["glow_hue_lo"]) & (hsv[..., 0] <= t["glow_hue_hi"]) & (hsv[..., 1] >= t["glow_min_sat"])
         & (hsv[..., 2] >= t["glow_min_v"])).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, ww, hh, a = (int(v) for v in st[i])
        if not t["glow_min_area"] <= a <= t["glow_max_frac"] * h * w:
            continue
        if any(_inside((x + ww / 2, y + hh / 2), [e["box"][0] - e["box"][2], e["box"][1] - e["box"][3],
                                                  3 * e["box"][2], 3 * e["box"][3]]) for e in eyes):
            continue
        pad = max(4, int(0.6 * max(ww, hh)))
        x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(w, x + ww + pad), min(h, y + hh + pad)
        blob = (lab[y0:y1, x0:x1] == i).astype(np.uint8)
        cnts, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        solidity = a / max(1.0, cv2.contourArea(cv2.convexHull(np.vstack(cnts))))
        ring = (cv2.dilate(blob, np.ones((2 * pad + 1, 2 * pad + 1), np.uint8)) - blob).astype(bool)
        ring &= lab[y0:y1, x0:x1] == 0
        if solidity < t["glow_min_solidity"] or not ring.any():
            continue
        vb, vr = float(V[y:y + hh, x:x + ww][lab[y:y + hh, x:x + ww] == i].mean()), float(V[y0:y1, x0:x1][ring].mean())
        if vr > t["glow_surround_rel"] * vb:
            continue
        out.append({"box": [x, y, ww, hh], "area": a, "hue": int(np.median(hsv[..., 0][lab == i])),
                    "solidity": round(solidity, 2), "surround": round(vr / max(vb, 1.0), 2)})
    return out


def _face_box(a, b):
    """The face round an eye pair: the pair widened 1.5 eye widths a side, 2 eye heights up and 4 down."""
    x, y, w, h = _union(a, b)
    ew, eh = max(a[2], b[2]), max(a[3], b[3])
    return [x - 1.5 * ew, y - 2 * eh, w + 3 * ew, h + 6 * eh]


def _inside(pt, box):
    return box[0] <= pt[0] <= box[0] + box[2] and box[1] <= pt[1] <= box[1] + box[3]


def _union(a, b):
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    x1, y1 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
    return [x0, y0, x1 - x0, y1 - y0]


# ------------------------------------------------------------------------------------------------ media
def _probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,avg_frame_rate", "-of", "json", str(path)], capture_output=True, text=True)
    if r.returncode != 0:
        raise Unavailable(f"{Path(path).name} cannot be probed: {r.stderr.strip()[:200]}")
    s = (json.loads(r.stdout).get("streams") or [{}])[0]
    if not s.get("width"):
        raise Unavailable(f"{Path(path).name} has no video stream")
    num, _, den = str(s.get("avg_frame_rate") or "24/1").partition("/")
    fps = float(num) / float(den or 1) if float(num or 0) else 24.0
    return int(s["width"]), int(s["height"]), fps


def _clip_frames(path, step):
    """Yield (frame index, RGB array) for every `step`-th frame, decoded by ffmpeg at native size."""
    w, h, _ = _probe(path)
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"select='not(mod(n\\,{step}))'",
                          "-vsync", "0", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        k = 0
        while True:
            buf = p.stdout.read(w * h * 3)
            if len(buf) < w * h * 3:
                break
            yield k * step, np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            k += 1
    finally:
        p.stdout.close()
        p.wait()


def _read_still(path):
    from PIL import Image
    try:
        with Image.open(path) as im:
            return np.asarray(im.convert("RGB"))
    except OSError as e:
        raise Unavailable(f"{Path(path).name} cannot be read: {e}")


def _kind(path):
    ext = Path(path).suffix.lower()
    if ext in CLIP_EXTS:
        return "clip"
    if ext in IMAGE_EXTS:
        return "still"
    raise Unavailable(f"{Path(path).name}: not a clip ({', '.join(sorted(CLIP_EXTS))}) or a still "
                      f"({', '.join(sorted(IMAGE_EXTS))})")


# ------------------------------------------------------------------------------------------------ verdicts
def _centre(box):
    return box[0] + box[2] / 2, box[1] + box[3] / 2


def _tracks(events, step):
    """Group (frame, box) events of one kind into places: consecutive samples (gaps up to 2 samples) whose boxes
    lie within one eye size of each other."""
    tracks = []
    for f, box in sorted(events):
        cx, cy = _centre(box)
        size = max(box[2], box[3])
        for tr in tracks:
            lf, lb = tr[-1]
            lx, ly = _centre(lb)
            if f - lf <= 3 * step and math.hypot(cx - lx, cy - ly) <= max(size, lb[2], lb[3]):
                tr.append((f, box))
                break
        else:
            tracks.append([(f, box)])
    return tracks


def _morph_events(frames, t):
    """Tracked face eyes whose sclera area jumps between consecutive samples: [(frame, box, ratio)]."""
    out = []
    for prev, cur in zip(frames, frames[1:]):
        # both samples must show a measured pupil: a blink (the white shrinking to a sliver and back) is not morphing
        pe = [e for e in prev["eyes"] if e["skin"] >= t["skin_min"] and e["pupils"]]
        for e in cur["eyes"]:
            if e["skin"] < t["skin_min"] or not e["pupils"]:
                continue
            cx, cy = _centre(e["box"])
            near = [p for p in pe if math.hypot(cx - _centre(p["box"])[0], cy - _centre(p["box"])[1])
                    <= 0.5 * max(e["box"][2], e["box"][3])]
            if not near:
                continue
            p = min(near, key=lambda q: math.hypot(cx - _centre(q["box"])[0], cy - _centre(q["box"])[1]))
            ratio = max(e["sclera_area"], p["sclera_area"]) / max(1, min(e["sclera_area"], p["sclera_area"]))
            if ratio > t["morph_area_ratio"]:
                out.append((cur["frame"], e["box"], round(ratio, 2)))
    return out


def judge(frames, kind, thresholds: dict = None, fps: float = 24.0) -> dict:
    """Aggregate per-frame findings into {"findings", "pass", "needs_review", "notes", "flagged_frames"}."""
    t = {**THRESHOLDS, **(thresholds or {})}
    step = t["step"] if kind == "clip" else 1
    by_kind = {}
    for fr in frames:
        for f in fr["findings"]:
            by_kind.setdefault(f["kind"], []).append((fr["frame"], f["box"], f["detail"]))
    for f, box, ratio in _morph_events(frames, t):
        by_kind.setdefault("morph", []).append((f, box, f"eye white area changed {ratio}x since the previous sample"))
    persist = {"double_pupil": t["double_persist"], "missing_pupil": t["missing_persist"],
               "glow": t["glow_persist"], "eye_off_face": t["off_face_persist"]}
    findings = []
    for k, evs in sorted(by_kind.items()):
        details = {(f, tuple(b)): d for f, b, d in evs}
        for tr in _tracks([(f, tuple(b)) for f, b, _ in evs], step):
            fr_list = [f for f, _ in tr]
            n = len(fr_list)
            if k in ("double_pupil", "missing_pupil"):
                if kind == "still":
                    sev = "fail" if k == "double_pupil" else "review"
                else:
                    sev = "fail" if n >= persist[k] else "review"
            elif k in ("glow", "eye_off_face"):
                if kind == "clip" and n < persist[k] or kind == "still" and k == "eye_off_face":
                    continue        # a one- or two-sample sparkle is not listed
                sev = "review"
            else:
                sev = "review"
            mid = tr[len(tr) // 2]
            findings.append({"kind": k, "severity": sev, "frames": fr_list,
                             "times": [round(f / fps, 3) for f in fr_list] if kind == "clip" else [],
                             "box": list(mid[1]), "boxes": [list(b) for _, b in tr],
                             "detail": details[(mid[0], mid[1])], "samples": n})
    order = {"fail": 0, "review": 1}
    findings.sort(key=lambda f: (order[f["severity"]], f["frames"][0]))
    fails = [f for f in findings if f["severity"] == "fail"]
    reviews = [f for f in findings if f["severity"] == "review"]
    notes = []
    for f in fails + reviews:
        where = (f"frames {f['frames'][0]}-{f['frames'][-1]} ({f['samples']} samples)" if kind == "clip" else "still")
        notes.append(f"{f['severity'].upper()} {f['kind'].replace('_', ' ')}: {where}; {f['detail']}")
    face_frames = sum(1 for fr in frames if any(e["skin"] >= t["skin_min"] and e["iris"] for e in fr["eyes"]))
    if not face_frames:
        notes.append("no eyes on a face detected: not judged (look at the sheet or contact sheet)")
    flagged = sorted({f for x in findings for f in x["frames"]})
    return {"findings": findings, "pass": not fails, "needs_review": bool(reviews) and not fails,
            "notes": notes, "flagged_frames": flagged, "face_frames": face_frames}


def check(path, thresholds: dict = None, key: str = None) -> dict:
    """Run the gate on one clip or still; nothing is written. `key` names it (default: the file stem)."""
    _require()
    path = Path(path)
    t = {**THRESHOLDS, **(thresholds or {})}
    kind = _kind(path)
    frames = []
    if kind == "clip":
        _, _, fps = _probe(path)
        for i, rgb in _clip_frames(path, t["step"]):
            frames.append({"frame": i, **analyse_image(rgb, t)})
        if not frames:
            raise Unavailable(f"{path.name}: no frames decoded")
    else:
        fps = 0.0
        frames.append({"frame": 0, **analyse_image(_read_still(path), t)})
    res = judge(frames, kind, t, fps or 24.0)
    return {"key": key or path.stem, "file": path.name, "kind": kind, "sha256": sha256_file(path),
            "fps": round(fps, 3) if fps else None, "sampled": len(frames), "frames": frames, **res,
            "identity": IDENTITY, "method": METHOD, "version": VERSION,
            "thresholds": dict(t), "thresholds_calibrated": False, "calibration": CALIBRATION}


# ------------------------------------------------------------------------------------------------ sheet
def _face_boxes(fr, t, w, h, extra=()):
    """Face crop boxes of a frame: each pair (or lone face eye) widened to the face round it."""
    eyes = fr["eyes"]
    used, groups = set(), []
    for a, b in fr.get("pairs") or []:
        if a in used or b in used:
            continue
        used |= {a, b}
        groups.append(_union(eyes[a]["box"], eyes[b]["box"]))
    for i, e in enumerate(eyes):
        if i not in used and e["skin"] >= t["skin_min"] and e["iris"]:
            groups.append(list(e["box"]))
    groups += [list(b) for b in extra]   # a flagged glow or eye off the face gets its own crop
    out = []
    for gx, gy, gw, gh in groups:
        side = max(gw * 1.9, gh * 4.0, 60)
        cx, cy = gx + gw / 2, gy + gh / 2 + 0.35 * side * 0.5
        x0, y0 = int(max(0, cx - side / 2)), int(max(0, cy - side * 0.45))
        x1, y1 = int(min(w, cx + side / 2)), int(min(h, cy + side * 0.55))
        if x1 - x0 > 8 and y1 - y0 > 8:
            out.append((x0, y0, x1, y1))
    return _dedupe(out)[:4]


def _dedupe(boxes):
    out = []
    for b in sorted(boxes, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1])):
        if not any(b[0] >= o[0] - 4 and b[1] >= o[1] - 4 and b[2] <= o[2] + 4 and b[3] <= o[3] + 4 for o in out):
            out.append(b)
    return out


def _font(size):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1: the fixed bitmap font
        return ImageFont.load_default()


def _tiles(path, res, t):
    """[(label, RGB tile, flagged)] for the review sheet."""
    from PIL import Image, ImageDraw
    by_frame = {fr["frame"]: fr for fr in res["frames"]}
    flagged = {}   # frame -> [{kind, severity, the box measured in that frame}]
    for f in res["findings"]:
        for fr, box in zip(f["frames"], f.get("boxes") or [f["box"]] * len(f["frames"])):
            flagged.setdefault(fr, []).append({"kind": f["kind"], "severity": f["severity"], "box": box})
    if res["kind"] == "clip":
        every = max(t["sheet_every"], t["step"])
        want = sorted({f for f in by_frame if f % every == 0} | set(flagged))
        source = {i: rgb for i, rgb in _clip_frames(path, t["step"]) if i in want}
    else:
        want, source = [0], {0: _read_still(path)}
    tiles, last = [], None
    T, scale = int(t["sheet_tile"]), float(t["sheet_scale"])
    any_face = any(_face_boxes(by_frame[f], t, *source[f].shape[1::-1],
                               [x["box"] for x in flagged.get(f, []) if x["kind"] in ("glow", "eye_off_face")])
                   for f in want if f in source)
    whole = [] if any_face else sorted(source)[::max(1, len(source) // 3)][:3]   # no face found: whole frames
    for f in want:
        rgb = source.get(f)
        if rgb is None:
            continue
        h, w = rgb.shape[:2]
        if f in whole:
            boxes = [(0, 0, w, h)]
        elif not any_face:
            continue
        else:
            extra = [x["box"] for x in flagged.get(f, []) if x["kind"] in ("glow", "eye_off_face")]
            boxes = _face_boxes(by_frame[f], t, w, h, extra) or ([last] if last else [])
        if boxes:
            last = boxes[0]
        for x0, y0, x1, y1 in boxes:
            crop = Image.fromarray(rgb[y0:y1, x0:x1])
            k = min(scale, T / crop.width, T / crop.height)
            crop = crop.resize((max(1, int(crop.width * k)), max(1, int(crop.height * k))), Image.LANCZOS)
            tile = Image.new("RGB", (T, T + 18), (24, 24, 24))
            ox, oy = (T - crop.width) // 2, (T - crop.height) // 2
            tile.paste(crop, (ox, oy))
            d = ImageDraw.Draw(tile)
            bad = flagged.get(f, [])
            for fd in bad:
                bx, by, bw, bh = fd["box"]
                rx0, ry0 = ox + (bx - x0) * k, oy + (by - y0) * k
                d.rectangle([rx0 - 3, ry0 - 3, rx0 + bw * k + 3, ry0 + bh * k + 3],
                            outline=(255, 0, 0) if fd["severity"] == "fail" else (255, 170, 0), width=2)
            if bad:
                d.rectangle([0, 0, T - 1, T + 17], outline=(255, 0, 0), width=5)
            label = (f"{res['key']} f{f:03d}" + (f" {f / res['fps']:.2f}s" if res.get("fps") else "")
                     + (" no face found: whole frame" if f in whole else "")
                     + (" " + ",".join(sorted({x['kind'] for x in bad})) if bad else ""))
            d.text((4, T + 1), label[:48], fill=(255, 80, 80) if bad else (220, 220, 220), font=_font(13))
            tiles.append((label, tile, bool(bad)))
    return tiles


def _grid(tiles, cols, title=None):
    from PIL import Image, ImageDraw
    if not tiles:
        return None
    tw, th = tiles[0][1].size
    rows = math.ceil(len(tiles) / cols)
    top = 22 if title else 0
    sheet = Image.new("RGB", (cols * tw + (cols + 1) * 4, top + rows * th + (rows + 1) * 4), (8, 8, 8))
    if title:
        ImageDraw.Draw(sheet).text((6, 3), title[:200], fill=(255, 255, 255), font=_font(15))
    for i, (_, tile, _) in enumerate(tiles):
        sheet.paste(tile, (4 + (i % cols) * (tw + 4), top + 4 + (i // cols) * (th + 4)))
    return sheet


def write_sheet(path, res, out_png, thresholds: dict = None):
    """The face close-up sheet of one clip or still: face crops enlarged ~3x, flagged frames boxed in red.
    Returns the path, or None when no face was found (nothing to crop)."""
    t = {**THRESHOLDS, **(thresholds or {})}
    tiles = _tiles(Path(path), res, t)
    sheet = _grid(tiles, int(t["sheet_cols"]), f"{res['key']}: face close-ups x{t['sheet_scale']:g} "
                  f"(red = flagged); {'FAIL' if not res['pass'] else 'REVIEW' if res['needs_review'] else 'pass'}")
    if sheet is None:
        return None
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png)
    return out_png


def scene_sheet(sections, out_path, cols: int = 8, max_h: int = 60000):
    """One review sheet for a scene: sections [(title, sheet PNG path)] stacked; JPEG-safe height."""
    from PIL import Image, ImageDraw
    ims = []
    for title, p in sections:
        if p and Path(p).is_file():
            with Image.open(p) as im:
                ims.append((title, im.convert("RGB")))
    if not ims:
        return None
    width = max(im.width for _, im in ims)
    height = sum(im.height + 26 for _, im in ims)
    sheet = Image.new("RGB", (width, min(height, max_h)), (0, 0, 0))
    y = 0
    for title, im in ims:
        if y + 26 + im.height > max_h:
            ImageDraw.Draw(sheet).text((6, y + 4), "... sheet cut at the JPEG height limit: open the per-clip sheets",
                                       fill=(255, 80, 80), font=_font(16))
            break
        ImageDraw.Draw(sheet).text((6, y + 4), title[:200], fill=(255, 255, 0), font=_font(16))
        sheet.paste(im, (0, y + 26))
        y += 26 + im.height
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=90)
    return out_path


# ------------------------------------------------------------------------------------------------ gate
def gate(path, out_dir=None, thresholds: dict = None, reuse: bool = True, key: str = None) -> dict:
    """check() plus <key>.face.json and <key>.faces.png in out_dir (default: beside the source). A face.json made
    from the same source sha256, gate version and thresholds is reused (the sheet is redrawn if it is missing)."""
    path = Path(path)
    out_dir = Path(out_dir) if out_dir else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    key = key or path.stem
    out_json = out_dir / f"{key}.face.json"
    t = {**THRESHOLDS, **(thresholds or {})}
    res = None
    if reuse and out_json.is_file():
        try:
            old = json.loads(out_json.read_text(encoding="utf-8"))
            if (old.get("sha256") == sha256_file(path) and old.get("version") == VERSION and old.get("key") == key
                    and old.get("thresholds") == json.loads(json.dumps(t))):
                res = old
        except (OSError, ValueError):
            res = None
    if res is None:
        res = check(path, t, key)
    sheet = out_dir / f"{key}.faces.png"
    if not sheet.is_file() or res.get("sheet") != sheet.name:
        made = write_sheet(path, res, sheet, t)
        res["sheet"] = made.name if made else None
    out_json.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return res


def summary_line(res) -> str:
    verdict = "FAIL" if not res["pass"] else ("REVIEW" if res["needs_review"] else "pass")
    return f"{verdict:6} {res['file']}: " + ("; ".join(res["notes"]) or "eyes look normal")
