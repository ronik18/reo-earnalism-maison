"""Clip touch-up: remove a small fixed defect from an imported Wan clip, locally, into a NEW clip file.

A free generator sometimes leaves a detail a story forbids in a clip (an LED-like glowing rectangle between the
slats of an 1880s carriage). Regenerating costs compute; a touch-up repaints one recorded mask in every frame with
OpenCV (Apache-2.0) and NumPy, on the CPU, with no model and no randomness. The source clip is never written.

An item ("mask", "fill", "mode"):

  mask  {"box": [x0, y0, x1, y1],                 source pixel coordinates, x1/y1 exclusive
         "select": [{"hue": [h0, h1], "sat_min": s, "light_min": l, "light_max": l}, ...],   optional: only the
                                                    pixels of the box that match any one rule (on the clip's
                                                    per-pixel temporal median), else the whole box
         "grow": px 0-10 (default 2), "feather": px 0-10 (default 2)}
        The mask is computed ONCE, on the temporal median of the clip, and recorded as a PNG: every frame is
        repainted inside the same pixels (a fixed defect; no per-frame guess, so nothing flickers).
  fill  {"method": "along", "angle": degrees}      fills each pixel from the nearest unmasked pixels on both sides
                                                    along the given direction (the slats, a beam, a floor line),
                                                    blended by distance: straight edges that run that way survive
        {"method": "telea" | "ns", "radius": 3-15}  cv2.inpaint
  mode  "plate"  the fill is made once on the temporal median and composited into every frame (the background
                 must be static round the mask: refused when any frame's ring round the mask differs from the
                 median by more than STATIC_MAX levels on average)
        "each"   the fill is made in every frame from that frame's own pixels

Hues are degrees 0-360 (h0 > h1 wraps through red); saturation is chroma (max - min channel) and lightness is HLS
lightness, both 0-1, as in eav.touchup.
"""
import json
import math
import subprocess
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover - reported by apply_clip()
    cv2 = None

SCHEMA = "earnalism.audiovisual-clip-touchup.v1"
FILLS = ("along", "telea", "ns")
MODES = ("plate", "each")
STATIC_MAX = 4.0        # mean abs RGB deviation from the median in the ring round the mask (plate mode)
RING = 8                # px: the ring round the mask that the static check and the outside comparison read
CRF = 12                # x264 quality of the touched clip (visually lossless; the film re-encodes it at crf 16)
_MASK_KEYS = {"box", "select", "grow", "feather"}
_RULE_KEYS = {"hue", "sat_min", "light_min", "light_max"}


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def validate(item: dict, size: tuple) -> dict:
    """Check one item's mask, fill and mode against a clip size (w, h); returns the item or raises ValueError."""
    w, h = size
    m = item.get("mask")
    if not isinstance(m, dict) or set(m) - _MASK_KEYS:
        raise ValueError(f"mask must be {{{', '.join(sorted(_MASK_KEYS))}}}")
    box = m.get("box")
    if not (isinstance(box, list) and len(box) == 4 and all(_int(v) for v in box)):
        raise ValueError("mask box must be [x0, y0, x1, y1] integers")
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        raise ValueError(f"mask box {box} is not inside the {w}x{h} clip")
    for k in ("grow", "feather"):
        if k in m and (not _int(m[k]) or not 0 <= m[k] <= 10):
            raise ValueError(f"mask {k} must be 0-10 px")
    sel = m.get("select")
    if sel is not None:
        if not isinstance(sel, list) or not sel:
            raise ValueError("mask select must be a non-empty list of rules")
        for r in sel:
            if not isinstance(r, dict) or not r or set(r) - _RULE_KEYS:
                raise ValueError(f"a select rule is {{{', '.join(sorted(_RULE_KEYS))}}} (at least one)")
            if "hue" in r and not (isinstance(r["hue"], list) and len(r["hue"]) == 2
                                   and all(_num(v) and 0 <= v <= 360 for v in r["hue"])):
                raise ValueError("select hue must be [h0, h1] degrees 0-360")
            for k in ("sat_min", "light_min", "light_max"):
                if k in r and (not _num(r[k]) or not 0 <= r[k] <= 1):
                    raise ValueError(f"select {k} must be 0-1")
    f = item.get("fill")
    if not isinstance(f, dict) or f.get("method") not in FILLS:
        raise ValueError(f"fill method must be one of {', '.join(FILLS)}")
    if f["method"] == "along":
        if set(f) != {"method", "angle"} or not _num(f["angle"]) or not -90 <= f["angle"] <= 90:
            raise ValueError("fill along needs angle: degrees -90..90 (0 = horizontal, positive = down to the right)")
    else:
        if set(f) != {"method", "radius"} or not _int(f["radius"]) or not 3 <= f["radius"] <= 15:
            raise ValueError("fill telea/ns needs radius 3-15")
    if item.get("mode", "plate") not in MODES:
        raise ValueError(f"mode must be one of {', '.join(MODES)}")
    return item


def _need_cv2():
    if cv2 is None:
        raise ValueError("clip touch-up needs opencv-python-headless (software/requirements-touchup.txt)")


def opencv_version() -> str:
    _need_cv2()
    return cv2.__version__


def select(plate: np.ndarray, mask: dict) -> np.ndarray:
    """The hard mask (bool, frame size): the box, narrowed by the select rules, grown by "grow" px, inside the box."""
    h, w = plate.shape[:2]
    x0, y0, x1, y1 = mask["box"]
    box = np.zeros((h, w), bool)
    box[y0:y1, x0:x1] = True
    rules = mask.get("select")
    if not rules:
        sel = box.copy()
    else:
        hls = cv2.cvtColor(plate, cv2.COLOR_RGB2HLS_FULL).astype(np.float32)
        hue, light = hls[..., 0] * 360.0 / 256.0, hls[..., 1] / 255.0
        f = plate.astype(np.float32)
        sat = (f.max(axis=2) - f.min(axis=2)) / 255.0
        sel = np.zeros((h, w), bool)
        for r in rules:
            m = box.copy()
            if "hue" in r:
                a, b = r["hue"]
                m &= ((hue >= a) & (hue <= b)) if a <= b else ((hue >= a) | (hue <= b))
            if "sat_min" in r:
                m &= sat >= r["sat_min"]
            if "light_min" in r:
                m &= light >= r["light_min"]
            if "light_max" in r:
                m &= light <= r["light_max"]
            sel |= m
    g = mask.get("grow", 2)
    if g and sel.any():
        sel = cv2.dilate(sel.astype(np.uint8), np.ones((2 * g + 1, 2 * g + 1), np.uint8)).astype(bool) & box
    return sel


def alpha(hard: np.ndarray, feather: int) -> np.ndarray:
    """0 outside the mask, ramping to 1 over `feather` px inside it."""
    if feather <= 0 or not hard.any():
        return hard.astype(np.float32)
    pad = cv2.copyMakeBorder(hard.astype(np.uint8), 1, 1, 1, 1, cv2.BORDER_REPLICATE)
    dist = cv2.distanceTransform(pad, cv2.DIST_L2, 5)[1:-1, 1:-1]
    return (np.clip(dist / float(feather), 0.0, 1.0) * hard).astype(np.float32)


def fill_along(img: np.ndarray, hard: np.ndarray, angle: float) -> np.ndarray:
    """Each masked pixel from the first unmasked pixel on each side along `angle`, blended by inverse distance."""
    h, w = hard.shape
    v = np.array([math.cos(math.radians(angle)), math.sin(math.radians(angle))])
    ys, xs = np.nonzero(hard)
    out = img.astype(np.float32).copy()
    if not len(xs):
        return img.copy()
    src = img.astype(np.float32)
    acc = np.zeros((len(xs), 3), np.float32)
    wsum = np.zeros(len(xs), np.float32)
    for s in (1.0, -1.0):
        t = np.zeros(len(xs), np.float32)
        open_ = np.ones(len(xs), bool)
        for _ in range(4 * (w + h)):
            if not open_.any():
                break
            t[open_] += 0.5
            px = np.clip(np.rint(xs + s * v[0] * t).astype(int), 0, w - 1)
            py = np.clip(np.rint(ys + s * v[1] * t).astype(int), 0, h - 1)
            open_ &= hard[py, px]
        ok = ~open_   # reached an unmasked pixel (else: ran off the frame, that side is ignored)
        t += 1.0      # one pixel past the mask edge: off its anti-aliased rim
        mx = (xs + s * v[0] * t).astype(np.float32)
        my = (ys + s * v[1] * t).astype(np.float32)
        inside = ok & (mx >= 0) & (mx <= w - 1) & (my >= 0) & (my <= h - 1)
        smp = cv2.remap(src, mx.reshape(1, -1), my.reshape(1, -1), cv2.INTER_LINEAR,
                        borderMode=cv2.BORDER_REPLICATE).reshape(-1, 3)
        wt = np.where(inside, 1.0 / t, 0.0).astype(np.float32)
        acc += smp * wt[:, None]
        wsum += wt
    good = wsum > 0
    out[ys[good], xs[good]] = acc[good] / wsum[good, None]
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def fill(img: np.ndarray, hard: np.ndarray, spec: dict) -> np.ndarray:
    if spec["method"] == "along":
        return fill_along(img, hard, spec["angle"])
    flag = cv2.INPAINT_TELEA if spec["method"] == "telea" else cv2.INPAINT_NS
    return cv2.inpaint(np.ascontiguousarray(img), hard.astype(np.uint8) * 255, spec["radius"], flag)


def blend(frame: np.ndarray, filled: np.ndarray, a: np.ndarray) -> np.ndarray:
    """frame outside the mask (byte-identical in RGB), filled inside it, feathered at the edge."""
    out = frame.copy()
    sel = a > 0
    mixed = frame[sel].astype(np.float32) * (1 - a[sel, None]) + filled[sel].astype(np.float32) * a[sel, None]
    out[sel] = np.clip(np.rint(mixed), 0, 255).astype(np.uint8)
    return out


def ring(hard: np.ndarray, px: int = RING) -> np.ndarray:
    big = cv2.dilate(hard.astype(np.uint8), np.ones((2 * px + 1, 2 * px + 1), np.uint8)).astype(bool)
    return big & ~hard


# ---------------------------------------------------------------------------------------------------- video I/O
def probe(path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate,nb_read_frames", "-of", "json", str(path)],
                       check=True, capture_output=True, text=True)
    st = json.loads(r.stdout)["streams"][0]
    a = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of",
                        "csv=p=0", str(path)], check=True, capture_output=True, text=True).stdout.strip()
    return {"width": int(st["width"]), "height": int(st["height"]), "fps": st["r_frame_rate"],
            "frames": int(st["nb_read_frames"]), "audio": bool(a)}


def read_frames(path, size) -> np.ndarray:
    w, h = size
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       check=True, capture_output=True)
    n = len(r.stdout) // (w * h * 3)
    return np.frombuffer(r.stdout[:n * w * h * 3], np.uint8).reshape(n, h, w, 3)


def write_frames(frames: np.ndarray, fps: str, out: Path, audio_from: Path = None):
    n, h, w, _ = frames.shape
    args = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", fps,
            "-i", "-"]
    if audio_from is not None:
        args += ["-i", str(audio_from), "-map", "0:v", "-map", "1:a", "-c:a", "copy"]
    args += ["-c:v", "libx264", "-preset", "slow", "-crf", str(CRF), "-pix_fmt", "yuv420p", "-frames:v", str(n),
             "-movflags", "+faststart", str(out)]
    subprocess.run(args, input=frames.tobytes(), check=True, capture_output=True)


def apply_clip(src: Path, item: dict, out: Path, review_dir: Path) -> dict:
    """Touch one clip up into `out` (never `src`). Writes the mask and before/after crops into review_dir (review
    only) and returns the measurements for the record."""
    _need_cv2()
    src, out, review_dir = Path(src), Path(out), Path(review_dir)
    if src.resolve() == out.resolve():
        raise ValueError("the touched clip must be a new file, never the source clip")
    info = probe(src)
    validate(item, (info["width"], info["height"]))
    frames = read_frames(src, (info["width"], info["height"]))
    if len(frames) != info["frames"]:
        raise ValueError(f"decoded {len(frames)} frames but the clip has {info['frames']}")
    plate = np.median(frames, axis=0).astype(np.uint8)
    hard = select(plate, item["mask"])
    if not hard.any():
        raise ValueError("the mask selects no pixel: check the box and select rules")
    a = alpha(hard, item["mask"].get("feather", 2))
    rg = ring(hard)
    dev = np.abs(frames[:, rg].astype(np.float32) - plate[rg].astype(np.float32)).mean(axis=(1, 2))
    mode = item.get("mode", "plate")
    if mode == "plate" and float(dev.max()) > STATIC_MAX:
        raise ValueError(f"the background round the mask moves (ring deviation up to {dev.max():.1f} > {STATIC_MAX}): "
                         "use mode \"each\"")
    if mode == "plate":
        patch = fill(plate, hard, item["fill"])
        done = np.stack([blend(f, patch, a) for f in frames])
    else:
        done = np.stack([blend(f, fill(f, hard, item["fill"]), a) for f in frames])
    out.parent.mkdir(parents=True, exist_ok=True)
    write_frames(done, info["fps"], out, src if info["audio"] else None)
    got = read_frames(out, (info["width"], info["height"]))
    if len(got) != len(frames):
        raise ValueError(f"the touched clip has {len(got)} frames, not {len(frames)}")
    outside = ~(a > 0)
    per_frame, sq = [], 0.0
    for f0, f1 in zip(frames, got):   # frame by frame: a whole-clip difference would not fit in memory
        d = np.abs(f1[outside].astype(np.int16) - f0[outside].astype(np.int16))
        per_frame.append(float(d.mean()))
        sq += float((d.astype(np.float64) ** 2).mean())
    mse = sq / len(frames)
    inside = np.asarray(hard)
    temporal = float(got[:, inside].astype(np.float32).std(axis=0).mean())   # flicker inside the mask
    temporal_src_ring = float(frames[:, rg].astype(np.float32).std(axis=0).mean())
    review_dir.mkdir(parents=True, exist_ok=True)
    stem = out.stem
    cv2.imwrite(str(review_dir / f"{stem}.mask.png"), np.rint(a * 255).astype(np.uint8))
    x0, y0, x1, y1 = item["mask"]["box"]
    pad = 60
    cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
    cx1, cy1 = min(info["width"], x1 + pad), min(info["height"], y1 + pad)
    mid = len(frames) // 2
    for name, img in (("before", frames[mid]), ("after", got[mid])):
        crop = cv2.cvtColor(img[cy0:cy1, cx0:cx1], cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(review_dir / f"{stem}.{name}.png"),
                    cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST))
    ys, xs = np.nonzero(hard)
    return {"frames": len(frames), "fps": info["fps"], "size": [info["width"], info["height"]], "mode": mode,
            "mask_pixels": int(hard.sum()), "mask_bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
            "ring_deviation_max": round(float(dev.max()), 3),
            "outside_mask": {"mean_abs_diff": round(sum(per_frame) / len(per_frame), 4),
                             "max_frame_mean_abs_diff": round(max(per_frame), 4),
                             "psnr_db": round(10 * math.log10(255 ** 2 / mse), 2) if mse > 0 else None},
            "inside_mask_temporal_std": round(temporal, 3), "ring_temporal_std_source": round(temporal_src_ring, 3),
            "encode": {"codec": "libx264", "crf": CRF, "preset": "slow", "pix_fmt": "yuv420p"},
            "audio_copied": info["audio"]}
