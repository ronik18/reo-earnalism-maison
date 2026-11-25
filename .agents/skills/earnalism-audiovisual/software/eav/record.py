"""Production record: a JSON file that tracks source, artifacts and events."""
import hashlib
import copy
import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "earnalism.audiovisual_record.v1"
FILENAME = "record.json"
LOCKNAME = ".record.lock"
_LISTS = ("artifacts", "events")


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
        # Merge-on-save bookkeeping. Rule: artifacts/events are append-only and this
        # instance contributes only the entries it appended itself (_mine); every other
        # top-level key is written only if this instance changed it since the last sync
        # (_base). In-place edits of existing artifact/event entries are NOT merged.
        self._mine = {k: [] for k in _LISTS}
        self._base = {k: copy.deepcopy(v) for k, v in data.items() if k not in _LISTS}

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
        self._mine["artifacts"].append(artifact)
        self._save()
        return artifact

    def event(self, stage: str, result: str, detail: dict) -> None:
        entry = {"at": _now(), "stage": stage, "result": result, "detail": dict(detail)}
        self.data["events"].append(entry)
        self._mine["events"].append(entry)
        self._save()

    def rollback(self, snapshot) -> None:
        """Undo this instance's appends made after `snapshot` (artifacts, events as
        taken from self.data); entries other commands appended stay."""
        keep = dict(zip(_LISTS, snapshot))
        with self._locked():
            disk = self._read_disk()
            for k in _LISTS:
                drop = [e for e in self._mine[k] if e not in keep[k]]
                for e in drop:
                    if e in disk[k]:
                        disk[k].remove(e)
                self._mine[k] = [e for e in self._mine[k] if e in keep[k]]
            self._write(disk)
            self._refresh(disk)

    def _locked(self):
        from contextlib import contextmanager

        @contextmanager
        def cm():
            self.root.mkdir(parents=True, exist_ok=True)
            with open(self.root / LOCKNAME, "a") as lf:
                fcntl.flock(lf, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lf, fcntl.LOCK_UN)
        return cm()

    def _read_disk(self):
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _refresh(self, merged) -> None:
        self.data = merged
        self._base = {k: copy.deepcopy(v) for k, v in merged.items() if k not in _LISTS}

    def _save(self) -> None:
        with self._locked():
            disk = self._read_disk()
            if disk is None:
                merged = self.data
            else:
                merged = disk
                for k, v in self.data.items():
                    if k not in _LISTS and v != self._base.get(k):
                        merged[k] = v
                for k in _LISTS:
                    merged.setdefault(k, [])
                    for e in self._mine[k]:
                        if e not in merged[k]:
                            merged[k].append(e)
            self._write(merged)
            self._refresh(merged)

    def _write(self, data) -> None:
        fd, tmp = tempfile.mkstemp(dir=self.root, prefix=".record-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, self.path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise
