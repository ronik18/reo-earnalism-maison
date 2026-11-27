"""Layered depth glide: frame count, overscan, easing, flat mode, drain."""
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np
import pytest

from eav import glide

W, H = 1920, 1080


@pytest.fixture(scope="module")
def still(tmp_path_factory):
    d = tmp_path_factory.mktemp("glide")
    xs = np.linspace(0, 255, 1344, dtype=np.float32)[None, :].repeat(768, 0)
    ys = np.linspace(255, 0, 768, dtype=np.float32)[:, None].repeat(1344, 1)
    img = np.stack([xs, ys, (xs + ys) / 2], -1).astype(np.uint8)
    cv2.circle(img, (672, 384), 150, (40, 60, 220), -1)
    img = cv2.GaussianBlur(img, (0, 0), 4)  # soft detail keeps the x264 loss small for the PSNR check
    cv2.imwrite(str(d / "still.png"), img)
    ramp = np.linspace(0, 1, 1344, dtype=np.float32)[None, :].repeat(768, 0)
    cv2.imwrite(str(d / "depth.png"), (ramp * 65535).astype(np.uint16))
    np.save(d / "depth.npy", ramp)
    return d


def frames(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)


def mad(a, b):
    return float(np.abs(a.astype(np.float32) - b.astype(np.float32)).mean())


def run(still, name, **kw):
    out = still / f"{name}.mp4"
    res = glide.render(still / "still.png", still / "depth.png", out, 1.0, **kw)
    return res, out


def test_frame_count_matches_seconds_at_24fps(still):
    res, out = run(still, "count")
    assert res["frames"] == 24
    probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                            "-show_entries", "stream=nb_read_frames,r_frame_rate", "-of", "json", str(out)],
                           check=True, capture_output=True, text=True).stdout
    s = json.loads(probe)["streams"][0]
    assert int(s["nb_read_frames"]) == 24 and s["r_frame_rate"] == "24/1"


def inside(ext):
    return all(x0 >= 0 and x1 <= W - 1 and y0 >= 0 and y1 <= H - 1 for x0, x1, y0, y1 in ext.values())


def test_pan_never_samples_outside_source():
    """Codec-independent: the warp maps at full progress stay inside the source, with a negative control."""
    res = glide.overscan(300, 0)
    assert res >= 1.03 + 2 * 300 * 1.2 / 1920
    for e in (0.0, 0.5, 1.0):
        assert inside(glide.sample_extent(e, pan_x=300)), e
        assert inside(glide.sample_extent(e, pan_x=-300, pan_y=100))
    assert not inside(glide.sample_extent(1.0, pan_x=300, base=1.03))  # too little overscan reaches outside


def test_render_reports_the_overscan_it_uses(still):
    res, _ = run(still, "pan", pan_x=300)
    assert res["base_overscan"] == glide.overscan(300, 0)


def test_ease_out_ends_at_rest(still):
    _, out = run(still, "out", ease="out", pan_x=60)
    f = frames(out)
    assert mad(f[-1], f[-2]) < 0.25 * mad(f[10], f[11])


def test_ease_in_leaves_moving(still):
    _, out = run(still, "in", ease="in", pan_x=60)
    f = frames(out)
    assert mad(f[-1], f[-2]) > 0.5 * mad(f[10], f[11])


def test_flat_mode_has_no_parallax(still):
    _, out = run(still, "flat", flat=True, zoom=0.12)
    last = frames(out)[-1]
    img = glide.cover(cv2.imread(str(still / "still.png")), W, H)
    z = 1.03 * 1.12
    M = np.float32([[z, 0, W / 2 - z * W / 2], [0, z, H / 2 - z * H / 2]])
    ref = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    mse = float(((last.astype(np.float32) - ref.astype(np.float32)) ** 2).mean())
    assert 10 * np.log10(255 ** 2 / max(mse, 1e-9)) > 40


def test_drain_ends_greyer(still):
    _, out = run(still, "drain", drain=True)
    f = frames(out)

    def sat(x):
        return float(cv2.cvtColor(x, cv2.COLOR_BGR2HSV)[..., 1].mean())
    assert sat(f[-1]) < 0.5 * sat(f[0])


def test_sweep_and_npy_depth(still):
    out = still / "sweep.mp4"
    res = glide.render(still / "still.png", still / "depth.npy", out, 0.5, sweep="down-right")
    assert res["frames"] == 12
    assert glide.load_depth(still / "depth.npy").dtype == np.float32
    d = glide.load_depth(still / "depth.png")
    assert d.dtype == np.float32 and 0 <= d.min() and d.max() <= 1
    with pytest.raises(ValueError):
        glide.render(still / "still.png", still / "depth.png", out, 1.0, ease="bogus")


def test_cli_glide_runs_without_a_record(still):
    from eav import cli
    out = still / "cli.mp4"
    assert cli.main(["glide", str(still / "still.png"), "-", str(out), "--seconds", "0.25", "--flat"]) == 0
    assert frames(out).shape[0] == 6
    assert cli.main(["glide", str(still / "still.png"), str(still / "depth.png"), str(out),
                     "--seconds", "0.25", "--ease", "out", "--sweep", "down-left"]) == 0
    assert cli.main(["glide", str(still / "missing.png"), "-", str(out), "--seconds", "1"]) == 2
