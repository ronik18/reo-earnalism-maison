"""G1 adoption: already-imported media bound to one scene's approved shots, verified, recorded, 0 CU, idempotent."""
import hashlib
import io
import json
import subprocess
import unittest
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from eav import cli, film, shotplan
from eav.record import Record
from tests import test_cli

run = test_cli.run

WAN = "Wan-AI/Wan2.2-TI2V-5B-Diffusers"
DEPTH = "depth-anything/Depth-Anything-V2-Small-hf"
FLUX = "black-forest-labs/FLUX.1-schnell"


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def png_bytes(color, size=(320, 180)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def clip(path, size="896x512", frames=121):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=24:d=6",
                    "-frames:v", str(frames), "-pix_fmt", "yuv420p", str(path)], check=True)


def depth_png(path):
    Image.fromarray(np.tile(np.linspace(0, 65535, 320, dtype=np.uint16), (180, 1))).save(path)


class AdoptTests(unittest.TestCase):
    setUp0 = test_cli.CliTests.setUp
    init_and_plan = test_cli.CliTests.init_and_plan

    def setUp(self):
        self.setUp0()
        self.init_and_plan()
        self.sid = json.loads((self.root / "plan.json").read_text())["plan"]["films"][0]["scenes"][0]["scene_id"]
        self.approve()
        self.still_bytes = png_bytes((10, 120, 200))
        self.stills_job = self.imported("stills", {f"{self.sid}-1--c1.png": self.still_bytes,
                                                   f"{self.sid}-1--c2.png": png_bytes((200, 20, 20))},
                                        {"items": []}, model={"repo": FLUX})
        # a film_clips job eav imported: a depth map made from exactly the picked still
        d = self.d / "depth.png"
        depth_png(d)
        self.depth_job = self.imported("film_clips", {"depth/door.depth.png": d.read_bytes()},
                                       {"items": [], "depth_stills": {"door.png": hashlib.sha256(self.still_bytes).hexdigest()}},
                                       model={"repo": WAN, "depth_repo": DEPTH})
        self.pilot = self.pilot_folder()
        self.spec = self.d / "adopt.json"

    # ------------------------------------------------------------------ fixtures
    def approve(self):
        """Scene 1: shot 1 a layered glide (a still and its depth map), shot 2 a Wan shot of 5.3 s (a two-clip chain)."""
        plan = json.loads((self.root / "plan.json").read_text())
        sc = plan["plan"]["films"][0]["scenes"][0]
        import re
        clauses = [c.strip() for c in re.split(r"(?<=[.])\s+|\n\n", sc["text"]) if c.strip()]
        k = len(clauses)
        spans = [(i * 5.5 / (k - 1) + (0.3 if i else 0.0), (i + 1) * 5.5 / (k - 1)) for i in range(k - 1)] + [(6.2, 11.5)]
        timing = [{"start": round(a, 3), "end": round(b, 3), "text": t} for (a, b), t in zip(spans, clauses)]
        shot = lambda b, tr, **kw: {"beats": b, "subject": "a room", "framing": "wide", "layer": "present",
                                    "transition_in": tr, "bible_refs": [], "sound": {"sfx": [], "music": None}, **kw}
        inp = {"spine": "s", "fidelity": "f", "motifs": ["m"], "timing": timing, "peak": {"shot": 2, "at": 9.0},
               "shots": [shot([0, k - 2], "cut", motion="glide",
                              camera={"move": "push", "zoom": 0.08, "pan_x": 0, "ease": "both"}),
                         shot([k - 1, k - 1], "dissolve", motion="wan", wan_res="896x512", plants=[1],
                              actions=["she turns", "she looks"])]}
        fdir = self.root / "film" / "film-01"
        paths = shotplan.paths(fdir, sc["scene_id"])
        paths["dir"].mkdir(parents=True, exist_ok=True)
        paths["input"].write_text(json.dumps(inp), encoding="utf-8")
        sp = shotplan.plan({**inp, "scene_id": sc["scene_id"], "text": sc["text"]}, timing, {"characters": {}})
        shotplan.write(fdir, shotplan.approve(sp, "claude", "reviewer", input_sha256=shotplan.input_sha256(paths["input"])))

    def imported(self, kind, files, job, model):
        """A job eav imported: its inputs.zip (job.json), its outputs and their recorded sha256, accepted."""
        rec = Record.load(self.root)
        job_id = f"{kind.replace('_', '-')}-{len(rec.data['artifacts']):04d}"
        jdir = self.root / "jobs" / job_id
        jdir.mkdir(parents=True)
        with zipfile.ZipFile(jdir / "inputs.zip", "w") as z:
            z.writestr("job.json", json.dumps({"job_id": job_id, "kind": kind, **job}))
        (jdir / "build-manifest.json").write_text("{}")
        (jdir / "nb.ipynb").write_text("{}")
        rec.add_artifact("colab_job", jdir / "nb.ipynb", {
            "job_id": job_id, "job_kind": kind, "forecast_units": 0.0, "month": "2026-11",
            "inputs_zip": f"jobs/{job_id}/inputs.zip", "manifest": f"jobs/{job_id}/build-manifest.json"})
        rec.event("cli", "job_target", {"job_id": job_id, "target": "film-01", "kind": kind})
        out = self.root / kind / job_id
        for name, data in files.items():
            p = out / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            rec.add_artifact(kind, p, {"job_id": job_id, "job_kind": kind, "model": model, "packages": {"x": "1"}})
        rec.event("import", "accepted", {"job_id": job_id, "kind": kind, "actual_units": 0.5})
        return job_id

    def pilot_folder(self):
        """A pilot "motion" job eav never imported: inputs.zip, its notebook and its own outputs manifest (COMPLETE)."""
        folder = self.d / "pilot" / "motion-pilot9"
        out = folder / "out"
        out.mkdir(parents=True)
        start = png_bytes((90, 90, 40), (896, 512))
        items = [{"key": f"{self.sid}-2a", "image": "start.png", "width": 896, "height": 512, "seed": 1},
                 {"key": f"{self.sid}-2b", "image": None, "width": 896, "height": 512, "seed": 2,
                  "continue_from": f"{self.sid}-2a"}]
        with zipfile.ZipFile(folder / "inputs.zip", "w") as z:
            z.writestr("job.json", json.dumps({"job_id": "motion-pilot9", "kind": "motion", "items": items}))
            z.writestr("start.png", start)
        (folder / "motion.ipynb").write_text(json.dumps({"cells": [{"source": f"DEPTH = '{DEPTH}'"}]}))
        for it in items:
            clip(out / f"{it['key']}.mp4")
        (self.d / "art").mkdir()
        (self.d / "art" / "start-copy.png").write_bytes(start)
        outputs = {p.name: sha(p) for p in sorted(out.iterdir())}
        (out / "manifest.json").write_text(json.dumps({
            "schema": "earnalism.audiovisual-outputs.v1", "job_id": "motion-pilot9", "kind": "motion",
            "status": "COMPLETE", "input_zip_sha256": sha(folder / "inputs.zip"),
            "model": {"repo": WAN, "licence": "apache-2.0"}, "packages": {"diffusers": "0.37.0"}, "outputs": outputs}))
        return folder

    def write_spec(self, **parts):
        self.spec.write_text(json.dumps({"scene": self.sid, "sources": {"motion-pilot9": {"folder": "pilot/motion-pilot9"}},
                                         **parts}), encoding="utf-8")

    def full_spec(self):
        s = self.sid
        self.write_spec(
            stills={f"{s}-1": {"job": self.stills_job, "file": f"{s}-1--c1.png"}},
            depth={f"{s}-1": {"job": self.depth_job, "file": "door.depth.png"}},
            clips={"2": {"job": "motion-pilot9", "takes": [f"{s}-2a", f"{s}-2b"],
                         "art": {"file": "art/start-copy.png", "reason": "the owner's start still, copied by hand"}}})

    def adopt(self):
        return run("adopt", "--root", self.root, "--spec", self.spec)

    def adopted_jobs(self):
        return [j for j in cli._jobs(Record.load(self.root)) if j["adopted"]]

    # ------------------------------------------------------------------ tests
    def test_adopts_a_clip_chain_a_still_and_its_depth_map_into_the_scene_flow(self):
        ledger_before = self.ledger.read_bytes() if self.ledger.exists() else None
        self.full_spec()
        code, out = self.adopt()
        self.assertEqual(code, 0, out)
        rec = Record.load(self.root)
        s = self.sid
        picks = cli._scene_picks(rec, "film-01", s)                  # where film --shots reads stills
        self.assertEqual(picks[f"{s}-1"]["sha256"], hashlib.sha256(self.still_bytes).hexdigest())
        items = cli._film_clip_items(rec, "film-01")                  # where pick_wan_clips reads takes
        chain = film.pick_wan_clips([c["item"] for c in items.values()], s, 2)
        self.assertEqual(chain, [f"{s}-2a", f"{s}-2b"])
        maps = cli._depth_maps(rec, "film-01")                        # where glides read depth maps
        self.assertIn((f"{s}-1.png", picks[f"{s}-1"]["sha256"]), maps)
        for k in chain:                                               # gated on adoption: a verdict is on record
            mj = self.root / "film_clips" / items[k]["job_id"] / "clips" / f"{k}.motion.json"
            self.assertTrue(mj.is_file())
            self.assertIn(mj.relative_to(self.root).as_posix(),
                          [a["path"] for a in rec.data["artifacts"] if a["kind"] == "motion_gate"])
        doc = json.loads(next(j for j in self.adopted_jobs() if j["kind"] == "film_clips")["adoption"].read_text())
        self.assertEqual(doc["spent_cu"], 0)
        self.assertEqual(doc["binding"]["clips"]["2"]["licence"], {"model": WAN, "licence": "Apache-2.0"})
        self.assertEqual(doc["binding"]["clips"]["2"]["source"]["origin"], "folder")
        self.assertEqual(doc["binding"]["depth"][f"{s}-1"]["licence"]["model"], DEPTH)
        self.assertIn("identical to the start image", doc["binding"]["clips"]["2"]["art"]["relation"])
        self.assertEqual((self.ledger.read_bytes() if self.ledger.exists() else None), ledger_before)   # 0 CU
        voice = self.root / "film" / "film-01" / "voice" / f"{s}.wav"   # the scene's voice is in place
        voice.parent.mkdir(parents=True, exist_ok=True)
        voice.write_bytes(b"RIFF")
        nxt = cli.next_action(self.root, s)
        self.assertIn("music.json", nxt)                              # stills, takes and depth are bound

    def test_readoption_is_a_no_op(self):
        self.full_spec()
        self.assertEqual(self.adopt()[0], 0)
        before = (self.root / "record.json").read_bytes()
        code, out = self.adopt()
        self.assertEqual(code, 0, out)
        self.assertIn("Already adopted", out)
        self.assertEqual((self.root / "record.json").read_bytes(), before)

    def test_sha_mismatch_is_refused_and_nothing_is_written(self):
        self.full_spec()
        (self.root / "stills" / self.stills_job / f"{self.sid}-1--c1.png").write_bytes(png_bytes((1, 2, 3)))
        before = (self.root / "record.json").read_bytes()
        code, out = self.adopt()
        self.assertEqual(code, 2, out)
        self.assertIn("sha256", out)
        self.assertIn("not the file the job made", out)
        self.assertEqual((self.root / "record.json").read_bytes(), before)
        self.assertFalse(self.adopted_jobs())

    def test_pilot_folder_whose_manifest_does_not_match_is_refused(self):
        self.full_spec()
        clip(self.pilot / "out" / f"{self.sid}-2b.mp4", frames=100)        # not the take the manifest names
        code, out = self.adopt()
        self.assertEqual(code, 2, out)
        self.assertIn("differs from the", out)
        self.assertFalse(self.adopted_jobs())

    def test_a_depth_map_of_another_image_is_refused(self):
        s = self.sid
        self.write_spec(stills={f"{s}-1": {"job": self.stills_job, "file": f"{s}-1--c2.png"}},
                        depth={f"{s}-1": {"job": self.depth_job, "file": "door.depth.png"}})
        code, out = self.adopt()
        self.assertEqual(code, 2, out)
        self.assertIn("no depth map matches it", out)
        self.assertFalse(self.adopted_jobs())
        # the still alone adopts; its glide still refuses at assembly, as before, for want of a depth map
        self.write_spec(stills={f"{s}-1": {"job": self.stills_job, "file": f"{s}-1--c2.png"}})
        code, out = self.adopt()
        self.assertEqual(code, 0, out)
        self.assertIn("have no depth map yet", out)
        rec = Record.load(self.root)
        shot = next(x for x in shotplan.require_approved(self.root / "film" / "film-01", s)["shots"] if x["n"] == 1)
        stills_dir, _ = cli._cinematic_stills(rec, "film-01", [(s, {"shots": [shot]}, None)], self.d / "out")
        with self.assertRaises(cli.Stop) as stop:
            cli._shot_assets(rec, "film-01", s, shot, {}, {}, stills_dir, cli._depth_maps(rec, "film-01"))
        self.assertIn("has no depth map", str(stop.exception))

    def test_hand_copied_file_needs_a_reason_and_its_provenance_is_traced(self):
        s = self.sid
        copy = self.d / "art" / "eye.png"
        copy.write_bytes(self.still_bytes)                                   # a hand copy of the job's c1
        self.write_spec(stills={f"{s}-1": {"file": "art/eye.png"}})
        code, out = self.adopt()
        self.assertEqual(code, 2, out)
        self.assertIn("needs the operator's \"reason\"", out)
        self.assertFalse(self.adopted_jobs())
        self.write_spec(stills={f"{s}-1": {"file": "art/eye.png", "reason": "owner-picked, corrected eye"}})
        code, out = self.adopt()
        self.assertEqual(code, 0, out)
        doc = json.loads(self.adopted_jobs()[0]["adoption"].read_text())
        hand = doc["binding"]["stills"][f"{s}-1"]
        self.assertEqual(hand["hand_copied"]["sha256"], hashlib.sha256(self.still_bytes).hexdigest())
        self.assertEqual(hand["hand_copied"]["reason"], "owner-picked, corrected eye")
        self.assertIn({"job_id": self.stills_job, "file": f"{s}-1--c1.png", "relation": "identical to the job's output"},
                      hand["hand_copied"]["traced"])
        self.assertEqual(hand["licence"]["model"], FLUX)

    def stills_of_shot_1(self):
        rec = Record.load(self.root)
        sp = shotplan.require_approved(self.root / "film" / "film-01", self.sid)
        shot = next(x for x in sp["shots"] if x["n"] == 1)
        return lambda: cli._cinematic_stills(Record.load(self.root), "film-01", [(self.sid, {"shots": [shot]}, None)],
                                             self.d / "out")

    def test_untraced_hand_copy_needs_a_gate_reason_and_blocks_release(self):
        """I2: an untraced hand copy has no gate verdict and no verified licence: film --shots refuses it until a
        reason is recorded, and then carries its licence (None) as a release blocker."""
        s = self.sid
        (self.d / "art" / "lane.png").write_bytes(png_bytes((5, 5, 60)))
        self.write_spec(stills={f"{s}-1": {"file": "art/lane.png", "reason": "night lane used in the pilots"}})
        code, out = self.adopt()
        self.assertEqual(code, 0, out)
        self.assertIn("licence unverified", out)
        stills = self.stills_of_shot_1()
        with self.assertRaises(cli.Stop) as stop:
            stills()
        self.assertIn("never enter the film ungated", str(stop.exception))
        (self.root / "picks" / "gate-overrides.json").write_text(json.dumps({f"{s}-1": "owner viewed it at full size"}))
        _, info = stills()
        self.assertEqual(info["gate_overrides"], {f"{s}-1": "owner viewed it at full size"})
        self.assertEqual([(b["key"], b["licence"]) for b in info["release_blockers"]], [(f"{s}-1", None)])
        self.assertEqual([b["key"] for b in cli._release_blockers(Record.load(self.root))], [f"{s}-1"])

    def test_declared_derivation_inherits_only_a_verified_source_licence_with_a_warning(self):
        s = self.sid
        (self.d / "art" / "touched.png").write_bytes(png_bytes((11, 121, 201)))     # a hand touch-up of c1
        entry = {"file": "art/touched.png", "reason": "lettering painted out by hand",
                 "from": {"job": self.stills_job, "file": f"{s}-1--c1.png"}}
        self.write_spec(stills={f"{s}-1": entry})
        src = self.root / "stills" / self.stills_job / f"{s}-1--c1.png"
        src.write_bytes(png_bytes((1, 1, 1)))                                        # the source no longer verifies
        code, out = self.adopt()
        self.assertEqual(code, 2, out)
        self.assertIn("not the file the job made", out)
        src.write_bytes(self.still_bytes)
        code, out = self.adopt()
        self.assertEqual(code, 0, out)
        self.assertIn(f"inherited from {self.stills_job}/{s}-1--c1.png", out)
        b = json.loads(self.adopted_jobs()[0]["adoption"].read_text())["binding"]["stills"][f"{s}-1"]
        self.assertEqual(b["licence"]["model"], FLUX)
        self.assertIn("not verified", b["hand_copied"]["declared_from"]["relation"])
        with self.assertRaises(cli.Stop):                                            # no gate verdict of its own
            self.stills_of_shot_1()()
        self.assertEqual(cli._release_blockers(Record.load(self.root)), [])           # its licence is the source's

    def test_adoption_needs_the_approved_paper_edit(self):
        fdir = self.root / "film" / "film-01"
        sp = json.loads((fdir / "shots" / f"{self.sid}.json").read_text())
        sp.pop("approved", None)
        (fdir / "shots" / f"{self.sid}.json").write_text(json.dumps(sp))
        self.full_spec()
        code, out = self.adopt()
        self.assertEqual(code, 2, out)
        self.assertIn("plan-shots", out)

    # ------------------------------------------------------------------ still touch-ups bound to a shot
    def dotted_job(self, model):
        """An imported stills job whose shot-1 candidate has a red dot a touch-up can paint out."""
        img = np.zeros((180, 320, 3), np.uint8)
        img[:] = (10, 120, 200)
        img[50:56, 100:106] = (220, 20, 30)
        buf = io.BytesIO()
        Image.fromarray(img).save(buf, format="PNG")
        return self.imported("stills", {f"{self.sid}-1--c1.png": buf.getvalue()}, {"items": []}, model=model)

    def touch(self, job, job_id="touchup-shot1", scene=None):
        spec = self.d / f"{job_id}.json"
        spec.write_text(json.dumps({**({"scene": scene} if scene else {}), "items": [
            {"key": f"{self.sid}-1", "source": {"job": job, "file": f"{self.sid}-1--c1.png"},
             "ops": [{"op": "inpaint", "box": [95, 45, 111, 61], "radius": 5}]}]}), encoding="utf-8")
        return run("touchup", "--root", self.root, "--film", 1, "--spec", spec, "--job-id", job_id)

    def test_scene_bound_touchup_pick_binds_the_shot_with_the_inherited_licence(self):
        s, job = self.sid, self.dotted_job({"repo": FLUX})
        code, out = self.touch(job, scene=s)
        self.assertEqual(code, 0, out)
        self.assertIn(f"inherited from stills/{job}/{s}-1--c1.png (verified)", out)
        rec = Record.load(self.root)
        row = next(j for j in cli._jobs(rec) if j["job_id"] == "touchup-shot1")
        self.assertEqual(row["scene"], s)
        self.assertEqual(cli._job_json(row), {})                       # a local job: no inputs.zip, no crash
        man = json.loads((self.root / "jobs" / "touchup-shot1" / "touchup-manifest.json").read_text())
        self.assertEqual((man["scene"], man["items"][0]["licence"]), (s, {"model": FLUX, "licence": "Apache-2.0"}))
        self.assertFalse(cli._job_gated(rec, "touchup-shot1"))          # provenance, never a gate verdict
        choices = self.d / "choices.json"
        choices.write_text(json.dumps({f"{s}-1": 1}))
        code, out = run("pick", "--root", self.root, "--job", "touchup-shot1", "--choices", choices)
        self.assertEqual(code, 0, out)
        picks = cli._scene_picks(Record.load(self.root), "film-01", s)  # where film --shots reads stills
        self.assertEqual(picks[f"{s}-1"]["job_id"], "touchup-shot1")
        self.assertEqual(picks[f"{s}-1"]["sha256"], sha(self.root / "touchup" / "touchup-shot1" / f"{s}-1--c1.png"))

    def test_scene_bound_touchup_needs_a_key_of_the_scene_and_the_approved_plan(self):
        job = self.dotted_job({"repo": FLUX})
        before = (self.root / "record.json").read_bytes()
        code, out = self.touch(job, scene="f01s999")
        self.assertEqual(code, 2, out)
        self.assertEqual((self.root / "record.json").read_bytes(), before)
        self.assertFalse((self.root / "touchup").exists())

    def test_touchup_output_is_adopted_by_hand_copy_with_the_source_licence(self):
        """The 7-c1 route inside one root: a touch-up's output traced to its job, no crash on the job's missing
        inputs.zip, the licence inherited from the verified source still, no gate verdict of its own."""
        s, job = self.sid, self.dotted_job({"repo": FLUX})
        self.assertEqual(self.touch(job)[0], 0)
        (self.d / "art" / "touched.png").write_bytes(
            (self.root / "touchup" / "touchup-shot1" / f"{s}-1--c1.png").read_bytes())
        self.write_spec(stills={f"{s}-1": {"file": "art/touched.png", "reason": "dot painted out (touch-up)",
                                           "from": {"job": job, "file": f"{s}-1--c1.png"}}})
        code, out = self.adopt()
        self.assertEqual(code, 0, out)
        self.assertIn("inherited from touchup-shot1", out)
        b = json.loads(self.adopted_jobs()[0]["adoption"].read_text())["binding"]["stills"][f"{s}-1"]
        self.assertEqual(b["licence"], {"model": FLUX, "licence": "Apache-2.0"})
        self.assertEqual(b["hand_copied"]["traced"][0]["job_id"], "touchup-shot1")
        self.assertTrue(cli._ungated_copy(b))                         # film --shots needs a recorded reason
        self.assertEqual(cli._release_blockers(Record.load(self.root)), [])
        self.assertEqual(cli._scene_picks(Record.load(self.root), "film-01", s)[f"{s}-1"]["sha256"],
                         sha(self.d / "art" / "touched.png"))

    def test_touchup_of_an_unverified_source_is_refused(self):
        s, job = self.sid, self.dotted_job({})                       # no model licence on record
        before = (self.root / "record.json").read_bytes()
        code, out = self.touch(job, scene=s)                         # bound to a scene: refused, nothing written
        self.assertEqual(code, 2, out)
        self.assertIn("unverified source", out)
        self.assertEqual((self.root / "record.json").read_bytes(), before)
        code, out = self.touch(job)                                  # unbound: made, with a warning
        self.assertEqual(code, 0, out)
        self.assertIn("cannot be bound to a scene or adopted", out)
        (self.d / "art" / "touched.png").write_bytes(
            (self.root / "touchup" / "touchup-shot1" / f"{s}-1--c1.png").read_bytes())
        self.write_spec(stills={f"{s}-1": {"file": "art/touched.png", "reason": "dot painted out (touch-up)"}})
        before = (self.root / "record.json").read_bytes()
        code, out = self.adopt()
        self.assertEqual(code, 2, out)
        self.assertIn("unverified source", out)
        self.assertEqual((self.root / "record.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
