"""Original synthesized sounds for scene 14 v4 (numpy only; no recording used). Dedicated to CC0 1.0.
  synth_sfx.py <out_dir> <broom_times_json>
wheels.wav   wooden cart wheels on a rutted lane: low rumble, irregular knocks, occasional axle creak (60 s)
breeze.wav   soft dawn breeze: slowly swelling filtered noise (60 s)
broom.wav    straw-broom strokes on packed earth, placed on the measured stroke times of the sweeping take
murmur.wav   distant crowd murmur: 9 formant-filtered synthetic voices with syllabic envelopes (14 s)
"""
import json, sys
from pathlib import Path
import numpy as np

SR = 48000
rng = np.random.default_rng(1414)


def fft_filter(x, lo=None, hi=None, tilt=0.0):
    n = len(x)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1 / SR)
    g = np.ones_like(f)
    if lo:
        g *= 1 / np.sqrt(1 + (lo / np.maximum(f, 1e-3)) ** 4)
    if hi:
        g *= 1 / np.sqrt(1 + (f / hi) ** 4)
    if tilt:
        g *= (np.maximum(f, 20) / 1000.0) ** tilt
    return np.fft.irfft(X * g, n)


def norm(x, db):
    return x * (10 ** (db / 20)) / (np.sqrt(np.mean(x ** 2)) + 1e-12)


def stereo(l, r=None):
    return np.stack([l, l if r is None else r], 1).astype(np.float32)


def write(path, y):
    import subprocess
    y = np.clip(y, -0.99, 0.99).astype(np.float32)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                    "-c:a", "pcm_s24le", str(path)], input=y.tobytes(), check=True)


def env_smooth(n, rate_hz, depth, seed):
    r = np.random.default_rng(seed)
    k = max(2, int(n / SR * rate_hz) + 2)
    pts = r.uniform(-1, 1, k)
    e = np.interp(np.linspace(0, k - 1, n), np.arange(k), pts)
    return 1 + depth * e


def decay(n, t_attack, t_decay):
    t = np.arange(n) / SR
    return (1 - np.exp(-t / max(t_attack, 1e-4))) * np.exp(-t / t_decay)


def wheels(sec=60.0):
    n = int(sec * SR)
    rumble = fft_filter(rng.standard_normal(n), lo=35, hi=180)
    rumble *= env_smooth(n, 0.7, 0.35, 3)
    rumble = norm(rumble, -30)
    knocks = np.zeros(n)
    t = 0.3
    while t < sec - 0.5:
        a = int(t * SR)
        m = int(0.12 * SR)
        k = fft_filter(rng.standard_normal(m), lo=180, hi=900) * decay(m, 0.002, 0.025)
        knocks[a:a + m] += k * rng.uniform(0.5, 1.0)
        t += rng.normal(0.62, 0.08)          # one rut every ~0.6 s at a walking horse's pace
    knocks = norm(knocks, -33)
    creak = np.zeros(n)
    t = 2.0
    while t < sec - 2:
        a, m = int(t * SR), int(rng.uniform(0.25, 0.5) * SR)
        f0 = rng.uniform(380, 620)
        ph = 2 * np.pi * np.cumsum(f0 * (1 + 0.06 * np.sin(np.linspace(0, 3, m))) / SR)
        sig = (np.sin(ph) + 0.4 * np.sin(2 * ph) + 0.2 * np.sin(3 * ph)) * np.hanning(m)
        sig *= 1 + 0.5 * np.sign(np.sin(2 * np.pi * 37 * np.arange(m) / SR))   # stick-slip grain
        creak[a:a + m] += sig
        t += rng.uniform(3.5, 7.0)
    creak = norm(fft_filter(creak, lo=300, hi=2500), -44)
    m = rumble + knocks + creak
    l = m + 0.02 * fft_filter(rng.standard_normal(n), lo=40, hi=150)
    r = np.roll(m, int(0.0007 * SR))
    return stereo(l, r)


def breeze(sec=60.0):
    n = int(sec * SR)
    out = []
    for ch in range(2):
        x = fft_filter(rng.standard_normal(n), lo=90, hi=900, tilt=-0.5)
        x *= np.clip(env_smooth(n, 0.18, 0.55, 10 + ch), 0.2, None)
        out.append(norm(x, -30))
    return stereo(*out)


def broom(times, sec):
    n = int(sec * SR)
    y = np.zeros((n, 2))
    for t in times:
        m = int(rng.uniform(0.32, 0.45) * SR)
        sw = fft_filter(rng.standard_normal(m), lo=1800, hi=7500)
        grit = fft_filter(rng.standard_normal(m), lo=300, hi=1500) * (rng.random(m) < 0.02)
        shape = np.sin(np.linspace(0, np.pi, m)) ** 1.5 * np.linspace(1.0, 0.6, m)
        s = (sw + 0.6 * grit) * shape
        a = int(t * SR)
        b = min(n, a + m)
        pan = rng.uniform(0.35, 0.55)
        y[a:b, 0] += s[:b - a] * (1 - pan)
        y[a:b, 1] += s[:b - a] * pan
    return (y * 10 ** (-20 / 20) / (np.sqrt(np.mean(y[np.abs(y).sum(1) > 0] ** 2)) + 1e-12)).astype(np.float32)


VOWELS = {"a": (750, 1250, 2600), "e": (480, 1900, 2600), "i": (320, 2300, 3000), "o": (500, 900, 2500), "u": (350, 800, 2300)}


def voice(sec, seed):
    r = np.random.default_rng(seed)
    n = int(sec * SR)
    f0 = r.uniform(105, 230) * env_smooth(n, 2.0, 0.08, seed + 1)
    ph = 2 * np.pi * np.cumsum(f0 / SR)
    src = np.zeros(n)
    for h in range(1, 28):
        src += np.sin(h * ph) / h * (h * f0 < 4500)
    src += 0.05 * r.standard_normal(n)
    # syllables ~4.5 Hz grouped in phrases with pauses
    amp = np.zeros(n)
    t = r.uniform(0, 1.0)
    while t < sec:
        phrase = r.uniform(0.8, 2.4)
        end = min(sec, t + phrase)
        while t < end:
            d = r.uniform(0.13, 0.28)
            a, b = int(t * SR), min(n, int((t + d) * SR))
            amp[a:b] = np.sin(np.linspace(0, np.pi, b - a)) * r.uniform(0.5, 1.0)
            t += d
        t += r.uniform(0.3, 1.2)
    # time-varying formants via STFT
    hop, win = 512, 2048
    w = np.hanning(win)
    pad = np.pad(src, (win, win))
    out = np.zeros(len(pad))
    norm_w = np.zeros(len(pad))
    f = np.fft.rfftfreq(win, 1 / SR)
    keys = list(VOWELS)
    vseq = [VOWELS[keys[r.integers(len(keys))]] for _ in range(int(sec * 5) + 4)]
    for k, s in enumerate(range(0, len(pad) - win, hop)):
        tt = (s - win) / SR
        i = max(0, int(tt * 4.5))
        v = np.array(vseq[min(i, len(vseq) - 1)])
        g = sum(np.exp(-0.5 * ((f - F) / (60 + 0.08 * F)) ** 2) * (1.0, 0.6, 0.3)[j] for j, F in enumerate(v))
        X = np.fft.rfft(pad[s:s + win] * w) * (g + 0.02)
        out[s:s + win] += np.fft.irfft(X, win) * w
        norm_w[s:s + win] += w ** 2
    y = (out / np.maximum(norm_w, 1e-3))[win:win + n]
    return y * amp


def murmur(sec=14.0):
    n = int(sec * SR)
    L, R = np.zeros(n), np.zeros(n)
    for k in range(9):
        v = voice(sec, 500 + k)
        v = fft_filter(v, lo=150, hi=2200)          # distance
        pan = (k + 0.5) / 9
        g = 10 ** (rng.uniform(-6, 0) / 20)
        L += v * g * (1 - pan)
        R += v * g * pan
    ir_n = int(0.7 * SR)
    ir = rng.standard_normal(ir_n) * np.exp(-np.arange(ir_n) / SR / 0.18)
    ir[0] = 6.0
    def rev(x):
        return np.fft.irfft(np.fft.rfft(x, n + ir_n) * np.fft.rfft(ir, n + ir_n), n + ir_n)[:n]
    L, R = rev(L), rev(R)
    m = np.stack([L, R], 1)
    return (m * 10 ** (-24 / 20) / (np.sqrt(np.mean(m ** 2)) + 1e-12)).astype(np.float32)


if __name__ == "__main__":
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    times = json.loads(Path(sys.argv[2]).read_text())
    write(out / "wheels.wav", wheels())
    write(out / "breeze.wav", breeze())
    write(out / "broom.wav", broom(times["times"], times["seconds"]))
    write(out / "murmur.wav", murmur())
    print("ok")
