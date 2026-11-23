"""Production record: a JSON file that tracks source, artifacts and events."""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "earnalism.audiovisual_record.v1"
FILENAME = "record.json"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Record:
    def __init__(self, root: Path, data: dict):
        self.root = Path(root)
        self.data = data

    @property
    def path(self) -> Path:
        return self.root / FILENAME

    @classmethod
    def create(cls, root: Path, title_slug: str, source: dict) -> "Record":
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        rec = cls(root, {
            "schema": SCHEMA,
            "title_slug": title_slug,
            "created_at": _now(),
            "source": dict(source),
            "artifacts": [],
            "events": [],
        })
        rec._save()
        return rec

    @classmethod
    def load(cls, root) -> "Record":
        root = Path(root)
        data = json.loads((root / FILENAME).read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA:
            raise ValueError(f"unsupported record schema: {data.get('schema')!r}")
        return cls(root, data)

    def add_artifact(self, kind: str, path: Path, meta: dict) -> dict:
        root = self.root.resolve()
        resolved = Path(path).resolve()
        try:
            rel = resolved.relative_to(root)
        except ValueError:
            raise ValueError(f"artifact path outside record root: {path}") from None
        artifact = {
            "kind": kind,
            "path": rel.as_posix(),
            "sha256": sha256_file(resolved),
            "bytes": resolved.stat().st_size,
            "meta": dict(meta),
        }
        self.data["artifacts"].append(artifact)
        self._save()
        return artifact

    def event(self, stage: str, result: str, detail: dict) -> None:
        self.data["events"].append(
            {"at": _now(), "stage": stage, "result": result, "detail": dict(detail)}
        )
        self._save()

    def _save(self) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".record-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
