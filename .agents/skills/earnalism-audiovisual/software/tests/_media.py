"""Shared ffmpeg fixture helpers for mix/film tests."""
import subprocess
from pathlib import Path

import numpy as np


def ff(*args):
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


def sine_wav(path: Path, seconds: float, freq=220, amp=0.3, rate=48000):
    ff("-f", "lavfi", "-i", f"aevalsrc={amp}*sin(2*PI*{freq}*t):s={rate}:d={seconds}",
       "-ac", "1", str(path))


def speech_gap_wav(path: Path, total: float, start: float, end: float):
    expr = f"0.3*sin(2*PI*220*t)*between(t\\,{start}\\,{end})"
    ff("-f", "lavfi", "-i", f"aevalsrc={expr}:s=48000:d={total}", "-ac", "1", str(path))


def noise_wav(path: Path, seconds: float):
    ff("-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=pink:r=48000:a=0.3", "-ac", "1", str(path))


def samples(path: Path) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le",
                          "-ac", "1", "-ar", "48000", "-"], check=True,
                         capture_output=True).stdout
    return np.frombuffer(out, dtype=np.float32)


def rms_db(x: np.ndarray) -> float:
    return 20 * np.log10(max(float(np.sqrt(np.mean(x ** 2))), 1e-9))
