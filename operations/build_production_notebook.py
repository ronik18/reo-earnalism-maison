"""Reseal the existing notebook's source snapshot. No runtime/provider controller."""
import argparse
import ast
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile

SOURCE_FILES = (
    "operations/__init__.py", "operations/production_bundle.py",
    "operations/production_journal.py", "operations/production_delivery.py",
    "operations/stream_delivery.py", "operations/social_delivery/__init__.py",
    "operations/social_delivery/bridge.py", "operations/social_delivery/http.py",
    "library/__init__.py", "library/production_handoff.py",
    "operations/book_source.py", "library/book_import_client.py",
    "operations/provider_acceptance.py",
)
NOTEBOOK = "notebooks/Earnalism_Production_Orchestrator.ipynb"


def source_snapshot(root):
    root = Path(root)
    source = {name: (root / name).read_bytes() for name in SOURCE_FILES}
    for name, data in source.items():
        compile(data, name, "exec")
    rows = [{"path": name, "bytes": len(source[name]), "sha256": hashlib.sha256(source[name]).hexdigest()} for name in SOURCE_FILES]
    manifest = dict(schema="earnalism.private_bridge_source_snapshot.v1",
        state="SOURCE_SNAPSHOT_NOT_LIVE_PROVIDER_QUALIFICATION", files=rows,
        contains_credentials=False, contains_models_or_media=False)
    metadata = (json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
    packet = io.BytesIO()
    with zipfile.ZipFile(packet, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted({**source, "BRIDGE-SOURCES.json": metadata}.items()):
            info = zipfile.ZipInfo(name, (2026, 11, 21, 0, 0, 0))
            info.create_system = 3; info.external_attr = 0o100600 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    descriptors = [*rows, {"path": "BRIDGE-SOURCES.json", "bytes": len(metadata), "sha256": hashlib.sha256(metadata).hexdigest()}]
    return packet.getvalue(), rows, descriptors, source


def _replace_constants(source, values):
    lines, found = source.splitlines(keepends=True), {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in values:
                if name in found:
                    raise ValueError("DUPLICATE_SOURCE_SNAPSHOT_CONSTANT")
                found[name] = (node.lineno - 1, node.end_lineno)
    if set(found) != set(values):
        raise ValueError("EXISTING_SOURCE_SNAPSHOT_CELL_REQUIRED")
    for name, (start, end) in sorted(found.items(), key=lambda x: x[1][0], reverse=True):
        lines[start:end] = [name + " = " + repr(values[name]) + "\n"]
    return "".join(lines)


def build(root=None, *, check=False):
    root = Path(root or Path(__file__).resolve().parents[1]).resolve()
    target = root / NOTEBOOK
    original = target.read_bytes()
    if target.is_symlink() or len(original) > 2_000_000:
        raise ValueError("BOUNDED_EXISTING_NOTEBOOK_REQUIRED")
    notebook = json.loads(original)
    original_voice_cells = json.dumps(notebook["cells"][:9], ensure_ascii=False, sort_keys=True)
    cells = [c for c in notebook["cells"] if c.get("id") == "private-production-source"]
    if len(cells) != 1:
        raise ValueError("EXISTING_SINGLE_ORCHESTRATOR_REQUIRED")
    raw, rows, descriptors, source_files = source_snapshot(root)
    digest = hashlib.sha256(raw).hexdigest()
    cells[0]["source"] = _replace_constants("".join(cells[0]["source"]), {
        "BRIDGE_SOURCE_SHA256": digest, "BRIDGE_SOURCE_BASE64": base64.b64encode(raw).decode(),
        "BRIDGE_SOURCE_FILES": descriptors}).splitlines(keepends=True)
    notebook["metadata"]["earnalism"].update(bridge_source_snapshot_sha256=digest, bridge_source_files=rows)
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            if cell.get("execution_count") is not None or cell.get("outputs"):
                raise ValueError("PRESERVE_EXECUTED_NOTEBOOK_REVIEW_BEFORE_RESEALING")
            compile("".join(cell["source"]), "<notebook-cell>", "exec")
    if json.dumps(notebook["cells"][:9], ensure_ascii=False, sort_keys=True) != original_voice_cells:
        raise ValueError("ORIGINAL_VOICE_CELLS_CHANGED")
    updated = (json.dumps(notebook, ensure_ascii=False, indent=1) + "\n").encode()
    result = dict(notebook=NOTEBOOK, bytes=len(updated), sha256=hashlib.sha256(updated).hexdigest(),
        source_zip_sha256=digest, source_files=len(rows), changed=updated != original, provider_requests=0)
    if check:
        if updated != original:
            raise ValueError("NOTEBOOK_SOURCE_SNAPSHOT_STALE_RUN_MAINTENANCE_BUILDER")
        return result
    for name, data in source_files.items():
        if (root / name).read_bytes() != data:
            raise ValueError("SOURCE_CHANGED_DURING_RESEAL_REVIEW_AGAIN")
    if updated == original:
        return result
    fd, temporary = tempfile.mkstemp(prefix=".production-notebook-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(updated); stream.flush(); os.fsync(stream.fileno())
        if target.read_bytes() != original or target.is_symlink():
            raise ValueError("CONCURRENT_NOTEBOOK_WORK_PRESERVED")
        os.replace(temporary, target)
        fd = os.open(target.parent, os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify the snapshot without changing any file.")
    args = parser.parse_args(argv)
    print(json.dumps(build(check=args.check), sort_keys=True))


if __name__ == "__main__": main()
