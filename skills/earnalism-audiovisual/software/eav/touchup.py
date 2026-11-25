"""Touch-up: local, deterministic repaint of small defects inside hand-placed boxes.

Free open generators keep drawing details a story forbids (a bindi or ear studs on a child
widow, a judge's moustache, overhead wires in an 1880s lane, corner signatures, fruit out of
season) and text-prompted masks miss them. A touch-up repaints only hand-placed boxes of an
imported still with OpenCV (Apache-2.0), on the CPU, with no model and no randomness:

  {"op": "inpaint", "box": [x0, y0, x1, y1], "radius": 3..15, "method": "telea"|"ns"}
  {"op": "recolor", "box": [...], "from": {"hue": [h0, h1], "sat_min": s}, "to": "#F4F1EA"}
  {"op": "fill", "box": [...], "sample": [x, y]}
  {"op": "clone", "box": [...], "from": [dx, dy]}

Boxes are source pixel coordinates, x1/y1 exclusive. Every op may narrow its box with
"mask": "box" (default) | "ellipse" (inscribed) | "color" ("target": "#RRGGBB", "tol": RGB
distance, "grow": px). Edits are feathered over "feather" px (default 3) inside the box, so
pixels outside every box stay byte-identical. Hues are degrees 0-360 (h0 > h1 wraps through
red); saturation (chroma: max - min channel) and lightness are 0-1. recolor keeps each
pixel's Lab lightness by default; "lightness": "shade" puts the target's lightness under the pixels' own shading instead (a
coloured sari edge to white without leaving a grey stripe).
"""
import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover - reported by apply()
    cv2 = None

OPS = ("inpaint", "recolor", "fill", "clone")
MASKS = ("box", "ellipse", "color")
RADIUS = (3, 15)
FEATHER = (0, 20)
DEFAULT_FEATHER = 3
MAX_OPS = 40
_OP_KEYS = {"inpaint": {"radius", "method"}, "recolor": {"from", "to", "lightness"},
            "fill": {"sample"}, "clone": {"from"}}
_COMMON = {"op", "box", "mask", "target", "tol", "grow", "feather", "note"}


def opencv_version() -> str:
    _need_cv2()
    return cv2.__version__


def _need_cv2():
    if cv2 is None:
        raise ValueError("touchup needs opencv-python-headless (software/requirements-touchup.txt)")


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _hex(v, what):
    if not (isinstance(v, str) and len(v) == 7 and v[0] == "#"):
        raise ValueError(f"{what} must be a #RRGGBB colour, not {v!r}")
    try:
        return tuple(int(v[i:i + 2], 16) for i in (1, 3, 5))
    except ValueError:
        raise ValueError(f"{what} must be a #RRGGBB colour, not {v!r}") from None


def validate_ops(ops, size) -> list:
    """Check an op list against an image size (w, h); returns the ops unchanged or raises."""
    w, h = size
    if not isinstance(ops, list) or not 1 <= len(ops) <= MAX_OPS:
        raise ValueError(f"ops must be a list of 1 to {MAX_OPS} ops")
    for i, op in enumerate(ops):
        where = f"op {i + 1}"
        if not isinstance(op, dict) or op.get("op") not in OPS:
            raise ValueError(f"{where}: op must be one of {', '.join(OPS)}")
        kind = op["op"]
        extra = set(op) - _COMMON - _OP_KEYS[kind]
        if extra:
            raise ValueError(f"{where} ({kind}): unknown field(s) {', '.join(sorted(extra))}")
        box = op.get("box")
        if not (isinstance(box, list) and len(box) == 4 and all(_int(v) for v in box)):
            raise ValueError(f"{where}: box must be [x0, y0, x1, y1] integers")
        x0, y0, x1, y1 = box
        if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
            raise ValueError(f"{where}: box {box} is not inside the {w}x{h} image")
        mask = op.get("mask", "box")
        if mask not in MASKS:
            raise ValueError(f"{where}: mask must be one of {', '.join(MASKS)}")
        if mask == "color":
            _hex(op.get("target"), f"{where} target")
            if not _num(op.get("tol")) or not 0 < op["tol"] <= 442:
                raise ValueError(f"{where}: a color mask needs tol (RGB distance 1-442)")
        elif "target" in op or "tol" in op:
            raise ValueError(f"{where}: target/tol belong to mask \"color\"")
        if "grow" in op and (not _int(op["grow"]) or not 0 <= op["grow"] <= 10):
            raise ValueError(f"{where}: grow must be 0-10 px")
        f = op.get("feather", DEFAULT_FEATHER)
        if not _int(f) or not FEATHER[0] <= f <= FEATHER[1]:
            raise ValueError(f"{where}: feather must be {FEATHER[0]}-{FEATHER[1]} px")
        if kind == "inpaint":
            r = op.get("radius")
            if not _int(r) or not RADIUS[0] <= r <= RADIUS[1]:
                raise ValueError(f"{where}: inpaint radius must be {RADIUS[0]}-{RADIUS[1]}")
            if op.get("method", "telea") not in ("telea", "ns"):
                raise ValueError(f"{where}: inpaint method must be telea or ns")
        elif kind == "recolor":
            src = op.get("from")
            if not isinstance(src, dict) or set(src) - {"hue", "sat_min", "light_min", "light_max"}:
                raise ValueError(f"{where}: recolor from must be {{hue, sat_min[, light_min, light_max]}}")
            hue = src.get("hue")
            if not (isinstance(hue, list) and len(hue) == 2 and all(_num(v) and 0 <= v <= 360 for v in hue)):
                raise ValueError(f"{where}: recolor from.hue must be [h0, h1] degrees 0-360")
            for k in ("sat_min", "light_min", "light_max"):
                if k in src and (not _num(src[k]) or not 0 <= src[k] <= 1):
                    raise ValueError(f"{where}: recolor from.{k} must be 0-1")
            if "sat_min" not in src:
                raise ValueError(f"{where}: recolor from needs sat_min")
            _hex(op.get("to"), f"{where} to")
            if op.get("lightness", "keep") not in ("keep", "shade"):
                raise ValueError(f"{where}: recolor lightness must be keep or shade")
        elif kind == "fill":
            s = op.get("sample")
            if not (isinstance(s, list) and len(s) == 2 and all(_int(v) for v in s)
                    and 0 <= s[0] < w and 0 <= s[1] < h):
                raise ValueError(f"{where}: fill sample must be [x, y] inside the image")
        elif kind == "clone":
            d = op.get("from")
            if not (isinstance(d, list) and len(d) == 2 and all(_int(v) for v in d)) or d == [0, 0]:
                raise ValueError(f"{where}: clone from must be a non-zero [dx, dy] offset")
            if not (0 <= x0 + d[0] and x1 + d[0] <= w and 0 <= y0 + d[1] and y1 + d[1] <= h):
                raise ValueError(f"{where}: clone source box {[x0 + d[0], y0 + d[1], x1 + d[0], y1 + d[1]]} "
                                 f"is not inside the {w}x{h} image")
    return ops


def _hard(img, op) -> np.ndarray:
    """The op's selection (bool, whole image size), inside its box only."""
    h, w = img.shape[:2]
    x0, y0, x1, y1 = op["box"]
    m = np.zeros((h, w), np.uint8)
    mode = op.get("mask", "box")
    if mode == "box":
        m[y0:y1, x0:x1] = 1
    elif mode == "ellipse":
        yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
        cx, cy, rx, ry = (x0 + x1 - 1) / 2, (y0 + y1 - 1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
        m[y0:y1, x0:x1] = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0
    else:
        t = np.array(_hex(op["target"], "target"), np.float32)
        d = np.sqrt(((img[y0:y1, x0:x1].astype(np.float32) - t) ** 2).sum(axis=2))
        m[y0:y1, x0:x1] = d <= op["tol"]
    grow = op.get("grow", 2 if mode == "color" else 0)
    if grow and m.any():
        m = cv2.dilate(m, np.ones((2 * grow + 1, 2 * grow + 1), np.uint8))
    box = np.zeros_like(m)
    box[y0:y1, x0:x1] = 1
    return (m & box).astype(bool)


def _alpha(hard, feather) -> np.ndarray:
    """Feathered weight: 0 outside the selection, ramping to 1 over `feather` px inside it."""
    if not hard.any():
        return np.zeros(hard.shape, np.float32)
    if feather <= 0:
        return hard.astype(np.float32)
    # distance to the nearest unselected pixel; pad so the image border does not count as one
    pad = cv2.copyMakeBorder(hard.astype(np.uint8), 1, 1, 1, 1, cv2.BORDER_REPLICATE)
    dist = cv2.distanceTransform(pad, cv2.DIST_L2, 5)[1:-1, 1:-1]
    return np.clip(dist / float(feather), 0.0, 1.0).astype(np.float32) * hard


def _recolor_target(img, op, hard):
    """(edited image, selection) for recolor: matching pixels moved to the target colour."""
    hls = cv2.cvtColor(img, cv2.COLOR_RGB2HLS_FULL).astype(np.float32)
    hue = hls[..., 0] * 360.0 / 256.0
    # saturation as chroma (max - min channel): HLS saturation explodes near white and black
    f = img.astype(np.float32)
    light, sat = hls[..., 1] / 255.0, (f.max(axis=2) - f.min(axis=2)) / 255.0
    src = op["from"]
    h0, h1 = src["hue"]
    in_hue = (hue >= h0) & (hue <= h1) if h0 <= h1 else (hue >= h0) | (hue <= h1)
    sel = hard & in_hue & (sat >= src["sat_min"])
    if "light_min" in src:
        sel &= light >= src["light_min"]
    if "light_max" in src:
        sel &= light <= src["light_max"]
    matched = sel
    grow = op.get("grow", 1)
    if grow and sel.any():  # take in the anti-aliased rim of the matched pixels
        k = np.ones((2 * grow + 1, 2 * grow + 1), np.uint8)
        sel = cv2.dilate(sel.astype(np.uint8), k).astype(bool) & hard
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
    tgt = np.array([[_hex(op["to"], "to")]], np.uint8)
    t_lab = cv2.cvtColor(tgt, cv2.COLOR_RGB2LAB).astype(np.float32)[0, 0]
    new = lab.copy()
    new[..., 1], new[..., 2] = t_lab[1], t_lab[2]
    if op.get("lightness", "keep") == "shade" and matched.any():
        # the target lightness, with the matched pixels' own shading (deviation from their
        # brightest tone) kept, so folds and line art survive; never brighter than the pixel
        # or the target already is (the rim stays as light as it was)
        ref = np.percentile(lab[..., 0][matched], 90)
        new[..., 0] = np.clip(t_lab[0] + (lab[..., 0] - ref), 0, np.maximum(lab[..., 0], t_lab[0]))
    edited = cv2.cvtColor(np.clip(new, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
    return edited, sel


def _edited(img, op, hard):
    kind = op["op"]
    if kind == "inpaint":
        flag = cv2.INPAINT_TELEA if op.get("method", "telea") == "telea" else cv2.INPAINT_NS
        return cv2.inpaint(img, hard.astype(np.uint8) * 255, op["radius"], flag), hard
    if kind == "recolor":
        return _recolor_target(img, op, hard)
    if kind == "fill":
        x, y = op["sample"]
        h, w = img.shape[:2]
        patch = img[max(0, y - 1):min(h, y + 2), max(0, x - 1):min(w, x + 2)].reshape(-1, 3)
        colour = np.median(patch, axis=0).round().astype(np.uint8)
        return np.broadcast_to(colour, img.shape).copy(), hard
    dx, dy = op["from"]
    x0, y0, x1, y1 = op["box"]
    out = img.copy()
    out[y0:y1, x0:x1] = img[y0 + dy:y1 + dy, x0 + dx:x1 + dx]
    return out, hard


def apply(img: np.ndarray, ops: list):
    """Apply ops in order to an RGB uint8 image; returns (edited image, mask uint8 0-255).

    Each op reads the result of the ops before it. The mask is the maximum feathered weight
    of every op (review only; it never enters the film)."""
    _need_cv2()
    if img.dtype != np.uint8 or img.ndim != 3 or img.shape[2] != 3:
        raise ValueError("touchup works on RGB uint8 images")
    validate_ops(ops, (img.shape[1], img.shape[0]))
    out = np.ascontiguousarray(img.copy())
    weight = np.zeros(img.shape[:2], np.float32)
    for op in ops:
        hard = _hard(out, op)
        edited, sel = _edited(out, op, hard)
        a = _alpha(sel, op.get("feather", DEFAULT_FEATHER))
        if not a.any():
            continue
        x0, y0, x1, y1 = op["box"]
        a = a[y0:y1, x0:x1, None]
        cur = out[y0:y1, x0:x1].astype(np.float32)
        mixed = cur + (edited[y0:y1, x0:x1].astype(np.float32) - cur) * a
        region = np.where(a > 0, np.clip(np.rint(mixed), 0, 255), cur).astype(np.uint8)
        out[y0:y1, x0:x1] = region
        weight[y0:y1, x0:x1] = np.maximum(weight[y0:y1, x0:x1], a[..., 0])
    return out, np.rint(weight * 255).astype(np.uint8)
