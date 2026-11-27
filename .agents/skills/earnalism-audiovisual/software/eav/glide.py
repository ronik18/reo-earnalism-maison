"""Layered 2.5D depth glide: a still becomes a 1920x1080 camera move.

Two layers split by Otsu on the depth map. The far layer has the near region inpainted (Telea) so a
near object moving over it reveals painted background, never a stretch. The depth map is refined
with a guided filter keyed to the still, so layer edges follow the picture. The near layer moves
`near_gain` times the far layer (parallax). Moves are zoom (dolly) plus pan_x / pan_y in px at 1080p,
eased with smootherstep. `zoom0` starts the glide at a given scale so it matches the frame it
continues from; `sweep` adds a band of light, `drain` goes from warm to cold grey. Needs numpy,
opencv and ffmpeg; frames stream to ffmpeg (libx264 crf 15, yuv420p).
"""
import subprocess
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover - reported by render()
    cv2 = None

W, H = 1920, 1080
EASES = ("both", "in", "out", "none")
SWEEPS = ("down-left", "down-right")
SWEEP_GAIN = 0.14
SWEEP_TINT = np.array([0.97, 1.0, 1.03])
DRAIN_WARM = np.array([0.86, 0.98, 1.16])
DRAIN_COLD = np.array([1.06, 1.0, 0.94])


def guided(I, p, r=16, eps=1e-3):
    mean = lambda x: cv2.boxFilter(x, -1, (r, r))
    mI, mp = mean(I), mean(p)
    a = (mean(I * p) - mI * mp) / (mean(I * I) - mI * mI + eps)
    b = mp - a * mI
    return mean(a) * I + mean(b)


def cover(img, w, h, interp=cv2.INTER_LANCZOS4 if cv2 else None):
    sh, sw = img.shape[:2]
    s = max(w / sw, h / sh)
    r = cv2.resize(img, (round(sw * s), round(sh * s)), interpolation=interp)
    y0, x0 = (r.shape[0] - h) // 2, (r.shape[1] - w) // 2
    return r[y0:y0 + h, x0:x0 + w]


def load_depth(path) -> np.ndarray:
    """A 16-bit PNG or an .npy file as float32 in 0..1."""
    if str(path).endswith(".npy"):
        d = np.load(path).astype(np.float32)
        return np.clip(d, 0.0, 1.0)
    raw = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if raw is None:
        raise ValueError(f"cannot read depth map {path}")
    if raw.ndim == 3:
        raw = raw[..., 0]
    return raw.astype(np.float32) / (65535.0 if raw.dtype == np.uint16 else 255.0)


def smoother(t):
    return t * t * t * (t * (6 * t - 15) + 10)


def _ease(ease, t):
    if ease == "both":
        return smoother(t)
    if ease == "in":    # start from rest, leave moving (motion carries into the next dissolve)
        return 2 * smoother(t / 2)
    if ease == "out":   # arrive moving, settle at the end
        return 2 * smoother(0.5 + t / 2) - 1
    return t


def overscan(pan_x: float, pan_y: float, near_gain: float = 1.2) -> float:
    """Base scale so the largest layer shift never exposes an edge (pans need more)."""
    return 1.03 + max(2 * abs(pan_x) * near_gain / W, 2 * abs(pan_y) * near_gain / H)


def warp_maps(xx, yy, z, dx, dy):
    """Source sampling coordinates (map_x, map_y) of a layer scaled by z about the centre and shifted."""
    return (xx - W / 2) / z + W / 2 - dx, (yy - H / 2) / z + H / 2 - dy


def sample_extent(e: float, *, zoom: float = 0.12, pan_x: float = 0.0, pan_y: float = 0.0,
                  near_gain: float = 1.2, zoom0: float = 1.0, base: float | None = None) -> dict:
    """Min/max source coordinates the far and near layers sample at eased progress e (0..1)."""
    base = overscan(pan_x, pan_y, near_gain) if base is None else base
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    out = {}
    for name, gain in (("far", 1.0), ("near", near_gain)):
        mx, my = warp_maps(xx, yy, base * zoom0 * (1 + zoom * gain * e), pan_x * gain * e, pan_y * gain * e)
        out[name] = (float(mx.min()), float(mx.max()), float(my.min()), float(my.max()))
    return out


def render(image: Path, depth: Path | None, out: Path, seconds: float, *, zoom: float = 0.12,
           pan_x: float = 0.0, pan_y: float = 0.0, near_gain: float = 1.2, zoom0: float = 1.0,
           ease: str = "both", flat: bool = False, sweep: str | None = None, drain: bool = False,
           fps: int = 24) -> dict:
    if cv2 is None:
        raise ValueError("glide needs OpenCV: pip install opencv-python-headless numpy")
    if ease not in EASES:
        raise ValueError(f"ease must be one of {', '.join(EASES)}, not {ease!r}")
    if sweep is not None and sweep not in SWEEPS:
        raise ValueError(f"sweep must be one of {', '.join(SWEEPS)} or none, not {sweep!r}")
    if depth is None and not flat:
        raise ValueError("a depth map is required unless flat is set")
    src = cv2.imread(str(image))
    if src is None:
        raise ValueError(f"cannot read image {image}")
    img = cover(src, W, H)
    d = np.full((H, W), 0.5, np.float32) if flat else cover(load_depth(depth), W, H, cv2.INTER_CUBIC)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255
    d = np.clip(guided(gray, d), 0, 1)
    thr, _ = cv2.threshold((d * 255).astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    near = np.zeros((H, W), np.uint8) if flat else (d * 255 >= thr).astype(np.uint8)
    near = cv2.morphologyEx(near, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    # alpha with a soft 3-px edge; background with the near region inpainted (grown a little)
    alpha = cv2.GaussianBlur(near.astype(np.float32), (0, 0), 1.5)[..., None]
    grow = cv2.dilate(near, np.ones((13, 13), np.uint8))
    small = cv2.resize(img, (W // 2, H // 2), interpolation=cv2.INTER_AREA)
    msk = cv2.resize(grow * 255, (W // 2, H // 2), interpolation=cv2.INTER_NEAREST)
    bg_fill = cv2.resize(cv2.inpaint(small, msk, 7, cv2.INPAINT_TELEA), (W, H), interpolation=cv2.INTER_CUBIC)
    bg = np.where(grow[..., None] > 0, bg_fill, img)
    n = int(round(seconds * fps))
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    # overscan: enough that the largest layer shift never exposes an edge (pans need more)
    base = overscan(pan_x, pan_y, near_gain)
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
                          "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "15",
                          "-pix_fmt", "yuv420p", "-r", str(fps), str(out)], stdin=subprocess.PIPE)

    def warp(s, z, dx, dy, border):
        mx, my = warp_maps(xx, yy, z, dx, dy)
        return cv2.remap(s, mx, my, cv2.INTER_CUBIC, borderMode=border)

    try:
        for i in range(n):
            t = i / max(1, n - 1)
            e = _ease(ease, t)
            zb = base * zoom0 * (1 + zoom * e)
            zn = base * zoom0 * (1 + zoom * near_gain * e)
            far = warp(bg, zb, pan_x * e, pan_y * e, cv2.BORDER_REFLECT)
            nr = warp(img, zn, pan_x * near_gain * e, pan_y * near_gain * e, cv2.BORDER_REFLECT)
            a = warp(alpha, zn, pan_x * near_gain * e, pan_y * near_gain * e, cv2.BORDER_CONSTANT)[..., None]
            frame = far.astype(np.float32) * (1 - a) + nr.astype(np.float32) * a
            if sweep:  # a soft band of warm sunlight sliding along the painted rays
                u = (((W - xx) * 0.5 + yy) if sweep == "down-left" else (xx * 0.5 + yy)) / (W * 0.5 + H)
                band = np.exp(-(u - (e * 1.2 - 0.1)) ** 2 / 0.03)
                frame *= (1 + SWEEP_GAIN * band)[..., None] * SWEEP_TINT[None, None, :] ** band[..., None]
            if drain:  # starts warm (matching the room before) and drains to cold grey across the shot
                k = smoother(t)
                warm = frame * DRAIN_WARM[None, None, :]
                g = cv2.cvtColor(np.clip(frame, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY)[..., None]
                cold = g.astype(np.float32) * DRAIN_COLD[None, None, :] * 0.9
                frame = warm * (1 - k) + cold * k
            p.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
    finally:
        p.stdin.close()
        rc = p.wait()
    if rc:
        raise ValueError(f"ffmpeg failed encoding {out} (exit {rc})")
    return {"frames": n, "base_overscan": base}
