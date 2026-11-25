import hashlib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from eav.record import SCHEMA, Record, sha256_file


def make(root):
    return Record.create(root, "demo-title", {"content_sha256": "abc123", "path": "book.md"})


class RecordTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_create_then_load_roundtrip(self):
        rec = make(self.root)
        loaded = Record.load(self.root)
        self.assertEqual(rec.data, loaded.data)
        self.assertEqual(loaded.data["schema"], "earnalism.audiovisual_record.v1")
        self.assertEqual(SCHEMA, loaded.data["schema"])
        self.assertEqual(loaded.data["source"]["content_sha256"], "abc123")

    def test_add_artifact_hashes_bytes(self):
        rec = make(self.root)
        f = self.root / "out" / "a.bin"
        f.parent.mkdir()
        f.write_bytes(b"hello bytes")
        art = rec.add_artifact("audio", f, {"k": 1})
        self.assertEqual(art["sha256"], hashlib.sha256(b"hello bytes").hexdigest())
        self.assertEqual(art["sha256"], sha256_file(f))
        self.assertEqual(art["bytes"], 11)
        self.assertEqual(art["kind"], "audio")
        self.assertEqual(art["meta"], {"k": 1})
        self.assertEqual(Record.load(self.root).data["artifacts"][-1], art)

    def test_add_artifact_rejects_path_outside_root(self):
        rec = make(self.root)
        with tempfile.NamedTemporaryFile() as outside:
            with self.assertRaises(ValueError):
                rec.add_artifact("audio", Path(outside.name), {})

    def test_events_append_only(self):
        rec = make(self.root)
        rec.event("tts", "ok", {"n": 1})
        rec.event("mix", "fail", {"n": 2})
        events = Record.load(self.root).data["events"]
        self.assertEqual([e["stage"] for e in events], ["tts", "mix"])
        self.assertEqual([e["result"] for e in events], ["ok", "fail"])
        for e in events:
            datetime.fromisoformat(e["at"])


if __name__ == "__main__":
    unittest.main()


def _append_events(root, tag, n):
    rec = Record.load(root)
    for i in range(n):
        rec.event("race", "ok", {"tag": tag, "i": i})


class RecordMergeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_stale_instance_does_not_drop_other_commands_entries(self):
        make(self.root)
        a = Record.load(self.root)
        b = Record.load(self.root)
        f = self.root / "b.bin"
        f.write_bytes(b"bb")
        b.add_artifact("still", f, {"k": 1})
        b.event("job", "stills", {"x": 1})
        a.event("film", "done", {"y": 2})
        final = Record.load(self.root).data
        self.assertEqual([x["kind"] for x in final["artifacts"]], ["still"])
        self.assertEqual([e["stage"] for e in final["events"]], ["job", "film"])
        self.assertEqual(a.data, final)  # refreshed from the merged result

    def test_two_processes_append_concurrently(self):
        import multiprocessing as mp
        make(self.root)
        ps = [mp.Process(target=_append_events, args=(self.root, t, 50)) for t in ("p", "q")]
        for p in ps:
            p.start()
        for p in ps:
            p.join(120)
            self.assertEqual(p.exitcode, 0)
        ev = Record.load(self.root).data["events"]
        self.assertEqual(len(ev), 100)
        self.assertEqual({(e["detail"]["tag"], e["detail"]["i"]) for e in ev},
                         {(t, i) for t in ("p", "q") for i in range(50)})

    def test_top_level_change_kept_and_rollback_removes_only_own(self):
        rec = make(self.root)
        other = Record.load(self.root)
        other.event("job", "x", {})
        snap = (list(rec.data["artifacts"]), list(rec.data["events"]))
        rec.event("a", "1", {})
        rec.data["ledger"] = "../l.json"
        rec._save()
        rec.rollback(snap)
        final = Record.load(self.root).data
        self.assertEqual([e["stage"] for e in final["events"]], ["job"])
        self.assertEqual(final["ledger"], "../l.json")
