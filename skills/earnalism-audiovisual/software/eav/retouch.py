"""Deterministic local retouch of small defects in a still (numpy + Pillow only, $0).

The masked pixels are filled by harmonic (Laplace) inpainting from the boundary (red-black SOR
until converged or a fixed iteration cap), then given matched texture: high-pass residuals
sampled from a ring of untouched pixels around the mask, with a generator seeded from the
source still's sha256. The mask edge is feathered over FEATHER_PX pixels; every pixel beyond
the mask plus the feather band is copied byte for byte.
"""
import re

import numpy as np
from PIL import Image

METHOD = "harmonic-sor+ring-texture+feather"
METHOD_VERSION = 1
FEATHER_PX = 3          # alpha 0.75, 0.5, 0.25 on the three pixel rings outside the mask
RING_PX = 6             # width of the texture ring
BLUR_R = 2              # high-pass = image - (2*BLUR_R+1)^2 box blur
TOLERANCE = 0.01        # converged when no pixel moves more than this (0-255 units)
MAX_ITER = 6000
MAX_REGION_FRAC = 0.03
MAX_TOTAL_FRAC = 0.06
SHAPES = ("ellipse", "rect")
_REGION = re.compile(r"^\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?::\s*([a-z]+)\s*)?$")


def parse_region(text: str) -> dict:
    """'x,y,w,h[:ellipse|rect]' in the still's own pixels."""
    m = _REGION.match(text or "")
    if not m:
        raise ValueError(f"region {text!r}: write x,y,w,h[:ellipse|rect] in whole pixels")
    x, y, w, h = (int(v) for v in m.groups()[:4])
    shape = m.group(5) or "ellipse"
    if shape not in SHAPES:
        raise ValueError(f"region {text!r}: shape must be ellipse or rect")
    if w <= 0 or h <= 0:
        raise ValueError(f"region {text!r}: width and height must be positive")
    return {"x": x, "y": y, "w": w, "h": h, "shape": shape}


def region_mask(region: dict, size) -> np.ndarray:
    W, H = size
    m = np.zeros((H, W), dtype=bool)
    x, y, w, h = region["x"], region["y"], region["w"], region["h"]
    if region["shape"] == "rect":
        m[y:y + h, x:x + w] = True
        return m
    yy, xx = np.mgrid[y:y + h, x:x + w]
    cx, cy = x + w / 2.0, y + h / 2.0
    inside = ((xx + 0.5 - cx) / (w / 2.0)) ** 2 + ((yy + 0.5 - cy) / (h / 2.0)) ** 2 <= 1.0
    m[y:y + h, x:x + w] = inside
    return m


def check_regions(regions: list, size) -> list:
    """Refuse a region outside the image, one over 3 % of its area, or a sum over 6 %.
    Returns the per-region masked pixel counts."""
    W, H = size
    if not regions:
        raise ValueError("give at least one --region")
    area, counts = W * H, []
    for r in regions:
        if r["x"] < 0 or r["y"] < 0 or r["x"] + r["w"] > W or r["y"] + r["h"] > H:
            raise ValueError(f"region {r['x']},{r['y']},{r['w']},{r['h']} lies outside the "
                             f"{W}x{H} image")
        n = int(region_mask(r, size).sum())
        if n == 0:
            raise ValueError(f"region {r['x']},{r['y']},{r['w']},{r['h']} masks no pixel")
        if n > MAX_REGION_FRAC * area:
            raise ValueError(f"region {r['x']},{r['y']},{r['w']},{r['h']}:{r['shape']} covers "
                             f"{100 * n / area:.2f}% of the image; retouch is for small defects "
                             f"only (at most {100 * MAX_REGION_FRAC:g}% per region)")
        counts.append(n)
    if sum(counts) > MAX_TOTAL_FRAC * area:
        raise ValueError(f"the regions cover {100 * sum(counts) / area:.2f}% of the image together; "
                         f"retouch is for small defects only (at most {100 * MAX_TOTAL_FRAC:g}% in all)")
    return counts


def _dilate(m: np.ndarray, steps: int) -> np.ndarray:
    """Binary dilation by a 3x3 square, `steps` times."""
    out = m.copy()
    for _ in range(steps):
        p = np.pad(out, 1)
        out = (p[:-2, :-2] | p[:-2, 1:-1] | p[:-2, 2:] | p[1:-1, :-2] | p[1:-1, 1:-1]
               | p[1:-1, 2:] | p[2:, :-2] | p[2:, 1:-1] | p[2:, 2:])
    return out


def _box_blur(a: np.ndarray, r: int) -> np.ndarray:
    """Mean over a (2r+1)^2 window, edges replicated; a is HxWxC."""
    p = np.pad(a, ((r, r), (r, r), (0, 0)), mode="edge")
    c = np.cumsum(np.cumsum(p, axis=0), axis=1)
    c = np.pad(c, ((1, 0), (1, 0), (0, 0)))
    k = 2 * r + 1
    s = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return s / (k * k)


def _harmonic(u: np.ndarray, m: np.ndarray):
    """Solve Laplace's equation for u on mask m (never on the array border), boundary fixed.
    Red-black SOR; returns (iterations, converged)."""
    h, w = m.shape
    ys, xs = np.nonzero(m)
    n = max(ys.max() - ys.min() + 1, xs.max() - xs.min() + 1)
    omega = 2.0 / (1.0 + np.sin(np.pi / (n + 2)))
    yy, xx = np.mgrid[0:h, 0:w]
    inner = m[1:-1, 1:-1]
    colours = [inner & ((yy + xx)[1:-1, 1:-1] % 2 == p) for p in (0, 1)]
    for it in range(1, MAX_ITER + 1):
        biggest = 0.0
        for sel in colours:
            if not sel.any():
                continue
            nb = (u[:-2, 1:-1] + u[2:, 1:-1] + u[1:-1, :-2] + u[1:-1, 2:]) * 0.25
            core = u[1:-1, 1:-1]
            d = nb[sel] - core[sel]
            core[sel] += omega * d
            biggest = max(biggest, float(np.abs(d).max()))
        if biggest < TOLERANCE:
            return it, True
    return MAX_ITER, False


def seed_from_sha(sha256: str) -> int:
    return int(sha256[:16], 16)


def retouch(img: Image.Image, regions: list, seed: int):
    """(retouched image, method record). The image keeps its mode (L, LA, RGB or RGBA; any
    other mode is converted to RGB first)."""
    if img.mode not in ("L", "LA", "RGB", "RGBA"):
        img = img.convert("RGB")
    W, H = img.size
    check_regions(regions, (W, H))
    src = np.asarray(img)
    if src.ndim == 2:
        src = src[:, :, None]
    mask = np.zeros((H, W), dtype=bool)
    for r in regions:
        mask |= region_mask(r, (W, H))
    # work on a crop around the mask: feather + blur + ring + a border for the solver
    margin = FEATHER_PX + RING_PX + BLUR_R + 2
    ys, xs = np.nonzero(mask)
    y0, y1 = max(0, ys.min() - margin), min(H, ys.max() + margin + 1)
    x0, x1 = max(0, xs.min() - margin), min(W, xs.max() + margin + 1)
    orig = src[y0:y1, x0:x1].astype(np.float64)
    m = mask[y0:y1, x0:x1]
    # the fill covers the mask and its feather band; alpha falls 1 -> 0 across the band
    bands = [m]
    for _ in range(FEATHER_PX):
        bands.append(_dilate(bands[-1], 1))
    fill_m = bands[-1].copy()
    alpha = np.zeros(m.shape)
    alpha[m] = 1.0
    for d in range(1, FEATHER_PX + 1):
        alpha[bands[d] & ~bands[d - 1]] = 1.0 - d / (FEATHER_PX + 1)
    # a fill pixel on the crop border (mask touching the image edge) cannot be solved there:
    # pad by replicating the edge so the solver always has a fixed boundary
    u = np.pad(orig, ((1, 1), (1, 1), (0, 0)), mode="edge")
    fm = np.pad(fill_m, 1)
    clean = _dilate(fill_m, BLUR_R)  # pixels whose blur window would see the defect
    ring = _dilate(fill_m, BLUR_R + RING_PX) & ~clean
    if not ring.any():
        raise ValueError("no untouched pixels around the regions to take texture from")
    ring_mean = orig[ring].mean(axis=0)
    u[fm] = ring_mean
    iters, converged = _harmonic(u, fm)
    smooth = u[1:-1, 1:-1]
    residual = (orig - _box_blur(orig, BLUR_R))[ring]
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, residual.shape[0], size=int(fill_m.sum()))
    filled = smooth.copy()
    filled[fill_m] += residual[picks]
    a = alpha[:, :, None]
    out_crop = np.where(fill_m[:, :, None], a * filled + (1.0 - a) * orig, orig)
    out = src.copy()
    patch = np.clip(np.rint(out_crop), 0, 255).astype(np.uint8)
    keep = ~fill_m  # untouched pixels are copied, never round-tripped
    patch[keep] = src[y0:y1, x0:x1][keep]
    out[y0:y1, x0:x1] = patch
    if out.shape[2] == 1:
        out = out[:, :, 0]
    result = Image.fromarray(out, mode=img.mode)
    method = {"name": METHOD, "version": METHOD_VERSION, "iterations": iters,
              "converged": converged, "max_iterations": MAX_ITER, "tolerance": TOLERANCE,
              "feather_px": FEATHER_PX, "ring_px": RING_PX, "highpass_box_radius": BLUR_R,
              "noise_seed": seed, "noise": "ring high-pass residuals, sampled with numpy "
              "default_rng(noise_seed)", "mode": img.mode,
              "masked_pixels": int(m.sum()), "changed_pixels_max": int(fill_m.sum())}
    return result, method


def changed_mask(regions: list, size):
    """The only pixels a retouch may change: the mask plus its feather band."""
    W, H = size
    mask = np.zeros((H, W), dtype=bool)
    for r in regions:
        mask |= region_mask(r, size)
    return _dilate(mask, FEATHER_PX)
