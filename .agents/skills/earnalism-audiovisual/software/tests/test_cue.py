import wave

import numpy as np

from eav import cue
from tests._media import rms_db, samples

SR = 48000
TOTAL = 12.0
_rng = np.random.default_rng(3)


def _wav(path, x):
    x = np.asarray(x, np.float32)
    st = np.stack([x, x], axis=1) if x.ndim == 1 else x
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(st, -1, 1) * 32767).astype("<i2").tobytes())


def _t(s):
    return np.arange(int(s * SR)) / SR


def _tone(freqs, s, amp=0.3):
    return amp * sum(np.sin(2 * np.pi * f * _t(s)) for f in freqs) / len(freqs)


def _stems(d, s=14.0):
    d.mkdir(parents=True, exist_ok=True)
    t = _t(s)
    _wav(d / "drone.wav", _tone([146.83, 293.66], s) * (1 + 0.1 * np.sin(2 * np.pi * 0.2 * t)))
    kick = np.zeros(len(t))                               # 2 Hz pulse of 60 Hz thumps: no tonic, low, pulsed
    for b in np.arange(0, s, 0.5):
        i = int(b * SR)
        m = min(int(0.12 * SR), len(t) - i)
        kick[i:i + m] = 0.6 * np.sin(2 * np.pi * 60 * t[:m]) * np.exp(-t[:m] * 30)
    _wav(d / "kick.wav", kick)
    pluck = np.zeros(len(t))                              # sparse irregular plucks on G / C
    for b, f in zip([0.7, 2.9, 3.6, 6.2, 8.8, 9.5, 11.7], [392, 523, 392, 523, 392, 523, 392]):
        i = int(b * SR)
        m = min(int(0.9 * SR), len(t) - i)
        pluck[i:i + m] = 0.4 * np.sin(2 * np.pi * f * t[:m]) * np.exp(-t[:m] * 4)
    _wav(d / "pluck.wav", pluck)
    _wav(d / "chord.wav", _tone([293.66, 369.99, 440.0], s) * (1 + 0.2 * np.sin(2 * np.pi * 0.1 * t)))
    return d


def _voice(path, total=TOTAL, amp=0.3, always=False):
    t = _t(total)
    gate = np.ones(len(t)) if always else ((t % 3.0) < 1.8).astype(float)   # speech 0-1.8 s, gap 1.8-3 s, repeating
    _wav(path, amp * np.sin(2 * np.pi * 220 * t) * gate)
    return path


def _noise(path, s, amp=0.1):
    _wav(path, amp * _rng.standard_normal(int(s * SR)))


def _mix(tmp_path, peak_at=7.0, total=TOTAL, cuts=(0.0, 2.5, 5.0, 6.0), amb=(), foley=(), amp=0.3, always=False,
         voice_total=None):
    stems = _stems(tmp_path / "stems")
    voice = _voice(tmp_path / "v.wav", voice_total or total, amp, always)
    out = tmp_path / "scene.wav"
    r = cue.scene_mix(voice, list(cuts), peak_at, {k: stems / f"{n}.wav" for k, n in
                      (("drone", "drone"), ("solo", "pluck"), ("phrase", "chord"))}, list(amb), list(foley), out, total)
    return r, out


def test_pick_prefers_tonic_and_low_pulse(tmp_path):
    d = _stems(tmp_path / "stems")
    pick = cue.pick_stems(d, "D")
    assert set(pick) == {"drone", "solo", "phrase"}
    assert pick["drone"] == "drone"
    assert len(set(pick.values())) == 3 and "kick" not in pick.values()
    assert pick["phrase"] == "chord" or pick["solo"] == "chord"
    p = cue.write_pick(d, "D", pick)
    assert p.parent == d and p.suffix == ".json"


def test_music_silent_at_peak(tmp_path):
    stems = _stems(tmp_path / "stems")
    dec = {r: cue.rms_norm(cue.read(stems / f"{n}.wav", af=cue.HIGHPASS), db)
           for r, n, db in (("drone", "drone", -22), ("solo", "pluck", -19), ("phrase", "chord", -20))}
    bus = cue.music_bus(dec, [0.0, 2.5, 5.0, 6.0], 7.0, TOTAL)
    win = bus[int(7.0 * SR):int(7.4 * SR)]
    assert rms_db(win) < -80
    assert rms_db(bus[int(6.0 * SR):int(6.9 * SR)]) > -40       # music holds right up to the peak
    assert rms_db(bus[int(7.6 * SR):int(9 * SR)]) > -40         # and returns after


def test_peak_silence_at_scene_end_is_clipped(tmp_path):
    stems = _stems(tmp_path / "stems")
    dec = {r: cue.rms_norm(cue.read(stems / f"{n}.wav", af=cue.HIGHPASS), -20)
           for r, n in (("drone", "drone"), ("solo", "pluck"), ("phrase", "chord"))}
    bus = cue.music_bus(dec, [0.0, 2.5, 5.0], 11.8, TOTAL)       # 11.8 + 0.4 > 12
    assert bus.shape == (int(TOTAL * SR), 2)
    assert rms_db(bus[int(11.8 * SR):]) < -80
    assert rms_db(bus[int(10.0 * SR):int(11.7 * SR)]) > -40
    r, out = _mix(tmp_path, peak_at=11.8)
    assert out.is_file() and r["lufs"] is not None


def test_voice_over_music_in_range_16_to_18(tmp_path):
    r, _ = _mix(tmp_path)
    assert 16.0 <= r["voice_over_music_db"] <= 18.0, r


def test_margin_holds_for_quiet_and_loud_voices(tmp_path):
    for i, amp in enumerate((0.05, 0.15, 0.6)):
        d = tmp_path / str(i)
        d.mkdir()
        r, _ = _mix(d, amp=amp)
        assert 16.0 <= r["voice_over_music_db"] <= 18.0, (amp, r)
        assert abs(r["lufs"] + 16) <= 1.0 and r["true_peak"] <= -1.5


def test_true_peak_over_limit_is_refused(tmp_path, monkeypatch):
    import pytest
    from eav import mix
    real = mix._loudnorm_gated
    monkeypatch.setattr(mix, "_loudnorm_gated", lambda pre, out, t: {**real(pre, out, t), "true_peak": -1.2})
    with pytest.raises(ValueError, match="true peak"):
        _mix(tmp_path)


def test_no_end_fade_voice_and_room_tone_survive_to_the_end(tmp_path):
    n1 = tmp_path / "amb.wav"
    _noise(n1, TOTAL)
    _, out = _mix(tmp_path, always=True, amb=[{"path": n1, "at": 0.0, "gain_db": -36, "fin": 0.0, "fout": 0.0}])
    y = samples(out)
    assert np.abs(y[-int(0.05 * SR):]).max() > 1e-3
    assert abs(rms_db(y[-SR:]) - rms_db(y[-3 * SR:-2 * SR])) < 1.5


def test_voice_length_must_match_plan(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="voice"):
        _mix(tmp_path, voice_total=TOTAL + 0.5)
    with pytest.raises(ValueError, match="voice"):
        _mix(tmp_path / "x" if (tmp_path / "x").mkdir() is None else tmp_path, voice_total=TOTAL - 0.2)
    _mix(tmp_path / "ok" if (tmp_path / "ok").mkdir() is None else tmp_path, voice_total=TOTAL + 0.03)


def test_output_is_stereo_and_meets_loudness(tmp_path):
    n1, n2 = tmp_path / "amb.wav", tmp_path / "pot.wav"
    _noise(n1, 6.0)
    _noise(n2, 1.0)
    r, out = _mix(tmp_path, amb=[{"path": n1, "at": 0.0, "gain_db": -36, "fin": 1.0, "fout": 1.0}],
                  foley=[{"path": n2, "at": 7.9, "gain_db": -24, "fin": 0.0, "fout": 0.3, "start": 0.0, "dur": 0.8}])
    assert cue.read(out).shape[1] == 2
    assert abs(r["lufs"] + 16) <= 1.0 and r["true_peak"] <= -1.5
    y = samples(out)
    assert len(y) >= int((TOTAL - 0.05) * SR) and len(y) <= int((TOTAL + 0.05) * SR)


# ----------------------------------------------------------------------------- CLI
def _cli_title(tmp_path):
    from tests.test_shotplan import _title
    root, run = _title(tmp_path)
    _stems(root / "music" / "m1")
    return root, run


def test_cue_cli_pick_then_mix_needs_approved_plan(tmp_path):
    import json
    root, run = _cli_title(tmp_path)
    code, out = run("cue", "--root", root, "--film", 1, "--stems", "m1", "--pick", "--tonic", "D")
    assert code == 0 and '"drone": "drone"' in out and (root / "music" / "m1" / "cue-pick.json").is_file()
    code, out = run("cue", "--root", root, "--film", 1, "--scene", "f01s014", "--stems", "m1")
    assert code == 2 and "no shot plan" in out                       # R11: nothing is built before approval
    for extra in ([], ["--approve", "--by", "claude", "--reviewer", "rev"]):
        assert run("plan-shots", "--root", root, "--film", 1, "--scene", "f01s014", *extra)[0] == 0
    sp = json.loads((root / "film" / "film-01" / "shots" / "f01s014.json").read_text(encoding="utf-8"))
    (root / "film" / "film-01" / "voice").mkdir()
    _voice(root / "film" / "film-01" / "voice" / "f01s014.wav", sp["seconds"])
    code, out = run("cue", "--root", root, "--film", 1, "--scene", "f01s014", "--stems", "m1")
    assert code == 0, out
    res = json.loads((root / "film" / "film-01" / "audio" / "f01s014.mix.json").read_text(encoding="utf-8"))
    assert res["peak_at"] == sp["peak"]["at"] and abs(res["lufs"] + 16) <= 1 and res["true_peak"] <= -1.5
