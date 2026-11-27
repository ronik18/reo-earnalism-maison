import copy
import zipfile
import json
import math
from pathlib import Path

import pytest

from eav import cli, colab_jobs, shotplan

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


def _t(*rows):
    return [{"start": a, "end": b, "text": t} for a, b, t in rows]


def test_beats_kinds_punct_and_breath():
    timing = _t((0.0, 1.0, "মনে হইতে লাগিল,"), (1.5, 2.5, "ঘরে ঘরে"), (2.9, 4.0, "সবাই ঘুমে।"))
    b = shotplan.beats("মনে হইতে লাগিল, ঘরে ঘরে সবাই ঘুমে।", timing)
    assert [x["kind"] for x in b] == ["punct", "breath", "end"]  # 0.4 s unpunctuated gap is a legal breath cut
    assert len(b) == 3


def test_beats_merge_an_unpunctuated_gap_under_015s():
    timing = _t((0.0, 1.0, "মনে হইতে লাগিল,"), (1.5, 2.5, "ঘরে ঘরে"), (2.6, 4.0, "সবাই ঘুমে।"))
    b = shotplan.beats("মনে হইতে লাগিল, ঘরে ঘরে সবাই ঘুমে।", timing)
    assert [x["kind"] for x in b] == ["punct", "end"]
    assert b[1]["text"] == "ঘরে ঘরে সবাই ঘুমে।" and (b[1]["start"], b[1]["end"]) == (1.5, 4.0)
    assert [x["n"] for x in b] == [0, 1]


def test_beats_punctuated_gap_is_punct_even_when_tiny():
    b = shotplan.beats("এক, দুই।", _t((0.0, 1.0, "এক,"), (1.05, 2.0, "দুই।")))
    assert [x["kind"] for x in b] == ["punct", "end"] and len(b) == 2


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
    assert p["compute"]["stills"] == 11 and p["compute"]["wan_clips"] == 4 and p["compute"]["cu"] > 0  # 2 chains of 2
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
    wan = _hand([_shot(1, 0.0, 7.0, "wan", actions=["she turns", "she blinks"])], None, 7.0)
    assert "R1" not in shotplan.validate(wan)


def test_a_long_wan_shot_needs_one_action_per_6_s():
    """I3/F8: plan-shots no longer counts a Wan shot as new information whatever its length; qc new_info fails a
    9.5 s take whose frame stays the same, so the plan asks for a second action (a continuation) past 6 s."""
    one = _hand([_shot(1, 0.0, 7.0, "wan")], None, 7.0)
    found = shotplan.check(one)
    assert any(c == "R1" and "declared action" in m for c, m in found)
    two = _hand([_shot(1, 0.0, 9.5, "wan", actions=["sweeps", "turns to the door"])], None, 9.5)
    assert not [c for c, _ in shotplan.check(two) if c == "R1"]
    short = _hand([_shot(1, 0.0, 5.5, "wan")], None, 5.5)
    assert not [c for c, _ in shotplan.check(short) if c == "R1"]


def test_planning_compute_counts_the_continuations_a_wan_shot_needs():
    """F15/M4: a 9.5 s Wan shot renders more than one 5.04 s clip, so its chain is two clips (or more)."""
    assert shotplan.chain_frames(1) == 121 and shotplan.chain_frames(2) == 241
    assert shotplan.clips_for(121) == 1 and shotplan.clips_for(122) == 2
    p = _plan()
    need = shotplan.wan_clips_needed(p)
    assert need == {3: 2, 9: 2}
    assert p["compute"]["wan_clips"] == 4
    from eav import colab_jobs, film
    assert (shotplan.CLIP_FRAMES, shotplan.FPS) == (colab_jobs.FILM_FRAMES, colab_jobs.FILM_FPS)
    assert shotplan.DISSOLVE_S == film.DISSOLVE_S


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


def _approved_film(tmp_path):
    film = tmp_path / "film-01"
    inp = shotplan.paths(film, "f01s014")["input"]
    inp.parent.mkdir(parents=True)
    inp.write_text(json.dumps({**FIX["input"], "timing": FIX["timing"]}), encoding="utf-8")
    sha = shotplan.input_sha256(inp)
    shotplan.write(film, shotplan.approve(_plan(), "claude", "reviewer", input_sha256=sha))
    return film, inp


def test_job_refuses_unapproved_scene(tmp_path):
    film = tmp_path / "film-01"
    with pytest.raises(shotplan.NotApproved, match="plan-shots"):
        shotplan.require_approved(film, "f01s014")
    shotplan.write(film, _plan())
    with pytest.raises(shotplan.NotApproved, match="approved"):
        shotplan.require_approved(film, "f01s014")
    film2, _ = _approved_film(tmp_path / "ok")
    shotplan.require_approved(film2, "f01s014")  # no raise
    assert (film2 / "shots" / "f01s014.av.md").is_file()


def test_approval_binds_to_the_input_content(tmp_path):
    film, inp = _approved_film(tmp_path)
    assert shotplan.require_approved(film, "f01s014")["approved"]["input_sha256"]
    inp.write_text(inp.read_text(encoding="utf-8") + " ", encoding="utf-8")  # input edited after approval
    with pytest.raises(shotplan.NotApproved, match="changed since approval"):
        shotplan.require_approved(film, "f01s014")


def test_approval_without_hash_or_input_is_refused(tmp_path):
    film = tmp_path / "film-01"
    shotplan.write(film, shotplan.approve(_plan(), "claude", "reviewer"))  # no hash
    with pytest.raises(shotplan.NotApproved, match="re-approve"):
        shotplan.require_approved(film, "f01s014")


def test_approved_plan_that_was_hand_edited_to_break_a_rule_is_refused(tmp_path):
    film, _ = _approved_film(tmp_path)
    f = shotplan.paths(film, "f01s014")["plan"]
    sp = json.loads(f.read_text(encoding="utf-8"))
    sp["shots"] = sp["shots"][:3]  # fewer shots than ceil(seconds / 6)
    f.write_text(json.dumps(sp), encoding="utf-8")
    with pytest.raises(shotplan.NotApproved, match="R2"):
        shotplan.require_approved(film, "f01s014")


def test_stills_job_refused_after_input_edit(tmp_path):
    root, run = _title(tmp_path)
    for extra in ([], ["--approve", "--by", "claude", "--reviewer", "rev"]):
        assert run("plan-shots", "--root", root, "--film", 1, "--scene", "f01s014", *extra)[0] == 0
    inp = root / "film" / "film-01" / "shots" / "f01s014.input.json"
    d = json.loads(inp.read_text(encoding="utf-8"))
    d["spine"] += " Changed."
    inp.write_text(json.dumps(d), encoding="utf-8")
    spec = tmp_path / "stills.json"
    spec.write_text(json.dumps({"scene": "f01s014", "items": [{"key": "a", "prompt": "a lamp", "seed": 1}]}), encoding="utf-8")
    rates = tmp_path / "r.json"
    rates.write_text(json.dumps({"stills": {"s_per_step": 10.0, "units_per_hour": 5.0, "steps": 4, "decode_s": 10, "export_s": 10}}))
    code, out = run("job", "stills", "--root", root, "--film", 1, "--rates", rates, "--spec", spec)
    assert code == 2 and "changed since approval" in out


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


def _wan_item(key, shot, w=1280, h=704):
    return {"key": key, "shot": shot, "image": "s.png", "width": w, "height": h, "seed": 1,
            "prompt": "A girl turns her face, static locked-off camera.", "continue_from": None}


def _chain(key, shot, w=1280, h=704):
    """A take and its continuation: the fixture's Wan shots (8 s and 9.5 s) need two chained clips (I3)."""
    return [_wan_item(key, shot, w, h), {**_wan_item(key + "-x", shot, w, h), "image": None, "continue_from": key}]


def test_film_clips_job_with_scene_key_needs_approval_but_a_pilot_spec_does_not(tmp_path):
    root, run = _title(tmp_path)
    art = tmp_path / "art"
    art.mkdir()
    (art / "s.png").write_bytes(b"png")
    rates = tmp_path / "r.json"
    rates.write_text(json.dumps({"film_clips": {"clip_s_hd": 900, "clip_s_hd_a100": 215, "clip_s_sd": 435,
                                                "units_per_hour_l4": 2.4, "units_per_hour_a100": 4.5,
                                                "decode_s": 900, "export_s": 120}}), encoding="utf-8")
    items = _chain("f01s014-03", 3) + _chain("f01s014-09", 9)
    spec = tmp_path / "clips.json"
    spec.write_text(json.dumps({"scene": "f01s014", "art_dir": str(art), "items": items}), encoding="utf-8")
    args = ("job", "film_clips", "--root", root, "--film", 1, "--rates", rates, "--spec", spec)
    code, out = run(*args)
    assert code == 2 and "no shot plan" in out and "plan-shots" in out
    assert not (root / "jobs").exists() or not list((root / "jobs").iterdir())
    assert run("plan-shots", "--root", root, "--film", 1, "--scene", "f01s014")[0] == 0
    code, out = run(*args)
    assert code == 2 and "not approved" in out
    assert run("plan-shots", "--root", root, "--film", 1, "--scene", "f01s014", "--approve", "--by", "claude", "--reviewer", "rev")[0] == 0
    code, out = run(*args)
    assert code == 0 and "Built film_clips job" in out, out
    pilot = [{k: v for k, v in _wan_item("pilot", 1).items() if k != "shot"}]
    spec.write_text(json.dumps({"art_dir": str(art), "items": pilot}), encoding="utf-8")  # pilot: no scene key
    code, out = run(*args, "--job-id", "film-clips-pilot")
    assert code == 0 and "Built film_clips job" in out, out


def test_film_clips_job_is_bound_to_the_approved_wan_shots(tmp_path):
    root, run = _title(tmp_path)
    art = tmp_path / "art"
    art.mkdir()
    (art / "s.png").write_bytes(b"png")
    rates = tmp_path / "r.json"
    rates.write_text(json.dumps({"film_clips": {"clip_s_hd": 900, "clip_s_hd_a100": 215, "clip_s_sd": 435,
                                                "units_per_hour_l4": 2.4, "units_per_hour_a100": 4.5,
                                                "decode_s": 900, "export_s": 120}}), encoding="utf-8")
    assert run("plan-shots", "--root", root, "--film", 1, "--scene", "f01s014")[0] == 0
    assert run("plan-shots", "--root", root, "--film", 1, "--scene", "f01s014", "--approve", "--by", "claude", "--reviewer", "rev")[0] == 0
    spec = tmp_path / "clips.json"

    def attempt(items, *extra):
        spec.write_text(json.dumps({"scene": "f01s014", "art_dir": str(art), "items": items}), encoding="utf-8")
        return run("job", "film_clips", "--root", root, "--film", 1, "--rates", rates, "--spec", spec, *extra)

    code, out = attempt(_chain("a", 3) + [_wan_item("b", 4)])              # shot 4 is a glide shot
    assert code == 2 and "shot 4" in out and "wan" in out
    code, out = attempt(_chain("a", 3) + _chain("b", 9, 896, 512))         # wrong resolution
    assert code == 2 and "1280x704" in out
    code, out = attempt(_chain("a", 3))                                    # wan shot 9 has no item
    assert code == 2 and "shot 9" in out
    code, out = attempt([{k: v for k, v in _wan_item("a", 3).items() if k != "shot"}] + _chain("b", 9))
    assert code == 2 and "shot" in out
    code, out = attempt([_wan_item("a", 3)] + _chain("b", 9))              # I3: one 5.04 s clip for an 8 s shot
    assert code == 2 and "continuation" in out and "shot 3" in out
    assert not (root / "jobs").exists() or not list((root / "jobs").iterdir())
    code, out = attempt(_chain("a", 3) + _chain("a2", 3) + _chain("b", 9))  # two takes of shot 3
    assert code == 0 and "Built film_clips job" in out, out
    assert "Split into 3 film_clips jobs" in out                           # I5: one Colab session each
    jobs = [j for j in cli._jobs(cli.Record.load(root)) if j["kind"] == "film_clips"]
    for j in jobs:
        with zipfile.ZipFile(j["inputs_zip"]) as z:
            job = json.loads(z.read("job.json"))
        keys = [i["key"] for i in job["items"]]
        assert all((k + "-x" in keys) == (k in keys) for k in ("a", "a2", "b"))   # a chain stays in one job
        assert json.loads(j["manifest"].read_text())["deadline_seconds"] <= colab_jobs.FILM_SESSION_S


def test_camera_carries_glide_extras_type_checked():
    scene = _scene()
    g = next(i for i in scene["shots"] if i["motion"] == "glide")
    g["camera"] = {**g["camera"], "zoom": -0.12, "zoom0": 1.17, "flat": True, "sweep": "down-left",
                   "drain": True, "pan_y": 4, "near_gain": 1.1}
    sp = shotplan.plan(scene, FIX["timing"], FIX["bible"])
    cam = next(s for s in sp["shots"] if s["camera"].get("zoom0"))["camera"]
    assert cam["zoom0"] == 1.17 and cam["flat"] is True and cam["sweep"] == "down-left"
    assert cam["drain"] is True and cam["pan_y"] == 4 and cam["near_gain"] == 1.1
    # a plain glide keeps exactly its four fields
    assert any(set(s["camera"]) == {"move", "zoom", "pan_x", "ease"} for s in sp["shots"] if s["motion"] == "glide")


@pytest.mark.parametrize("bad", [{"zoom0": "1.2"}, {"zoom0": 0}, {"flat": "yes"}, {"sweep": "up"},
                                 {"drain": 1}, {"pan_y": "x"}, {"near_gain": True}])
def test_camera_extras_are_type_checked(bad):
    scene = _scene()
    g = next(i for i in scene["shots"] if i["motion"] == "glide")
    g["camera"] = {**g["camera"], **bad}
    with pytest.raises(ValueError, match="camera"):
        shotplan.plan(scene, FIX["timing"], FIX["bible"])


def test_approved_plan_pull_back_renders_only_with_enough_zoom0(tmp_path):
    from unittest import mock
    from eav import film
    from PIL import Image
    scene = _scene()
    g = next(i for i in scene["shots"] if i["motion"] == "glide")
    g["camera"] = {**g["camera"], "zoom": -0.12, "zoom0": 1.17}
    sp = shotplan.plan(scene, FIX["timing"], FIX["bible"])
    shot = next(s for s in sp["shots"] if s["motion"] == "glide" and s["camera"]["zoom"] == -0.12)
    img = tmp_path / "i.png"
    Image.new("RGB", (64, 36)).save(img)

    def fake(image, depth, out, seconds, **kw):
        out.write_bytes(b"x")
        assert kw["zoom0"] == 1.17
        return {"frames": round(seconds * 24), "base_overscan": 1.03}
    with mock.patch("eav.glide.render", side_effect=fake):
        film.render_shot({**shot, "seconds": 2.0}, {"image": img, "depth": img}, tmp_path / "c")
        with pytest.raises(ValueError, match="edge band"):
            film.render_shot({**shot, "camera": {**shot["camera"], "zoom0": 1.16}, "seconds": 2.0},
                             {"image": img, "depth": img}, tmp_path / "c")
