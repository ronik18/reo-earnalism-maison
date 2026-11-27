"""rebase-source: a corrected revision of the same edition moves the title root in place."""
import copy
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from eav import cli
from eav.record import Record
from tests.test_cli import RATES, SOURCE, RoundTwo, run

NEW_TEXT = {
    2: "Every afternoon the children did not play in the garden. It was large and lovely.",
    3: "The giant came back. He had not been away for seven years.",
}


def corrected(**over):
    """SOURCE as a corrected revision: every unit and anchor id changed, paragraphs 2 and 3 fixed."""
    src = copy.deepcopy(SOURCE)
    src.update(revision_id="r-2", content_sha256="d" * 64)
    n = 0
    for u in src["units"]:
        u["unit_id"] = "v" + u["unit_id"][1:]
        for p in u["paragraphs"]:
            n += 1
            p["anchor_id"] = f"b{n}"
            p["text"] = NEW_TEXT.get(n, p["text"])
    src.update(over)
    return src


class RebaseSourceTests(unittest.TestCase):
    fake_job, wav, film_ready = RoundTwo.fake_job, RoundTwo.wav, RoundTwo.film_ready  # not its tests

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = Path(tmp.name)
        self.root = self.d / "titles" / "selfish-giant"
        self.ledger = self.d / "titles" / "allowance-ledger.json"
        self.src = self.d / "selfish-giant.json"
        self.src.write_text(json.dumps(SOURCE), encoding="utf-8")
        self.rates = self.d / "rates.json"
        self.rates.write_text(json.dumps(RATES), encoding="utf-8")
        self.new = self.d / "source-r-2.json"
        self.new.write_text(json.dumps(corrected()), encoding="utf-8")

    def init_and_plan(self):
        self.assertEqual(run("init", self.src, "--root", self.root)[0], 0)
        self.assertEqual(run("plan", "--root", self.root)[0], 0)

    def rebase(self, path=None):
        return run("rebase-source", path or self.new, "--root", self.root, "--reason", "scan fix")

    def plan(self):
        return json.loads((self.root / "plan.json").read_text(encoding="utf-8"))

    def events(self):
        return Record.load(self.root).data["events"]

    # --- happy path ---------------------------------------------------------------------------
    def test_two_paragraph_change_rebases_source_record_and_plan(self):
        self.init_and_plan()
        old_plan = self.plan()
        old_bytes = (self.root / "source.json").read_bytes()
        code, out = self.rebase()
        self.assertEqual(code, 0, out)
        self.assertIn("2 paragraph(s) changed (¶2, ¶3)", out)
        self.assertIn("Stills and music kept", out)
        self.assertIn("job narration", out.split("Next:")[-1])
        # source.json is the new export; the old one is kept by its revision id
        self.assertEqual(json.loads((self.root / "source.json").read_text())["revision_id"], "r-2")
        self.assertEqual((self.root / "source.json").read_bytes(), self.new.read_bytes())
        self.assertEqual((self.root / "source-r-1.json").read_bytes(), old_bytes)
        rec = Record.load(self.root)
        s = rec.data["source"]
        self.assertEqual((s["revision_id"], s["content_sha256"], s["edition_id"]),
                         ("r-2", "d" * 64, "e-1"))
        ev = [e for e in rec.data["events"] if e["stage"] == "rebase_source"][-1]["detail"]
        self.assertEqual((ev["old_revision_id"], ev["new_revision_id"]), ("r-1", "r-2"))
        self.assertEqual((ev["old_content_sha256"], ev["new_content_sha256"]), ("c" * 64, "d" * 64))
        self.assertEqual([c["ordinal"] for c in ev["changed_paragraphs"]], [2, 3])
        self.assertEqual(ev["changed_paragraphs"][1]["new_text"], NEW_TEXT[3])
        self.assertEqual(ev["changed_paragraphs"][1]["old_text"], SOURCE["units"][1]["paragraphs"][0]["text"])
        self.assertEqual(ev["anchor_mapping"][1], {
            "unit": 2, "old_unit_id": "u-2", "new_unit_id": "v-2",
            "paragraphs": [{"position": 1, "ordinal": 3, "old_anchor_id": "a3", "new_anchor_id": "b3"}]})
        kinds = {a["kind"] for a in rec.data["artifacts"]}
        self.assertTrue({"source_previous", "source_rebase"} <= kinds)
        diff = json.loads(next((self.root / "rebases").glob("*.json")).read_text())
        self.assertEqual(diff["new_revision_id"], "r-2")
        # plan: ids mapped by position, text refreshed, structure and still keys unchanged
        new_plan = self.plan()
        old_sc = old_plan["plan"]["films"][0]["scenes"]
        new_sc = new_plan["plan"]["films"][0]["scenes"]
        self.assertEqual([(s["scene_id"], s["keyframes"], len(s["blocks"])) for s in old_sc],
                         [(s["scene_id"], s["keyframes"], len(s["blocks"])) for s in new_sc])
        self.assertEqual(new_plan["plan"]["films"][0]["unit_ids"], ["v-1", "v-2"])
        anchors = [a for s in new_sc for a in s["anchor_ids"]]
        self.assertEqual(sorted(set(anchors)), ["b1", "b2", "b3"])
        dumped = json.dumps(new_plan)
        for old_id in ("a1", "a2", "a3", "u-1", "u-2"):
            self.assertNotIn(f'"{old_id}"', dumped)
        self.assertIn("did not play", dumped)
        self.assertIn("had not been away", dumped)
        changed = [s["scene_id"] for s in new_sc if s["text"] != next(
            o["text"] for o in old_sc if o["scene_id"] == s["scene_id"])]
        self.assertEqual(ev["plan_changed_scenes"], changed)
        self.assertTrue(ev["plan_changed_voice_units"])
        self.assertTrue(all(k.split("-")[0] in changed for k in ev["plan_changed_voice_units"]))
        code, out = run("status", "--root", self.root)
        self.assertIn("stills and music are kept", out)
        self.assertIn("job narration", out.split("Next:")[-1])
        # the rebuild is the usual job narration, from the refreshed plan
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates)
        self.assertEqual(code, 0, out)
        job_zip = next(self.root.glob("jobs/narration-*/inputs.zip"))
        units = json.loads(zipfile.ZipFile(job_zip).read("job.json"))["units"]
        self.assertTrue(any("did not play" in u["text"] for u in units))
        self.assertFalse(any("children played" in u["text"] for u in units))

    def test_old_never_run_narration_job_is_superseded(self):
        self.init_and_plan()
        code, out = run("job", "narration", "--root", self.root, "--rates", self.rates)
        self.assertEqual(code, 0, out)
        old_id = json.loads(self.ledger.read_text())[0]["job_id"]
        code, out = self.rebase()
        self.assertEqual(code, 0, out)
        self.assertIn(f"Superseded never-run narration from the old text: {old_id}", out)
        done = [e["detail"] for e in self.events() if e["result"] == "superseded"]
        self.assertEqual(done, [{"job_id": old_id, "reason": "source rebased to r-2"}])
        entry = json.loads(self.ledger.read_text())[0]
        self.assertEqual((entry["state"], entry["units"]), ("settled", 0))
        ev = [e for e in self.events() if e["stage"] == "rebase_source"][-1]["detail"]
        self.assertEqual(ev["superseded_narration_jobs"], [old_id])
        self.assertIn("job narration", run("status", "--root", self.root)[1].split("Next:")[-1])

    # --- imported media -----------------------------------------------------------------------
    def test_imported_narration_is_stale_and_film_refuses_it_while_stills_and_music_stay(self):
        self.film_ready()  # imported narration and stills from the old text

        def cues(rec, job_id, job_dir, out):
            self.wav(out / "cue-1.wav", 1)

        music = self.fake_job("music", "film-01", cues)
        rec = Record.load(self.root)
        narr = cli._latest_job(rec, "narration", "film-01")["job_id"]
        have_before, _ = cli._stills_view(rec, "film-01")
        code, out = self.rebase()
        self.assertEqual(code, 0, out)
        self.assertIn(f"Imported narration now stale (film refuses it): {narr}", out)
        rec = Record.load(self.root)
        self.assertIsNone(cli._latest_job(rec, "narration", "film-01"))
        have, missing = cli._stills_view(rec, "film-01")
        self.assertEqual((sorted(have), missing), (sorted(have_before), []))
        self.assertTrue(cli._find(rec, music)["imported"])
        self.assertEqual(cli._score_route(rec, f"ace-step:{music}"), f"ace-step:{music}")
        code, out = run("status", "--root", self.root)
        self.assertIn(f"{narr} narration film-01: imported but STALE", out)
        self.assertIn("stills and music are kept", out)
        self.assertIn("job narration", out.split("Next:")[-1])
        code, out = run("film", "--root", self.root, "--logo", self.d / "logo.png",
                        "--end-card", self.d / "end.png", "--score-route", "vcsl")
        self.assertEqual(code, 2, out)
        self.assertIn(f"imported narration {narr} is stale", out)
        self.assertIn("job narration", out)
        # narration rebuilt from the corrected text becomes current
        scenes = self.plan()["plan"]["films"][0]["scenes"]
        from eav.voice import voice_units

        def narr2(rec, job_id, job_dir, out):
            for sc in scenes:
                for u in voice_units(sc, {"description": ""}, None, "en"):
                    self.wav(out / f"{u['unit_key']}.wav", 1)

        new_id = self.fake_job("narration", "film-01", narr2)
        self.assertEqual(cli._latest_job(Record.load(self.root), "narration", "film-01")["job_id"], new_id)
        self.assertIn("film --root", cli.next_action(self.root))

    # --- refusals -----------------------------------------------------------------------------
    def assert_refused(self, src, needle):
        before = (self.root / "source.json").read_bytes(), self.plan(), len(self.events())
        path = self.d / "bad.json"
        path.write_text(json.dumps(src) if isinstance(src, dict) else src, encoding="utf-8")
        code, out = self.rebase(path)
        self.assertEqual(code, 2, out)
        self.assertIn(needle, out)
        self.assertEqual(((self.root / "source.json").read_bytes(), self.plan(), len(self.events())),
                         before)
        self.assertFalse((self.root / "source-r-1.json").exists())
        return out

    def test_refuses_a_different_edition(self):
        self.init_and_plan()
        out = self.assert_refused(corrected(edition_id="e-2"), "same edition")
        self.assertIn("new title root", out)

    def test_refuses_a_different_paragraph_count(self):
        self.init_and_plan()
        src = corrected()
        src["units"][1]["paragraphs"].append({"anchor_id": "b4", "kind": "paragraph", "text": "More."})
        out = self.assert_refused(src, "paragraph")
        self.assertIn("new title root", out)

    def test_refuses_a_different_language(self):
        self.init_and_plan()
        self.assert_refused(corrected(language="bn"), "new title root")

    def test_refuses_an_invalid_export(self):
        self.init_and_plan()
        self.assert_refused(corrected(content_sha256="not-a-sha"), "no cleared source")
        self.assert_refused(corrected(public_domain_evidence=False), "public-domain")
        self.assert_refused("{not json", "no cleared source")

    def test_refuses_the_same_revision(self):
        self.init_and_plan()
        self.assert_refused(SOURCE, "already on revision")


if __name__ == "__main__":
    unittest.main()
