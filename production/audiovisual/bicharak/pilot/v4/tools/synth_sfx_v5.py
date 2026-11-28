"""Original synthesized sounds for scene 14 v5 (numpy/OpenCV only; no recording used). Dedicated to CC0 1.0.
Sibling of synth_sfx.py (its filter, envelope and writer helpers and its broom() stroke model are reused).

  synth_sfx_v5.py <out_dir> [--sweep <f01s014-13s.mp4>]

hooves.wav      one horse at a trot on a brick lane at night: diagonal hoof pairs (clip-clop flams), slight
                timing/level/timbre variation, lane-wall reflections and a light room tone (6.4 s, shot 1 is
                5.588 s plus half its 0.8 s dissolve)
crows.wav       sparse morning chorus: a few house-crow caws (harmonic source + noise, formant-filtered, band
                limited to about 450-2600 Hz) and small soft chirps, distant (14.5 s, shots 9-10)
broom-13s.wav   straw-broom strokes re-timed to the 13s sweeping take (door re-take r3): stroke times are the
                peaks of the take's frame difference in the broom-pole region, measured here with OpenCV
                (written beside it as broom-13s.times.json); 9.6 s (shot 10 is 9.52 s; 13t has no strokes)
"""
import hashlib, json, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import synth_sfx as base  # noqa: E402  (fft_filter, norm, stereo, write, env_smooth, decay, broom)

SR = base.SR
fft_filter, decay, write = base.fft_filter, base.decay, base.write


def _conv(x, ir):
    n = len(x) + len(ir) - 1
    m = 1 << (n - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(x, m) * np.fft.rfft(ir, m), m)[:len(x)]


def _room_ir(rng, sec, rt, early):
    """A short room: early reflections [(delay_s, gain)] plus a diffuse exponential tail of RT60 `rt`."""
    n = int(sec * SR)
    ir = np.zeros(n)
    ir[0] = 1.0
    for d, g in early:
        ir[int(d * SR)] += g * rng.choice([-1, 1])
    t = np.arange(n) / SR
    tail = rng.standard_normal(n) * np.exp(-6.91 * t / rt) * (t > 0.03)
    ir += 0.06 * fft_filter(tail, lo=150, hi=3500)
    return ir


# ---------------------------------------------------------------- hooves
def hoof_hit(rng, bright):
    """One shod hoof on brick: a shoe click, a hard knock with brick/hoof modes, and a small body thump."""
    m = int(0.12 * SR)
    t = np.arange(m) / SR
    click = fft_filter(rng.standard_normal(m), lo=2200, hi=6000) * decay(m, 0.0003, 0.004)
    knock = fft_filter(rng.standard_normal(m), lo=500, hi=2400) * decay(m, 0.0006, 0.016 * rng.uniform(0.8, 1.25))
    modes = np.zeros(m)
    for _ in range(3):
        f = rng.uniform(650, 1700) * bright
        modes += np.sin(2 * np.pi * f * t + rng.uniform(0, 6.28)) * np.exp(-t / rng.uniform(0.010, 0.022))
    thump = np.sin(2 * np.pi * rng.uniform(120, 190) * t) * decay(m, 0.002, 0.035)
    y = 0.55 * click * bright + 1.0 * knock + 0.45 * modes + 0.6 * thump
    return y / (np.max(np.abs(y)) + 1e-12)


def hooves(sec=6.4, seed=2814):
    rng = np.random.default_rng(seed)
    n = int(sec * SR)
    dry = np.zeros(n)
    beat = 0.355                                   # two-beat trot, about 2.8 beats/s (1.4 strides/s)
    t, k = rng.uniform(0.08, 0.18), 0
    while t < sec - 0.15:
        accent = 1.0 if k % 2 == 0 else 0.78        # diagonal pairs alternate fore-led and hind-led
        bright = 1.0 if k % 2 == 0 else 0.88
        flam = rng.uniform(0.018, 0.042)           # the two hooves of a pair land a little apart: clip-clop
        for j, (dt, g) in enumerate(((0.0, 1.0), (flam, rng.uniform(0.55, 0.8)))):
            h = hoof_hit(rng, bright * rng.uniform(0.93, 1.07))
            a = int((t + dt) * SR)
            b = min(n, a + len(h))
            dry[a:b] += h[:b - a] * g * accent * 10 ** (rng.normal(0, 1.2) / 20)
        k += 1
        t += beat * (1 + rng.normal(0, 0.025)) * (1 + 0.03 * np.sin(2 * np.pi * t / 4.0))
    swell = np.interp(np.arange(n) / SR, [0, 2.5, sec], [10 ** (-5 / 20), 1.0, 10 ** (-1.5 / 20)])
    dry *= swell                                   # the carriage draws a little closer through the shot
    ir_l = _room_ir(rng, 0.6, 0.45, [(0.011, 0.30), (0.024, 0.20), (0.039, 0.12), (0.061, 0.07)])
    ir_r = _room_ir(rng, 0.6, 0.45, [(0.014, 0.28), (0.028, 0.18), (0.044, 0.11), (0.067, 0.06)])
    dry = fft_filter(dry, lo=90, hi=7000)           # a lane at night, a few metres off: no sharp top
    L, R = _conv(dry, ir_l), _conv(np.roll(dry, int(0.0004 * SR)), ir_r)
    room = [fft_filter(rng.standard_normal(n), lo=40, hi=380, tilt=-0.4) for _ in range(2)]
    room = [r * base.env_smooth(n, 0.3, 0.2, 77 + i) for i, r in enumerate(room)]
    lvl = np.sqrt(np.mean(L ** 2))
    L += base.norm(room[0], 20 * np.log10(lvl) - 24)  # light room tone, 24 dB under the trot
    R += base.norm(room[1], 20 * np.log10(lvl) - 24)
    y = np.stack([L, R], 1)
    y *= 10 ** (-3 / 20) / np.max(np.abs(y))
    return y.astype(np.float32)


# ---------------------------------------------------------------- morning birds
def caw(rng, dur, f0):
    """A house-crow caw: harmonic source falling in pitch with jitter, mixed with shaped noise, through three
    formants; band-limited to about 450-2600 Hz so it stays soft (no harsh top)."""
    m = int(dur * SR)
    t = np.arange(m) / SR
    jit = fft_filter(rng.standard_normal(m), hi=60)
    glide = f0 * (1.0 - 0.16 * (t / dur) ** 1.3) * (1 + 0.05 * jit / (np.std(jit) + 1e-9))   # pitch jitter
    ph = 2 * np.pi * np.cumsum(glide / SR)
    src = sum(np.sin(h * ph) / h ** 0.9 * (h * f0 < 3200) for h in range(1, 9))
    src += 0.3 * sum(np.sin((h - 0.5) * ph) / h for h in range(1, 6))   # weak subharmonic: the caw's grain
    shim = fft_filter(rng.standard_normal(m), hi=80)
    src *= (1 + 0.3 * np.sin(2 * np.pi * rng.uniform(28, 38) * t)) * (1 + 0.25 * shim / (np.std(shim) + 1e-9))
    src += 0.9 * fft_filter(rng.standard_normal(m), lo=500, hi=2500) * np.std(src)   # breathy, noisy body
    X = np.fft.rfft(src)
    f = np.fft.rfftfreq(m, 1 / SR)
    F = [rng.uniform(850, 1000), rng.uniform(1400, 1650), rng.uniform(2050, 2350)]
    g = sum(a * np.exp(-0.5 * ((f - Fi) / bw) ** 2) for Fi, a, bw in zip(F, (1.0, 0.75, 0.35), (160, 220, 260)))
    y = np.fft.irfft(X * (g + 0.03), m)
    y = fft_filter(y, lo=450, hi=2600)
    env = np.minimum(1, t / 0.025) * np.minimum(1, (dur - t) / 0.07) * (1 - 0.25 * t / dur)
    y = y * np.clip(env, 0, 1)
    return y / (np.max(np.abs(y)) + 1e-12)


def chirp(rng):
    """A small soft songbird chirp: a short frequency sweep with a Hann envelope."""
    d = rng.uniform(0.04, 0.09)
    m = int(d * SR)
    t = np.arange(m) / SR
    f1, f2 = rng.uniform(2600, 4200), rng.uniform(2600, 4200)
    f = f1 + (f2 - f1) * (t / d) ** rng.uniform(0.6, 1.6)
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) + 0.15 * np.sin(4 * np.pi * np.cumsum(f) / SR)
    return y * np.hanning(m)


def crows(sec=14.5, seed=914):
    rng = np.random.default_rng(seed)
    n = int(sec * SR)
    L, R = np.zeros(n), np.zeros(n)
    caws = []

    def put(sig, at, gain, pan):
        a = int(at * SR)
        b = min(n, a + len(sig))
        L[a:b] += sig[:b - a] * gain * np.cos(pan * np.pi / 2)
        R[a:b] += sig[:b - a] * gain * np.sin(pan * np.pi / 2)

    # caw series: (start s, number of caws, crow) -- three crows at different places and distances; the first
    # series falls in the narration's pause after "প্রভাত হইবে," (scene 32.69-33.34 s; this file starts at 30.69 s)
    crowsets = {0: (560, 0.85, 0.30), 1: (500, 0.55, 0.75), 2: (610, 0.35, 0.15)}   # f0, gain, pan
    for at, count, who in ((1.95, 2, 0), (5.6, 3, 1), (8.9, 2, 2), (11.6, 2, 0)):
        f0, gain, pan = crowsets[who]
        t = at
        for _ in range(count):
            d = rng.uniform(0.24, 0.36)
            sig = caw(rng, d, f0 * rng.uniform(0.96, 1.04))
            if who == 2:
                sig = fft_filter(sig, hi=1800)          # the far one is duller
            put(sig, t, gain * rng.uniform(0.85, 1.0), pan)
            caws.append([round(t, 3), round(t + d, 3)])
            t += d + rng.uniform(0.28, 0.45)
    # chirps: sparse little groups across the file, low under the caws
    t = 0.3
    while t < sec - 0.6:
        pan = rng.uniform(0.2, 0.8)
        g = rng.uniform(0.07, 0.13)
        tt = t
        for _ in range(int(rng.integers(2, 5))):
            put(chirp(rng), tt, g, pan)
            tt += rng.uniform(0.08, 0.16)
        t += rng.uniform(0.9, 2.1)
    # outdoor space: a few distant wall reflections and a short diffuse tail
    ir_l = _room_ir(rng, 1.0, 0.7, [(0.07, 0.22), (0.13, 0.12)])
    ir_r = _room_ir(rng, 1.0, 0.7, [(0.08, 0.20), (0.15, 0.10)])
    L, R = _conv(L, ir_l), _conv(R, ir_r)
    L, R = fft_filter(L, lo=300, hi=5500), fft_filter(R, lo=300, hi=5500)
    lvl = 20 * np.log10(np.sqrt(np.mean(L ** 2)) + 1e-12)
    for i, ch in enumerate((L, R)):             # faint open-air bed, so the gaps are never dead silence
        air = fft_filter(rng.standard_normal(n), lo=120, hi=2500, tilt=-0.6) * base.env_smooth(n, 0.25, 0.3, 90 + i)
        ch += base.norm(air, lvl - 30)
    y = np.stack([L, R], 1)
    y *= 10 ** (-3 / 20) / np.max(np.abs(y))
    return y.astype(np.float32), caws


# ---------------------------------------------------------------- broom re-timed to 13s
def stroke_times(clip, fps=24.0):
    """Stroke instants of a sweeping take: per-frame mean absolute difference in the broom-pole region (the lowest
    29 % of the frame, where only the pole swings near the ground), smoothed over 5 frames (the take's periodic keyframe blips sit on single frames),
    then local maxima at least 10 frames apart and above the median: the fastest point of each swing."""
    import cv2
    cap = cv2.VideoCapture(str(clip))
    prev, d = None, []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        h, w = g.shape
        if prev is not None:
            d.append(float(np.abs(g - prev)[int(h * 0.71):, int(w * 0.20):int(w * 0.70)].mean()))
        prev = g
    d = np.array(d)
    med = np.array([np.median(d[max(0, i - 2):i + 3]) for i in range(len(d))])
    sm = np.convolve(med, np.ones(3) / 3, mode="same")
    floor = np.median(sm)
    peaks = []
    for i in range(1, len(sm) - 1):
        if sm[i] >= sm[i - 1] and sm[i] > sm[i + 1] and sm[i] > floor:
            if peaks and i - peaks[-1] < 10:
                if sm[i] > sm[peaks[-1]]:
                    peaks[-1] = i
                continue
            peaks.append(i)
    # diff index i lies between frames i and i+1: its instant is (i + 1) / fps from the clip's first frame
    return [round((i + 1) / fps, 3) for i in peaks], [round(float(x), 3) for x in sm]


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    write(out / "hooves.wav", hooves())
    birds, caw_spans = crows()
    write(out / "crows.wav", birds)
    (out / "crows.caws.json").write_text(json.dumps({"caws_s": caw_spans}, indent=1))
    if "--sweep" in sys.argv:
        clip = Path(sys.argv[sys.argv.index("--sweep") + 1])
        peaks, curve = stroke_times(clip)
        starts = [round(max(0.0, p - 0.18), 3) for p in peaks]   # a stroke's sound peaks mid-stroke (~0.19 s in)
        times = {"times": starts, "seconds": 9.6, "stroke_peaks_s": peaks,
                 "clip": clip.name, "clip_sha256": hashlib.sha256(clip.read_bytes()).hexdigest(),
                 "method": "frame difference in the broom-pole region, 5-frame median + 3-frame mean, maxima >= 10 "
                           "frames apart above the median; sound starts 0.18 s before each peak",
                 "diff_curve": curve}
        (out / "broom-13s.times.json").write_text(json.dumps(times, indent=1))
        base.rng = np.random.default_rng(1314)
        write(out / "broom-13s.wav", base.broom(starts, times["seconds"]))
    print("ok")
