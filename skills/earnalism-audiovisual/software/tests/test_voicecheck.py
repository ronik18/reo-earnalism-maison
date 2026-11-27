import json

import numpy as np

from eav import retime, voicecheck
from eav.retime import SR

RNG = np.random.default_rng(3)


def _voice(contour_st, amp=0.3):
    """Sine whose pitch follows contour_st (semitones about 180 Hz), one value per sample."""
    f = 180.0 * 2 ** (np.asarray(contour_st) / 12)
    return (amp * np.sin(2 * np.pi * np.cumsum(f) / SR)).astype(np.float32)


def _vib(seconds, depth=4.0, period=1.5):
    t = np.arange(int(seconds * SR)) / SR
    return depth * np.sin(2 * np.pi * t / period)


def _floor(n):
    return (RNG.standard_normal(n) * 10 ** (-62 / 20)).astype(np.float32)


def _phrases(n=4, burst=2.4, gap=0.4, depth=4.0, tail_fade=True):
    """Expressive 'speech': vibrato bursts, room-tone gaps, a faded end. Returns the samples."""
    parts = []
    for _ in range(n):
        b = _voice(_vib(burst, depth))
        ramp = np.linspace(0, 1, int(0.03 * SR)).astype(np.float32)  # no hard edges: those are real clicks
        b[:len(ramp)] *= ramp
        b[-len(ramp):] *= ramp[::-1]
        parts += [b, _floor(int(gap * SR))]
    y = np.concatenate(parts)
    if tail_fade:
        y[-int(0.5 * SR):] *= np.linspace(1, 0, int(0.5 * SR)).astype(np.float32)
        y[-int(0.1 * SR):] = _floor(int(0.1 * SR))
    return y


def _write(path, y):
    retime.write(path, y)
    return path


def _prof(path):
    return voicecheck.profile([path])


def test_flat_tone_fails_pitch_spread_and_monotone(tmp_path):
    y = np.concatenate([_voice(np.zeros(int(2.0 * SR))), _floor(int(0.4 * SR))] * 3)
    p = _write(tmp_path / "flat.wav", y)
    r = voicecheck.check(p, len(y) / SR, _prof(p))
    assert "pitch_spread" in r["failures"] and "monotone" in r["failures"]
    assert r["pass"] is False


def test_varied_glide_passes_pitch(tmp_path):
    p = _write(tmp_path / "v.wav", _phrases())
    r = voicecheck.check(p, 4 * 2.8, _prof(p))
    assert "pitch_spread" not in r["failures"] and "monotone" not in r["failures"]
    assert r["metrics"]["pitch_spread_st"] > 3.0


def test_abrupt_tail_fails_tail(tmp_path):
    y = _phrases(tail_fade=False)
    y = np.concatenate([y[:-int(0.4 * SR)], _voice(_vib(0.4))])  # ends on a full-level sine
    p = _write(tmp_path / "t.wav", y)
    r = voicecheck.check(p, len(y) / SR, _prof(p))
    assert "tail" in r["failures"]


def test_long_run_fails_no_breath(tmp_path):
    y = np.concatenate([_voice(_vib(10.0)), _floor(int(0.4 * SR))])
    p = _write(tmp_path / "l.wav", y)
    r = voicecheck.check(p, len(y) / SR, _prof(p))
    assert "no_breath" in r["failures"]


def test_zero_gap_fails_digital_zero(tmp_path):
    y = _phrases()
    y[int(2.5 * SR):int(2.5 * SR) + int(0.2 * SR)] = 0
    p = _write(tmp_path / "z.wav", y)
    r = voicecheck.check(p, len(y) / SR, _prof(p))
    assert "digital_zero" in r["failures"]


def test_duration_outside_12_percent_fails(tmp_path):
    y = _phrases()
    p = _write(tmp_path / "d.wav", y)
    d = len(y) / SR
    assert "duration" in voicecheck.check(p, d * 1.2, _prof(p))["failures"]
    assert "duration" not in voicecheck.check(p, d * 1.05, _prof(p))["failures"]


def test_clean_take_passes_all(tmp_path):
    y = _phrases()
    p = _write(tmp_path / "c.wav", y)
    r = voicecheck.check(p, len(y) / SR, _prof(p))
    assert r["failures"] == [] and r["pass"] is True
    assert set(r["metrics"]) >= {"duration_s", "pitch_median_hz", "pitch_spread_st", "true_peak_dbfs"}


def test_profile_relative_checks(tmp_path):
    p = _write(tmp_path / "c.wav", _phrases())
    prof = _prof(p)
    assert set(prof) >= {"pitch_median_hz", "rate", "brightness_db", "jump_rate", "click_rate"}
    off = dict(prof, pitch_median_hz=prof["pitch_median_hz"] * 2 ** (3 / 12))
    assert "pitch_median" in voicecheck.check(p, 11.2, off)["failures"]
    assert "pitch_median" not in voicecheck.check(p, 11.2, {})["failures"]  # missing key: skipped


def test_true_peak_and_join(tmp_path):
    y = _phrases()
    hot = _write(tmp_path / "hot.wav", np.clip(y * 3.4, -1, 1))
    assert "true_peak" in voicecheck.check(hot, len(y) / SR, {})["failures"]
    flat = lambda st, g=1.0: _voice(np.full(int(3 * SR), float(st))) * g
    take = _write(tmp_path / "f.wav", flat(0))
    n = 3.0
    quiet = _write(tmp_path / "quiet.wav", flat(0, 0.05))   # about 25 LU quieter
    high = _write(tmp_path / "high.wav", flat(3))           # 3 semitones higher
    same = _write(tmp_path / "same.wav", flat(0))
    assert "join" in voicecheck.check(take, n, {}, prev_tail=quiet)["failures"]
    assert "join" in voicecheck.check(take, n, {}, prev_tail=high)["failures"]
    assert "join" not in voicecheck.check(take, n, {}, prev_tail=same)["failures"]


def test_cli_writes_voicecheck_json(tmp_path):
    from eav import cli
    y = _phrases()
    take = _write(tmp_path / "a.wav", y)
    code = cli.main(["voicecheck", str(take), "--expected", str(len(y) / SR)])
    out = json.loads((tmp_path / "a.voicecheck.json").read_text())
    assert out["pass"] is True and code == 0


def test_unvoiced_take_fails_instead_of_crashing(tmp_path):
    y = (RNG.standard_normal(3 * SR) * 0.1).astype(np.float32)
    p = _write(tmp_path / "noise.wav", y)
    r = voicecheck.check(p, 3.0, {"pitch_median_hz": 180.0})
    assert r["pass"] is False and "pitch_median" in r["failures"]


def test_true_peak_blocks_match_reference_and_long_take_completes():
    y = (RNG.standard_normal(2 * SR) * 0.2).astype(np.float32)
    ref = float(20 * np.log10(np.max(np.abs(np.fft.irfft(np.fft.rfft(y), 4 * len(y)) * 4))))
    assert abs(voicecheck._true_peak_db(y) - ref) < 0.1
    long = (RNG.standard_normal(600 * SR) * 0.05).astype(np.float32)
    assert voicecheck._true_peak_db(long) < 0
    assert voicecheck._clicks(long) >= 0


def test_cli_profile_saved_per_take_files_and_exit_code(tmp_path):
    from eav import cli
    a = _write(tmp_path / "a.wav", _phrases())
    b = _write(tmp_path / "b.wav", _phrases())
    n = len(_phrases()) / SR
    assert cli.main(["voicecheck", str(a), str(b), "--expected", str(n)]) == 0
    prof_file = tmp_path / "voicecheck-profile.json"
    assert "pitch_median_hz" in json.loads(prof_file.read_text())
    assert json.loads((tmp_path / "a.voicecheck.json").read_text())["pass"] is True
    assert (tmp_path / "b.voicecheck.json").exists()
    # same take shifted +3 st: resample by 2**(3/12) via index mapping
    y = _phrases()
    idx = np.arange(0, len(y) - 1, 2 ** (3 / 12))
    shifted = _write(tmp_path / "hi.wav", np.interp(idx, np.arange(len(y)), y).astype(np.float32))
    code = cli.main(["voicecheck", str(shifted), "--expected", str(len(idx) / SR), "--profile", str(prof_file)])
    res = json.loads((tmp_path / "hi.voicecheck.json").read_text())
    assert "pitch_median" in res["failures"] and code == 1
    assert json.loads((tmp_path / "a.voicecheck.json").read_text())["pass"] is True  # untouched
    assert json.loads(prof_file.read_text()) == json.loads(prof_file.read_text())
