import copy
import json
import math
from pathlib import Path

import pytest

from eav import cli, shotplan

FIX = json.loads((Path(__file__).parent / "fixtures" / "scene14.json").read_text(encoding="utf-8"))


def _scene():
    return {**FIX["scene"], **copy.deepcopy(FIX["input"])}


def _plan():
    return shotplan.plan(_scene(), FIX["timing"], FIX["bible"])


def _shot(n, start, end, motion="glide", **kw):
    return {"n": n, "start": start, "end": end, "framing": "wide", "camera": {"move": "push", "zoom": 0.1, "pan_x": 0, "ease": "both"},
            "motion": motion, "wan_res": "1280x704" if motion == "wan" else None, "subject": "s", "bible_refs": [],
            "sound": {"vo": "", "sfx": [], "music": None}, "layer": "present", "transition_in": "cut", **kw}


def _hand(shots, peak, seconds):
    return {"scene_id": "x", "spine": "s", "seconds": seconds, "shots": shots, "peak": peak,
            "compute": {"stills": len(shots), "wan_clips": 0, "cu": 0.0}}


def test_beats_follow_measured_timing():
    b = shotplan.beats(FIX["scene"]["text"], FIX["timing"])
    assert len(b) == len(FIX["timing"]) == 12
    assert b[0]["start"] == 0.0 and b[-1]["end"] == FIX["duration"]
    assert b[1]["pause_after"] == pytest.approx(1.0)


def test_beats_refuse_timing_that_changes_the_words():
    bad = copy.deepcopy(FIX["timing"])
    bad[3]["text"] += " extra"
    with pytest.raises(ValueError, match="words"):
        shotplan.beats(FIX["scene"]["text"], bad)


def test_shot_count_at_least_seconds_over_6():
    p = _plan()
    assert len(p["shots"]) >= math.ceil(p["seconds"] / 6)
    assert [s["n"] for s in p["shots"]] == list(range(1, len(p["shots"]) + 1))
    assert p["shots"][0]["start"] == 0.0 and p["shots"][-1]["end"] == FIX["duration"]
    for a, b in zip(p["shots"], p["shots"][1:]):
        assert a["end"] == b["start"]
    assert shotplan.validate(p) == []
    assert p["compute"]["stills"] == 11 and p["compute"]["wan_clips"] == 2 and p["compute"]["cu"] > 0
    assert p["shots"][8]["sound"]["vo"] == FIX["timing"][9]["text"]


def test_plan_does_not_invent_content():
    s = _scene()
    del s["shots"][0]["subject"]
    with pytest.raises(ValueError, match="subject"):
        shotplan.plan(s, FIX["timing"], FIX["bible"])
    s = _scene()
    s["shots"][0]["bible_refs"] = ["nobody"]
    with pytest.raises(ValueError, match="bible"):
        shotplan.plan(s, FIX["timing"], FIX["bible"])
    s = _scene()
    s["shots"][1]["beats"] = [3, 3]  # leaves a hole in the narration
    with pytest.raises(ValueError, match="beats"):
        shotplan.plan(s, FIX["timing"], FIX["bible"])


def test_validate_flags_r1_gap():
    p = _hand([_shot(1, 0.0, 7.0)] + [_shot(i, 7.0 + (i - 2) * 5.0, 12.0 + (i - 2) * 5.0) for i in range(2, 4)], None, 17.0)
    assert "R1" in shotplan.validate(p)
    wan = _hand([_shot(1, 0.0, 7.0, "wan")], None, 7.0)
    assert "R1" not in shotplan.validate(wan)


def test_validate_flags_r2():
    p = _plan()
    p["shots"][1]["end"] += 0  # untouched baseline
    assert "R2" not in shotplan.validate(p)
    few = _hand([_shot(1, 0.0, 5.0), _shot(2, 5.0, 10.0)], None, 13.0)
    few["shots"][1]["end"] = 13.0
    assert "R2" in shotplan.validate(few)  # 13 s needs 3 shots; and 8 s non-wan
    long = _hand([_shot(1, 0.0, 13.0, "wan")], None, 13.0)
    assert "R2" in shotplan.validate(long)  # over 12 s even with wan


def test_validate_flags_r3_peak_without_plant():
    p = _plan()
    p["shots"][8].pop("plants")
    assert "R3" in shotplan.validate(p)
    p = _plan()
    p["peak"]["at"] = 20.0  # 39 %
    assert "R3" in shotplan.validate(p)
    p = _plan()
    p["peak"] = None
    assert "R3" in shotplan.validate(p)
    p = _plan()
    p["peak"] = {"shot": 10, "at": 44.5}  # 10 is 4.15 s long, 85.7 %
    assert "R3" in shotplan.validate(p)
    p = _plan()
    p["shots"][8]["plants"] = [10]  # a plant after the peak is no plant
    assert "R3" in shotplan.validate(p)


def test_soft_warnings_are_marked_with_a_question_mark():
    s = _scene()
    s["motifs"] = []
    p = shotplan.plan(s, FIX["timing"], FIX["bible"])
    w = shotplan.validate(p)
    assert "R8?" in w and not [c for c in w if not c.endswith("?")]
    assert "R11" not in shotplan.validate(_plan()) and "R11" in shotplan.validate(_plan(), for_job=True)


def test_av_markdown_has_two_columns_per_shot():
    p = _plan()
    md = shotplan.av_markdown(p)
    rows = [l for l in md.splitlines() if l.startswith("| ") and not l.startswith("| Time") and not l.startswith("| ---")]
    assert len(rows) == len(p["shots"])
    for r, s in zip(rows, p["shots"]):
        cells = [c.strip() for c in r.strip("|").split("|")]
        assert len(cells) == 3  # time | audio | visual
        assert s["subject"] in cells[2] and s["sound"]["vo"] in cells[1]
    assert "| Time | Audio | Visual |" in md and "PEAK" in md


def test_approve_needs_two_distinct_people_and_a_valid_plan():
    p = _plan()
    with pytest.raises(ValueError, match="independent"):
        shotplan.approve(p, "claude", "claude")
    bad = _plan()
    bad["peak"] = None
    with pytest.raises(ValueError, match="R3"):
        shotplan.approve(bad, "claude", "reviewer")
    a = shotplan.approve(p, "claude", "reviewer", at="2026-11-27T10:00:00+00:00")
    assert a["approved"] == {"by": "claude", "at": "2026-11-27T10:00:00+00:00", "reviewer": "reviewer"}
    assert "approved" not in p  # the input plan is not mutated


def test_job_refuses_unapproved_scene(tmp_path):
    film = tmp_path / "film-01"
    with pytest.raises(shotplan.NotApproved, match="plan-shots"):
        shotplan.require_approved(film, "f01s014")
    shotplan.write(film, _plan())
    with pytest.raises(shotplan.NotApproved, match="approved"):
        shotplan.require_approved(film, "f01s014")
    shotplan.write(film, shotplan.approve(_plan(), "claude", "reviewer"))
    shotplan.require_approved(film, "f01s014")  # no raise
    assert (film / "shots" / "f01s014.av.md").is_file()


# ----------------------------------------------------------------------------- CLI
def _title(tmp_path):
    from tests.test_cli import SOURCE, run  # the shared CLI runner and source
    src = tmp_path / "src.json"
    src.write_text(json.dumps(SOURCE), encoding="utf-8")
    root = tmp_path / "t"
    assert run("init", src, "--root", root)[0] == 0
    (root / "specs").mkdir(parents=True)
    (root / "specs" / "world-bible.json").write_text(json.dumps(FIX["bible"]), encoding="utf-8")
    plan = {"language": "bn", "wpm": 130, "voice": {}, "plan": {"series": False, "films": [{"scenes": [
        {"scene_id": "f01s014", "text": FIX["scene"]["text"], "seconds": 44.5}]}]}}
    (root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    inp = root / "film" / "film-01" / "shots"
    inp.mkdir(parents=True)
    (inp / "f01s014.input.json").write_text(json.dumps({**FIX["input"], "timing": FIX["timing"]}), encoding="utf-8")
    return root, run


def test_plan_shots_cli_writes_plan_and_av_then_approves(tmp_path):
    root, run = _title(tmp_path)
    code, out = run("plan-shots", "--root", root, "--film", 1, "--scene", "f01s014")
    shots = root / "film" / "film-01" / "shots"
    assert code == 0, out
    plan = json.loads((shots / "f01s014.json").read_text(encoding="utf-8"))
    assert "approved" not in plan and (shots / "f01s014.av.md").is_file()
    code, out = run("plan-shots", "--root", root, "--film", 1, "--scene", "f01s014", "--approve", "--by", "claude")
    assert code == 2 and "--reviewer" in out
    code, out = run("plan-shots", "--root", root, "--film", 1, "--scene", "f01s014", "--approve", "--by", "x", "--reviewer", "x")
    assert code == 2 and "independent" in out
    code, out = run("plan-shots", "--root", root, "--film", 1, "--scene", "f01s014", "--approve", "--by", "claude", "--reviewer", "rev")
    assert code == 0, out
    ap = json.loads((shots / "f01s014.json").read_text(encoding="utf-8"))["approved"]
    assert ap["by"] == "claude" and ap["reviewer"] == "rev" and ap["at"]


def test_plan_shots_cli_refuses_to_approve_a_failing_plan(tmp_path):
    root, run = _title(tmp_path)
    f = root / "film" / "film-01" / "shots" / "f01s014.input.json"
    d = json.loads(f.read_text(encoding="utf-8"))
    d["peak"]["at"] = 10.0
    f.write_text(json.dumps(d), encoding="utf-8")
    code, out = run("plan-shots", "--root", root, "--film", 1, "--scene", "f01s014")
    assert code == 1 and "R3" in out
    code, out = run("plan-shots", "--root", root, "--film", 1, "--scene", "f01s014", "--approve", "--by", "claude", "--reviewer", "rev")
    assert code == 2 and "R3" in out
    assert "approved" not in json.loads((root / "film" / "film-01" / "shots" / "f01s014.json").read_text(encoding="utf-8"))


def test_stills_job_with_scene_key_needs_approval_but_legacy_spec_does_not(tmp_path):
    root, run = _title(tmp_path)
    rates = tmp_path / "r.json"
    rates.write_text(json.dumps({"stills": {"s_per_step": 10.0, "units_per_hour": 5.0, "steps": 4,
                                            "decode_s": 10, "export_s": 10}}), encoding="utf-8")
    items = [{"key": "f01s014-1", "prompt": "a lamp", "seed": 1}]
    spec = tmp_path / "stills.json"
    spec.write_text(json.dumps({"scene": "f01s014", "items": items}), encoding="utf-8")
    args = ("job", "stills", "--root", root, "--film", 1, "--rates", rates, "--spec", spec)
    code, out = run(*args)
    assert code == 2 and "plan-shots" in out and "no shot plan" in out
    assert not (root / "jobs").exists() or not list((root / "jobs").iterdir())
    assert run("plan-shots", "--root", root, "--film", 1, "--scene", "f01s014")[0] == 0
    code, out = run(*args)  # planned but not approved: still refused
    assert code == 2 and "not approved" in out
    assert run("plan-shots", "--root", root, "--film", 1, "--scene", "f01s014", "--approve", "--by", "claude", "--reviewer", "rev")[0] == 0
    code, out = run(*args)
    assert code == 0 and "Built stills job" in out, out
    spec.write_text(json.dumps({"items": items}), encoding="utf-8")  # legacy: no scene key, never asked for approval
    (root / "film" / "film-01" / "shots" / "f01s014.json").unlink()
    code, out = run(*args)
    assert code == 0 and "Built stills job" in out, out
