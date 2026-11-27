import wave

import numpy as np
import pytest

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


def test_peak_silence_is_recorded_for_the_qc_gate(tmp_path):
    r, _ = _mix(tmp_path)
    assert r["music_bus_peak_rms_db"] < -80          # spec 7: silence at the peak, measured on the music-only bus
    r, _ = _mix(tmp_path, peak_at=11.95)              # clipped to the scene end: still recorded, still silent
    assert r["music_bus_peak_rms_db"] < -80


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
def _music_job(root, job_id, scene, roles):
    """An imported ACE-Step music job as the record sees it, its job.json items labelled by role."""
    import json, zipfile
    from eav.record import Record
    rec = Record.load(root)
    jd = root / "jobs" / job_id
    jd.mkdir(parents=True)
    with zipfile.ZipFile(jd / "inputs.zip", "w") as z:
        z.writestr("job.json", json.dumps({"items": [{"key": k, "role": r} for k, r in roles.items()],
                                           **({"scene": scene} if scene else {})}))
    for name in ("build-manifest.json", "music.ipynb"):
        (jd / name).write_text("{}")
    rec.add_artifact("colab_job", jd / "music.ipynb", {"job_id": job_id, "job_kind": "music", "forecast_units": 0.0,
                                                       "month": "2026-11", "inputs_zip": f"jobs/{job_id}/inputs.zip",
                                                       "manifest": f"jobs/{job_id}/build-manifest.json"})
    rec.event("cli", "job_target", {"job_id": job_id, "target": "film-01", "kind": "music",
                                    **({"scene": scene} if scene else {})})
    _stems(root / "music" / job_id)
    rec.event("import", "accepted", {"job_id": job_id})


ROLES = {"drone": "drone", "kick": "drone", "pluck": "solo", "chord": "phrase"}


def _cli_title(tmp_path):
    from tests.test_shotplan import _title
    root, run = _title(tmp_path)
    _music_job(root, "m1", "f01s014", ROLES)
    return root, run


def _approved(root, run):
    import json
    for extra in ([], ["--approve", "--by", "claude", "--reviewer", "rev"]):
        assert run("plan-shots", "--root", root, "--film", 1, "--scene", "f01s014", *extra)[0] == 0
    sp = json.loads((root / "film" / "film-01" / "shots" / "f01s014.json").read_text(encoding="utf-8"))
    (root / "film" / "film-01" / "voice").mkdir(exist_ok=True)
    _voice(root / "film" / "film-01" / "voice" / "f01s014.wav", sp["seconds"])
    return sp


def test_cue_cli_pick_then_mix_needs_approved_plan(tmp_path):
    import json
    root, run = _cli_title(tmp_path)
    code, out = run("cue", "--root", root, "--film", 1, "--scene", "f01s014", "--stems", "m1", "--pick", "--tonic", "D")
    assert code == 0 and '"drone": "drone"' in out and (root / "music" / "m1" / "cue-pick.json").is_file()
    code, out = run("cue", "--root", root, "--film", 1, "--scene", "f01s014", "--stems", "m1")
    assert code == 2 and "no shot plan" in out                       # R11: nothing is built before approval
    sp = _approved(root, run)
    code, out = run("cue", "--root", root, "--film", 1, "--scene", "f01s014", "--stems", "m1")
    assert code == 0, out
    res = json.loads((root / "film" / "film-01" / "audio" / "f01s014.mix.json").read_text(encoding="utf-8"))
    assert res["peak_at"] == sp["peak"]["at"] and abs(res["lufs"] + 16) <= 1 and res["true_peak"] <= -1.5
    assert res["music_bus_peak_rms_db"] < -80 and "fx" in res
    assert res["stems_job"] == "m1" and res["voice"].endswith("f01s014.wav")


def test_cue_refuses_stems_that_are_not_the_scenes_own_imported_music_job(tmp_path):
    """I9/F13: a folder copied in by hand, another scene's job, an unbound job, or a job another scene's mix
    already used is refused: a scene never borrows another scene's cue."""
    import json
    root, run = _cli_title(tmp_path)
    _stems(root / "music" / "copied")
    base = ("cue", "--root", root, "--film", 1, "--scene", "f01s014", "--pick", "--tonic", "D", "--stems")
    code, out = run(*base, "copied")
    assert code == 2 and "not an imported music job" in out
    _music_job(root, "m-other", "f01s013", ROLES)
    code, out = run(*base, "m-other")
    assert code == 2 and "scene f01s013" in out
    _music_job(root, "m-unbound", None, ROLES)
    code, out = run(*base, "m-unbound")
    assert code == 2 and "not bound to a scene" in out
    audio = root / "film" / "film-01" / "audio"
    audio.mkdir(parents=True)
    (audio / "f01s013.mix.json").write_text(json.dumps({"scene": "f01s013", "stems_job": "m1"}))
    code, out = run(*base, "m1")
    assert code == 2 and "never borrows" in out


def test_cue_pick_keeps_each_role_in_its_family(tmp_path):
    """I9/F7: the drone comes from the drone family (never the esraj), the phrase from the phrase family."""
    d = _stems(tmp_path / "stems")
    pick = cue.pick_stems(d, "D", {"drone": "drone", "kick": "drone", "pluck": "solo", "chord": "phrase"})
    assert pick == {"drone": "drone", "solo": "pluck", "phrase": "chord"}
    pick = cue.pick_stems(d, "D", {"drone": "solo", "kick": "drone", "pluck": "solo", "chord": "phrase"})
    assert pick["drone"] == "kick"          # the only drone, whatever its pulse: never a solo stem as the drone
    with pytest.raises(ValueError, match="no phrase stem"):
        cue.pick_stems(d, "D", {"drone": "drone", "kick": "drone", "pluck": "solo", "chord": "solo"})
    assert cue.stem_role("p3-drone-2") == "drone" and cue.stem_role("p3-esraj-4") is None
    assert cue.stem_role("p3-esraj-4", "solo") == "solo"


def test_cue_refuses_a_manual_stem_outside_its_family(tmp_path):
    root, run = _cli_title(tmp_path)
    _approved(root, run)
    code, out = run("cue", "--root", root, "--film", 1, "--scene", "f01s014", "--stems", "m1",
                    "--drone", "pluck", "--solo", "drone", "--phrase", "chord")
    assert code == 2 and "pluck as the drone" in out


def test_cue_fx_needs_a_licence_record_for_every_sound(tmp_path):
    """I10: every ambience or foley file needs a CC0 or author-released public-domain record in the licences.json
    beside it; anything else fails closed. The record's basis is copied into mix.json."""
    import json
    root, run = _cli_title(tmp_path)
    _approved(root, run)
    sfx = tmp_path / "sfx"
    sfx.mkdir()
    _noise(sfx / "wheels.wav", 2.0, 0.01)
    fx = sfx / "fx.json"
    fx.write_text(json.dumps({"ambience": [{"path": "wheels.wav", "at": 0.5, "gain_db": -40, "fin": 0.2, "fout": 0.2}]}))
    args = ("cue", "--root", root, "--film", 1, "--scene", "f01s014", "--stems", "m1", "--drone", "drone",
            "--solo", "pluck", "--phrase", "chord", "--fx", fx)
    code, out = run(*args)
    assert code == 2 and "without a licence" in out and "wheels.wav" in out
    (sfx / "licences.json").write_text(json.dumps({"wheels.wav": {"title": "wheels", "licence": "CC BY 4.0",
                                                                  "author": "x", "basis": {"rule": "cc0"}}}))
    code, out = run(*args)
    assert code == 2 and "CC BY 4.0" in out
    (sfx / "licences.json").write_text(json.dumps({"wheels.wav": {"title": "wheels", "licence": "CC0-1.0",
                                                                  "author": "Earnalism", "basis": {"rule": "cc0-synthesis"}}}))
    code, out = run(*args)
    assert code == 0, out
    res = json.loads((root / "film" / "film-01" / "audio" / "f01s014.mix.json").read_text(encoding="utf-8"))
    assert res["fx"]["ambience"][0]["licence"]["basis"] == "cc0-synthesis"
    rec = {"title": "File:Crows.ogg", "licence": "Public domain", "author": "x", "basis": {"rule": "author-release"}}
    assert cue.licence_ok(rec) == "author-release"
    assert cue.licence_ok({**rec, "basis": {"rule": "pd-us"}}) is None
