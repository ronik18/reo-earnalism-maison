"""Verified import of Colab outputs into the production record.

Notebook kinds (narration, stills, music, retouch) come back as a Drive folder whose
manifest.json lists the sha256 of every output. Reel clips come back as the
wan22 export archive and are verified by that tool's own import_export.
Any mismatch raises ImportHeld and leaves files, record and ledger unchanged.
"""
import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from .budget import _check_units
from .colab_jobs import _load_wan_batch
from .record import sha256_file

OUTPUTS_SCHEMA = "earnalism.audiovisual-outputs.v1"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SHA = re.compile(r"[0-9a-f]{64}")


class ImportHeld(Exception):
    """The downloaded outputs do not match the job; nothing was imported."""


def _read_json(path: Path, what: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ImportHeld(f"cannot read {what}: {e}") from None
    if not isinstance(data, dict):
        raise ImportHeld(f"{what} is not a JSON object")
    return data


def _kind(job: dict, build: dict) -> str:
    kind = job.get("kind") or build.get("kind")
    if kind:
        return kind
    if str(build.get("schema", "")).startswith("earnalism.wan22-batch-build"):
        return "reel_clips"
    raise ImportHeld("cannot determine job kind")


def _preflight_ledger(ledger, job_id: str, units) -> None:
    try:
        _check_units(units)
    except ValueError as e:
        raise ImportHeld(str(e)) from None
    entry = next((e for e in ledger._load() if e["job_id"] == job_id), None)
    if entry is None:
        raise ImportHeld(f"job not reserved on the ledger: {job_id!r}")
    if entry["state"] == "settled":
        raise ImportHeld(f"job already settled: {job_id!r}")


def import_job(record, job: dict, downloaded_dir, ledger, actual_units: float,
               *, archive=None, archive_sha256=None) -> list:
    job_id = job["job_id"]
    build = _read_json(job["manifest"], "build manifest")
    kind = _kind(job, build)
    if build.get("job_id", job_id) != job_id:
        raise ImportHeld("build manifest belongs to a different job")
    _preflight_ledger(ledger, job_id, actual_units)
    if kind not in ("narration", "stills", "music", "retouch", "reel_clips"):
        raise ImportHeld(f"unknown job kind: {kind!r}")
    dest = record.root / kind / job_id
    if dest.exists():
        raise ImportHeld(f"already imported: {dest}")
    parent_existed = dest.parent.exists()
    snapshot = (list(record.data["artifacts"]), list(record.data["events"]))
    try:  # all or nothing: files, record rows and ledger
        if kind == "reel_clips":
            artifacts, detail = _import_reel(record, job, job_id, dest, archive, archive_sha256)
        else:
            artifacts, detail = _import_notebook(record, job, job_id, kind, build,
                                                 Path(downloaded_dir), dest)
        record.event("import", "accepted", {"job_id": job_id, "kind": kind,
                                            "actual_units": actual_units,
                                            "files": [a["path"] for a in artifacts], **detail})
        ledger.settle(job_id, actual_units)
    except BaseException:
        try:
            record.rollback(snapshot)
        finally:
            shutil.rmtree(dest, ignore_errors=True)
            if not parent_existed:
                try:
                    dest.parent.rmdir()
                except OSError:
                    pass
        raise
    return artifacts


def _job_keys(inputs_zip, kind) -> list:
    """The item keys the job asked for: every one needs an output."""
    try:
        with zipfile.ZipFile(inputs_zip) as z:
            data = json.loads(z.read("job.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as e:
        raise ImportHeld(f"cannot read the built job.json: {e}") from None
    rows = data.get("units") if kind == "narration" else data.get("items")
    keys = [r["unit_key" if kind == "narration" else "key"] for r in rows or []]
    if kind == "retouch":  # every retouched still also returns its <key>--mask for review
        keys += list(data.get("masks") or [])
    return keys


def _import_notebook(record, job, job_id, kind, build, folder: Path, dest: Path):
    if not folder.is_dir():
        raise ImportHeld(f"downloaded folder not found: {folder}")
    manifest = _read_json(folder / "manifest.json", "manifest.json")
    if (manifest.get("schema") != OUTPUTS_SCHEMA or manifest.get("job_id") != job_id
            or manifest.get("kind") != kind):
        raise ImportHeld("manifest.json does not belong to this job")
    if manifest.get("status") != "COMPLETE":
        raise ImportHeld(f"manifest.json status is {manifest.get('status')!r}, not COMPLETE (a hard stop "
                         "or failed run): nothing is imported; close the job with its actual units")
    zip_sha = sha256_file(job["inputs_zip"])
    if manifest.get("input_zip_sha256") != zip_sha or build.get("inputs_sha256", zip_sha) != zip_sha:
        raise ImportHeld("input zip sha256 mismatch")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        raise ImportHeld("manifest lists no outputs")
    for name, digest in outputs.items():
        if not _NAME.fullmatch(name) or name in ("manifest.json", "inputs.zip", "exchange.json") \
                or not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise ImportHeld(f"invalid manifest entry: {name!r}")
    present = {}
    for p in folder.iterdir():
        if p.is_symlink() or not p.is_file():
            raise ImportHeld(f"unexpected non-file entry: {p.name}")
        present[p.name] = p
    copy_zip = present.pop("inputs.zip", None)
    present.pop("manifest.json")
    present.pop("exchange.json", None)  # R2 exchange capabilities in a Drive download: never imported
    if copy_zip is not None and sha256_file(copy_zip) != zip_sha:
        raise ImportHeld("inputs.zip in the download differs from the built inputs")
    if set(present) != set(outputs):
        missing, extra = set(outputs) - set(present), set(present) - set(outputs)
        raise ImportHeld(f"files differ from manifest: missing {sorted(missing)}, "
                         f"extra {sorted(extra)}")
    for name, digest in outputs.items():
        if sha256_file(present[name]) != digest:
            raise ImportHeld(f"sha256 mismatch: {name}")
    model = manifest.get("model")
    if not isinstance(model, dict) or not model:
        raise ImportHeld("manifest.json has no MODEL_INFO (model)")
    packages = manifest.get("packages")
    if not isinstance(packages, dict) or not any(packages.values()):
        raise ImportHeld("manifest.json records no resolved package versions (packages)")
    missing = [k for k in _job_keys(job["inputs_zip"], kind)
               if not any(Path(name).stem == k for name in outputs)]
    if missing:
        raise ImportHeld(f"outputs miss job item(s): {', '.join(missing)}")
    staging = Path(tempfile.mkdtemp(dir=record.root, prefix=".import-"))
    try:
        for name in outputs:
            shutil.copy2(present[name], staging / name)
        for name, digest in outputs.items():  # re-verify the copies
            if sha256_file(staging / name) != digest:
                raise ImportHeld(f"copy sha256 mismatch: {name}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(dest)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    meta = {"job_id": job_id, "job_kind": kind, "model": model, "packages": packages,
            "input_zip_sha256": zip_sha}
    artifacts = [record.add_artifact("retouch_mask" if kind == "retouch" and name.endswith("--mask.png")
                                     else kind, dest / name, meta) for name in sorted(outputs)]
    return artifacts, {"model": model, "packages": packages, "input_zip_sha256": zip_sha}


def _import_reel(record, job, job_id, dest: Path, archive, archive_sha256):
    if archive is None or not archive_sha256:
        raise ImportHeld("reel_clips import needs archive and archive_sha256")
    job_path = Path(job["inputs_zip"]).parent / "job.json"
    if not job_path.is_file():
        raise ImportHeld("built job.json not found next to the inputs zip")
    expected = [s["id"] for s in _read_json(job_path, "job.json").get("scenes", [])]
    batch = _load_wan_batch()
    try:  # import_export creates dest; the caller removes it on any failure
        clips = batch.import_export(Path(archive), dest, archive_sha256, job_path)
        rows = [dict(c) for c in clips]
        receipt = _read_json(dest / "import-receipt.json", "import-receipt.json")
    except (ValueError, OSError, KeyError, RuntimeError, zipfile.BadZipFile) as e:
        raise ImportHeld(f"reel export rejected: {e}") from None
    if receipt.get("rejected") != []:
        raise ImportHeld(f"export rejected clips: {receipt.get('rejected')!r}")
    if sorted(c["scene"] for c in rows) != sorted(expected) or not expected:
        raise ImportHeld("accepted clips do not cover exactly the job's scenes")
    meta_base = {"job_id": job_id, "job_kind": "reel_clips", "archive_sha256": archive_sha256}
    artifacts = [record.add_artifact("reel_clip", Path(c["file"]), {
        **meta_base, "scene": c["scene"],
        "source_image_sha256": c.get("source_image_sha256"),
        "technical_verified": bool(c.get("technical_verified")),
        "motion_accepted": False}) for c in rows]
    artifacts.append(record.add_artifact("import_receipt", dest / "import-receipt.json",
                                         meta_base))
    return artifacts, {"archive_sha256": archive_sha256}
