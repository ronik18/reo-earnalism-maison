"""Per-scene music cue and film mix: ACE-Step stems under the narration (numpy + ffmpeg, no extra dependencies).

`pick_stems` chooses the drone / solo / phrase stem of a music job by measurement. `scene_mix` places the
three stems from the scene's cuts, opens 0.4 s of music silence on the dramatic peak, ducks the music under the
re-timed voice with a smooth sidechain, adds the ambience and foley bus, and masters to -16 LUFS / <= -1.5 dBTP.

Generalised cue map (all times are scene seconds of the re-timed narration; `cuts` = shot starts, `peak_at` =
the plan's dramatic peak, `total` = scene length). The spike's scene 14 map c0..c6 becomes:
  drone   fades up from silence at 0 over 4 s, holds to `peak_at` and is cut dead (30 ms) there; after the
          silence it returns 3 dB lower (stem seconds 10.. so it does not restart), fading in 1.6 s and out over 2.5 s.
  solo    the opening phrase over the first two shots: from cuts[0] - 0.5 s to cuts[2] (the third cut; at most
          `peak_at`), 1.5 s in, 2.5 s out, so it settles by the third cut. After the peak the solo resolves from stem
          second 30 at -2 dB under the end fade (1.2 s in, 2.4 s out).
  phrase  the hushed phrase over the stretch before the peak: from the last cut at least 0.5 s before `peak_at` to
          `peak_at`, at -2 dB, 2 s in, cut dead (50 ms) at the peak.
  silence music is exactly zero over [peak_at, peak_at + 0.4]; the window is clipped to `total` (a peak at the
          very end gets a shorter or no window and no return).
Levels: the stems are high-passed at 90 Hz (two cascaded 2-pole ffmpeg stages) and RMS-normalised to
-22 / -19 / -20 dBFS (drone / solo / phrase) for their relative balance; after ducking the whole music bus is scaled
so the in-speech margin is 17 dB whatever the voice level, and scene_mix raises unless it is 16-18 dB, the written
master is one linear gain (so the margin holds) and the true peak is <= -1.5 dBTP. The voice must match `total`
within 50 ms. No fade is applied to voice or ambience (the film's last scene fades, in assembly). Ducking: 80 ms attack, 400 ms hold, 800 ms release. The ambience bus ducks half-depth.
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import mix

SR = 48000
STEM_EXTS = (".wav", ".flac", ".mp3")
STEM_DB = {"drone": -22.0, "solo": -19.0, "phrase": -20.0}
SILENCE_S = 0.4
DUCK_DB = 8.0
MARGIN_DB = 17.0
MARGIN_RANGE = (16.0, 18.0)
TRUE_PEAK_MAX = -1.5
MAX_VOICE_DRIFT_S = 0.05
HIGHPASS = "highpass=f=90:poles=2,highpass=f=90:poles=2"
_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def read(path, start=0.0, dur=None, ch=2, af=None):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-i", str(path)]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    if af:
        cmd += ["-af", af]
    raw = subprocess.run(cmd + ["-ac", str(ch), "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, ch).copy()


def stem_path(stems_dir, key) -> Path:
    for ext in STEM_EXTS:
        p = Path(stems_dir) / (key + ext)
        if p.is_file():
            return p
    raise ValueError(f"stem {key} not found in {stems_dir} (looked for {key}{'|'.join(STEM_EXTS)})")


def db(x):
    return 10 ** (x / 20)


def rms_norm(x, target_db):
    return x * db(target_db) / (np.sqrt(np.mean(x ** 2)) + 1e-9)


def place(bus, clip, at, gain=1.0, fin=1.0, fout=1.0):
    """Add clip at `at` seconds with sin^2 fades; the part before 0 or past the bus end is dropped."""
    a = int(round(at * SR))
    if a < 0:
        clip, a = clip[-a:], 0
    if a >= len(bus) or not len(clip):
        return
    clip = clip[: len(bus) - a].copy()
    for f, side in ((int(fin * SR), 0), (int(fout * SR), 1)):
        f = min(f, len(clip) // 2)
        if f:
            ramp = np.sin(np.linspace(0, np.pi / 2, f)) ** 2
            if side == 0:
                clip[:f] *= ramp[:, None]
            else:
                clip[-f:] *= ramp[::-1][:, None]
    bus[a:a + len(clip)] += gain * clip


def _seg(x, start_s, length_s):
    """length_s of x from start_s, wrapping round the stem when it is shorter than asked."""
    n = max(0, int(round(length_s * SR)))
    return x[(int(start_s * SR) + np.arange(n)) % len(x)]


def _active(voice, hop):
    frames = len(voice) // hop
    lvl = np.sqrt(np.mean(voice[:frames * hop].reshape(frames, hop) ** 2, axis=1)) if frames else np.zeros(0)
    return lvl, (lvl > np.percentile(lvl, 95) * db(-30)) if frames else lvl.astype(bool)


def duck_env(voice_mono, depth_db=DUCK_DB):
    """Smooth sidechain gain (linear, per sample): attack 80 ms, hold 400 ms, release 800 ms."""
    hop = SR // 100
    lvl, active = _active(voice_mono, hop)
    g = np.ones(len(lvl))
    target, hold, cur = 1.0, 0, 1.0
    att, rel = 1 - np.exp(-1 / 8), 1 - np.exp(-1 / 80)
    for i in range(len(lvl)):
        if active[i]:
            target, hold = db(-depth_db), 40
        elif hold > 0:
            hold -= 1
        else:
            target = 1.0
        cur += (target - cur) * (att if target < cur else rel)
        g[i] = cur
    return np.repeat(g, hop)


def music_bus(stems: dict, cuts: list, peak_at: float, total: float) -> np.ndarray:
    """The music-only bus, (n, 2) float32, from decoded and normalised stems {"drone", "solo", "phrase"}."""
    n = int(round(total * SR))
    bus = np.zeros((n, 2), np.float32)
    drone, solo, phrase = stems["drone"], stems["solo"], stems["phrase"]
    cuts = sorted(float(c) for c in cuts) or [0.0]
    peak_at = float(peak_at)
    pre = min(peak_at, total)
    resume = peak_at + SILENCE_S
    place(bus, _seg(drone, 0.0, pre), 0.0, 1.0, fin=4.0, fout=0.03)
    c0 = cuts[0]
    open_end = min(cuts[min(2, len(cuts) - 1)], pre)
    if open_end - c0 < 1.0:
        open_end = min(pre, c0 + 6.0)
    if open_end > c0 + 0.5:
        place(bus, _seg(solo, 2.0, open_end - c0 - 0.5), max(0.0, c0 - 0.5), 1.0, fin=1.5, fout=2.5)
    start = max([c for c in cuts if c < peak_at - 0.5], default=0.0)
    if pre - start > 0.1:
        place(bus, _seg(phrase, 1.0, pre - start), start, db(-2), fin=2.0, fout=0.05)
    if resume < total:
        place(bus, _seg(drone, 10.0, total - resume), resume, db(-3), fin=1.6, fout=2.5)
        place(bus, _seg(solo, 30.0, total - resume), resume, db(-2), fin=1.2, fout=2.4)
    bus[int(round(peak_at * SR)):int(round(resume * SR))] = 0.0   # slices clip at the scene end
    return bus


def _fx_bus(items: list, n: int) -> np.ndarray:
    """Ambience/foley entries {"path", "at", "gain_db", "fin", "fout", "start"?, "dur"?}; gain_db is the clip's RMS level."""
    bus = np.zeros((n, 2), np.float32)
    for it in items:
        clip = read(it["path"], it.get("start", 0.0), it.get("dur"))
        place(bus, rms_norm(clip, it["gain_db"]), it["at"], 1.0, it.get("fin", 0.0), it.get("fout", 0.0))
    return bus


def scene_mix(voice: Path, cuts: list, peak_at: float, stems: dict, ambience: list, foley: list,
              out: Path, total: float) -> dict:
    """Mix one scene. `stems` maps drone/solo/phrase to audio files. Returns the measured
    {"voice_over_music_db", "lufs", "true_peak"} (loudness measured on the written `out`)."""
    n = int(round(total * SR))
    v = read(voice, ch=1)[:, 0]
    if abs(len(v) - n) > MAX_VOICE_DRIFT_S * SR:
        raise ValueError(f"voice {voice} is {len(v) / SR:.3f} s but the plan says {total:.3f} s "
                         f"(more than {MAX_VOICE_DRIFT_S * 1000:.0f} ms apart); use the re-timed narration of this plan")
    v = np.pad(v[:n], (0, max(0, n - len(v))))
    dec = {r: rms_norm(read(stems[r], af=HIGHPASS), STEM_DB[r]) for r in ("drone", "solo", "phrase")}
    music = music_bus(dec, cuts, peak_at, total)
    g = duck_env(v)
    g = np.pad(g, (0, n - len(g)), constant_values=1.0)[:n, None]
    _, act = _active(v, SR // 100)
    sp = np.repeat(act, SR // 100)
    sp = np.pad(sp, (0, n - len(sp)))[:n]
    if not sp.any():
        raise ValueError(f"voice {voice} has no speech to measure the music margin against")
    vrms = np.sqrt(np.mean(v[sp] ** 2) + 1e-18)
    # keep the stems' relative levels; scale the whole bus so the ducked music sits MARGIN_DB under the speech
    music = music * db(20 * np.log10(vrms / (np.sqrt(np.mean((music * g)[sp] ** 2)) + 1e-9)) - MARGIN_DB)
    ducked = music * g
    pk = slice(min(int(round(peak_at * SR)), n), min(int(round((peak_at + SILENCE_S) * SR)), n))
    # spec 7 "silence at peaks": RMS of the music-only bus over the peak window (-200 when empty or silent)
    peak_rms_db = 20 * np.log10(float(np.sqrt(np.mean(ducked[pk] ** 2))) + 1e-10) if pk.stop > pk.start else -200.0
    vm = 20 * np.log10(vrms / (np.sqrt(np.mean(ducked[sp] ** 2)) + 1e-9))
    amb = _fx_bus(list(ambience) + list(foley), n)
    mixed = v[:, None] + ducked + amb * (0.5 + 0.5 * g)   # no whole-mix fade: the film's last scene fades (Task 8)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        pre = Path(td) / "pre.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-", str(pre)],
                       input=mixed.astype(np.float32).tobytes(), check=True)
        res = mix._loudnorm_gated(pre, out, -16.0)
        # the master must be one gain on the bus (linear loudnorm), which keeps the margin; verify on the written file
        a, w = read(pre).ravel(), read(out).ravel()
        m = min(len(a), len(w))
        a, w = a[:m], w[:m]
        gain = float(np.dot(a, w) / (np.dot(a, a) + 1e-18))
        resid = float(np.linalg.norm(w - gain * a) / (np.linalg.norm(w) + 1e-18))
    if resid > 0.02:
        raise ValueError(f"scene master is not a single linear gain (residual {resid:.3f}); the music margin is unverified")
    if res["true_peak"] > TRUE_PEAK_MAX:
        raise ValueError(f"scene true peak {res['true_peak']:.1f} dBTP is above {TRUE_PEAK_MAX} dBTP")
    if not MARGIN_RANGE[0] <= vm <= MARGIN_RANGE[1]:
        raise ValueError(f"voice over music is {vm:.1f} dB, outside {MARGIN_RANGE[0]}-{MARGIN_RANGE[1]} dB")
    return {"voice_over_music_db": round(float(vm), 1), "lufs": res["lufs"], "true_peak": res["true_peak"],
            "music_bus_peak_rms_db": round(float(peak_rms_db), 1)}


# ------------------------------------------------------------------ stem picking
def _tonic_pc(tonic: str) -> int:
    m = re.fullmatch(r"([A-Ga-g])([#b]?)", tonic.strip())
    if not m:
        raise ValueError(f"tonic {tonic!r} is not a note name such as D, F# or Bb")
    return (_PC[m.group(1).upper()] + {"#": 1, "b": -1, "": 0}[m.group(2)]) % 12


def stem_features(path, tonic_pc: int) -> dict:
    """Measured at 22.05 kHz mono: tonic_in_top2 (chroma), onset_rate (onsets/s), pulse (0..1), low_energy (0..1)."""
    sr = 22050
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.float32)
    nfft, hop = 4096, 512
    if len(x) < nfft:
        x = np.pad(x, (0, nfft - len(x)))
    win = np.hanning(nfft)
    frames = np.stack([x[i:i + nfft] * win for i in range(0, len(x) - nfft + 1, hop)])
    mag = np.abs(np.fft.rfft(frames, axis=1))
    freqs = np.fft.rfftfreq(nfft, 1 / sr)
    band = (freqs >= 55) & (freqs <= 2000)
    pcs = np.round(12 * np.log2(freqs[band] / 440.0) + 69).astype(int) % 12
    chroma = np.bincount(pcs, weights=(mag[:, band] ** 2).sum(axis=0), minlength=12)
    top2 = np.argsort(chroma)[-2:]
    power = (mag ** 2).sum(axis=0)
    low = float(power[freqs < 120].sum() / (power.sum() + 1e-12))
    flux = np.maximum(np.diff(mag, axis=0), 0).sum(axis=1)
    thr = max(flux.mean() + 1.5 * flux.std(), 0.15 * (mag.sum(axis=1).mean() + 1e-12))
    peaks = (flux[1:-1] > thr) & (flux[1:-1] >= flux[:-2]) & (flux[1:-1] > flux[2:])
    onset_rate = float(peaks.sum() / (len(x) / sr))
    k = int(1.0 * sr / hop)                                   # remove slow swell before looking for a pulse
    f = flux - np.convolve(np.pad(flux, k // 2, mode="edge"), np.ones(k) / k, mode="valid")[:len(flux)]
    ac = np.correlate(f, f, "full")[len(f) - 1:]
    lo, hi = int(0.25 * sr / hop), int(1.0 * sr / hop)
    pulse = float(max(0.0, ac[lo:hi + 1].max() / (ac[0] + 1e-12))) if peaks.any() and len(ac) > hi and ac[0] > 0 else 0.0
    return {"tonic_in_top2": bool(tonic_pc in top2), "onset_rate": onset_rate, "pulse": pulse, "low_energy": low}


def _unit(vals: dict) -> dict:
    lo, hi = min(vals.values()), max(vals.values())
    return {k: (v - lo) / (hi - lo) if hi > lo else 0.0 for k, v in vals.items()}


def pick_stems(stems_dir: Path, tonic: str) -> dict:
    """Choose {"drone", "solo", "phrase"} keys from <stems_dir>/<key>.wav|.flac|.mp3, never reusing a key.

    Per stem: t = 1 when the tonic is in the chroma top-2, else 0; o, p, l = onset rate, pulse autocorrelation
    and energy below 120 Hz, each min-max normalised across the stems (0 best). Scores, highest wins, assigned
    in this order from the stems still free (ties break on the key name):
      drone  = 2t - o - p       a sustained, unpulsed bed on the tonic
      solo   = 1.5t - 0.5o - p - l   a melodic line on the tonic that stays out of the low end
      phrase = t - p - l        a phrase that carries the tonic without pulse or mud
    """
    pc = _tonic_pc(tonic)
    keys = sorted({p.stem for p in Path(stems_dir).iterdir()
                   if p.is_file() and p.suffix.lower() in STEM_EXTS and not p.stem.endswith(".raw")})
    if len(keys) < 3:
        raise ValueError(f"{stems_dir} has {len(keys)} stem(s); picking needs at least 3")
    feats = {k: stem_features(stem_path(stems_dir, k), pc) for k in keys}
    o, p, l = (_unit({k: feats[k][m] for k in keys}) for m in ("onset_rate", "pulse", "low_energy"))
    t = {k: 1.0 if feats[k]["tonic_in_top2"] else 0.0 for k in keys}
    score = {"drone": lambda k: 2 * t[k] - o[k] - p[k],
             "solo": lambda k: 1.5 * t[k] - 0.5 * o[k] - p[k] - l[k],
             "phrase": lambda k: t[k] - p[k] - l[k]}
    free, pick = list(keys), {}
    for role, fn in score.items():
        pick[role] = max(free, key=lambda k: (round(fn(k), 9), [-ord(c) for c in k]))
        free.remove(pick[role])
    return pick


def write_pick(stems_dir: Path, tonic: str, pick: dict) -> Path:
    p = Path(stems_dir) / "cue-pick.json"
    p.write_text(json.dumps({"tonic": tonic, **pick}, indent=1) + "\n", encoding="utf-8")
    return p
