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


def test_pan_never_samples_outside_source(still):
    res, out = run(still, "pan", pan_x=300)
    assert res["base_overscan"] >= 1.03 + 2 * 300 * 1.2 / 1920
    last = frames(out)[-1].astype(np.int32)
    for edge in (last, last[:, ::-1]):  # a reflected border band of b px mirrors itself about column b
        for b in range(2, 21):
            assert not np.array_equal(edge[:, :b][:, ::-1], edge[:, b:2 * b])


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
