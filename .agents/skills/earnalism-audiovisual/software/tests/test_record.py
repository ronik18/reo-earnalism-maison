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
