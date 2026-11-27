"""Adoption (G1): bind media that already exists, from imported jobs, to one scene's approved shots.

Nothing is generated and nothing is spent. Every file is verified by sha256 against what its job recorded:

  record  a job imported into an eav production record (this title root, or another root named in the spec):
          the sha256 of each output artifact recorded at import, the job's built job.json (inputs.zip) and the
          motion gate verdicts recorded beside its clips;
  folder  a pilot job folder that eav never imported (inputs.zip plus the notebook's own outputs manifest.json,
          schema earnalism.audiovisual-outputs.v1, status COMPLETE, input_zip_sha256 equal to the inputs.zip).

A hand-copied file (no job) needs the operator's reason; its sha256 is recorded, and its provenance is traced
where it can be: byte-identical to a source job's output or input image, or a derivation the operator declares
from a named job file (recorded as declared, never as identical). No job manifest is ever written or edited.
"""
import hashlib
import json
import re
import zipfile
from pathlib import Path

from .colab_jobs import (EDIT_REPO, FILM_DEPTH_REPO, FILM_REPO, MUSIC_REPO, RETOUCH_REPO, STILLS_REPO)
from .importer import OUTPUTS_SCHEMA
from .record import sha256_file

SCHEMA = "earnalism.audiovisual-adoption.v1"
# the licence of each model whose outputs may be adopted (global constraints: Apache-2.0, MIT, CC0, OpenRAIL++)
MODEL_LICENCES = {STILLS_REPO: "Apache-2.0", FILM_REPO: "Apache-2.0", FILM_DEPTH_REPO: "Apache-2.0",
                  MUSIC_REPO: "Apache-2.0", EDIT_REPO: "Apache-2.0", RETOUCH_REPO: "OpenRAIL++"}
KINDS = {"stills": "stills", "retouch": "retouch", "edit": "edit", "touchup": "touchup", "music": "music",
         "film_clips": "film_clips", "motion": "film_clips"}   # a pilot "motion" notebook made Wan clips and depth
_DEPTH_REPO = re.compile(r"depth-anything/[A-Za-z0-9._-]+")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


class Refused(ValueError):
    """The adoption does not verify; nothing was written."""


def _zip_contents(path: Path) -> tuple:
    """({image base name: sha256}, job.json dict) of a job's inputs.zip ({} and {} when it cannot be read)."""
    images, job = {}, {}
    try:
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.lower().endswith(IMAGE_EXTS):
                    images[Path(name).name] = hashlib.sha256(z.read(name)).hexdigest()
            if "job.json" in z.namelist():
                job = json.loads(z.read("job.json"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        pass
    return images, job if isinstance(job, dict) else {}


class Source:
    """One job whose outputs may be adopted: {flat file name: (path, recorded sha256)}, its job.json, the sha256 of
    its input images and how it is known (provenance)."""

    def __init__(self, job_id, kind, files, job, images, prov, depth_model=None, motion=None):
        self.job_id, self.kind, self.files, self.job = job_id, kind, files, job or {}
        self.images, self.prov, self.depth_model = images, prov, depth_model
        self.motion = motion or {}   # {clip stem: (path, sha256)} of recorded motion gate verdicts

    def file(self, name: str) -> tuple:
        """(path, sha256) of one output, verified now against the sha256 its job recorded."""
        if name not in self.files:
            raise Refused(f"{self.job_id} has no output {name!r} on record")
        path, sha = self.files[name]
        if not Path(path).is_file():
            raise Refused(f"{self.job_id} output {name} is missing at {path}")
        got = sha256_file(path)
        if got != sha:
            raise Refused(f"{self.job_id} output {name}: sha256 {got[:12]}... differs from the {sha[:12]}... its job "
                          "recorded; it is not the file the job made")
        return Path(path), sha

    def item(self, key: str):
        return next((i for i in self.job.get("items") or [] if isinstance(i, dict) and i.get("key") == key), None)

    def model_repo(self):
        return (self.prov.get("model") or {}).get("repo")

    def licence(self, what: str) -> dict:
        """{"model", "licence"} of an output of this job: "depth" (Depth Anything V2 Small only) or its main model."""
        repo = self.depth_model if what == "depth" else self.model_repo()
        if what == "depth" and repo != FILM_DEPTH_REPO:
            raise Refused(f"{self.job_id}: the depth model of its depth maps is {repo or 'not recorded'}, not "
                          f"{FILM_DEPTH_REPO} (Base and Large are non-commercial); its depth maps are not adopted")
        if repo not in MODEL_LICENCES:
            raise Refused(f"{self.job_id}: model {repo or 'not recorded'} is not one whose outputs may be adopted "
                          f"({', '.join(sorted(MODEL_LICENCES))})")
        return {"model": repo, "licence": MODEL_LICENCES[repo]}

    def depth_image_sha(self, depth_name: str):
        """sha256 of the still a depth map <stem>.depth.png was made from: the job's depth_stills entry, else its
        input image <stem>.png."""
        stem = depth_name[:-len(".depth.png")]
        listed = self.job.get("depth_stills") or {}
        for name, sha in listed.items():
            if name.rsplit(".", 1)[0] == stem:
                return sha
        return next((sha for name, sha in self.images.items() if name.rsplit(".", 1)[0] == stem), None)


def record_source(src_root: Path, job_row: dict, artifacts: list, job_json: dict, label: str) -> Source:
    """A job imported into an eav record. job_row is that record's `_jobs` row (imported, not ended)."""
    jid, kind = job_row["job_id"], job_row["kind"]
    if not job_row["imported"] or job_row["superseded"] or job_row["closed"]:
        raise Refused(f"{jid} is not an imported job of {label} (superseded, closed or not imported)")
    files, motion, model, packages = {}, {}, None, None
    prefix = f"{kind}/{jid}/"
    for a in artifacts:
        m = a["meta"]
        if m.get("job_id") != jid or not a["path"].startswith(prefix):
            continue
        p = Path(src_root) / a["path"]
        if a["kind"] == "motion_gate":
            motion[p.name[:-len(".motion.json")]] = (p, a["sha256"])
            continue
        files[p.name] = (p, a["sha256"])
        model, packages = model or m.get("model"), packages or m.get("packages")
    if not files:
        raise Refused(f"{jid} has no imported output artifacts in {label}")
    images, zjob = _zip_contents(job_row["inputs_zip"]) if job_row.get("inputs_zip") else ({}, {})
    job = job_json or zjob
    depth = job.get("depth_model") or (model or {}).get("depth_repo")
    zip_sha = sha256_file(job_row["inputs_zip"]) if job_row.get("inputs_zip") and Path(job_row["inputs_zip"]).is_file() else None
    prov = {"origin": "record", "record": label, "job_id": jid, "kind": kind, "model": model, "packages": packages,
            "input_zip_sha256": zip_sha, "verified_against": "the output sha256 recorded when eav imported the job"}
    return Source(jid, kind, files, job, images, prov, depth, motion)


def folder_source(folder: Path, job_id: str, label: str) -> Source:
    """A pilot job folder eav never imported: its outputs manifest (COMPLETE) and inputs.zip, verified together."""
    folder = Path(folder)
    man_path = next((p for p in (folder / "out" / "manifest.json", folder / "manifest.json") if p.is_file()), None)
    if man_path is None:
        raise Refused(f"{label}: no outputs manifest.json in {folder} or {folder / 'out'}")
    try:
        man = json.loads(man_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Refused(f"{label}: cannot read {man_path}: {e}") from None
    if not isinstance(man, dict) or man.get("schema") != OUTPUTS_SCHEMA or man.get("job_id") != job_id:
        raise Refused(f"{label}: {man_path} is not the outputs manifest of job {job_id}")
    if man.get("status") != "COMPLETE":
        raise Refused(f"{label}: {man_path} status is {man.get('status')!r}, not COMPLETE; nothing of it is adopted")
    zpath = folder / "inputs.zip"
    if not zpath.is_file() or sha256_file(zpath) != man.get("input_zip_sha256"):
        raise Refused(f"{label}: {zpath} is missing or its sha256 differs from the manifest's input_zip_sha256")
    kind = KINDS.get(man.get("kind"))
    if kind is None:
        raise Refused(f"{label}: job kind {man.get('kind')!r} cannot be adopted")
    outputs = man.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        raise Refused(f"{label}: {man_path} lists no outputs")
    files = {name: (man_path.parent / name, sha) for name, sha in outputs.items()}
    images, job = _zip_contents(zpath)
    # the depth model of a pilot notebook is not in its manifest: read from the job's own notebook(s), recorded
    found = {}
    for nb in sorted(folder.glob("*.ipynb")):
        for repo in set(_DEPTH_REPO.findall(nb.read_text(encoding="utf-8", errors="replace"))):
            found.setdefault(repo, []).append({"notebook": nb.name, "sha256": sha256_file(nb)})
    depth = next(iter(found)) if len(found) == 1 else None
    prov = {"origin": "folder", "folder": label, "job_id": job_id, "kind": kind, "model": man.get("model"),
            "packages": man.get("packages"), "input_zip_sha256": man.get("input_zip_sha256"),
            "manifest_sha256": sha256_file(man_path),
            "verified_against": "the job's own outputs manifest.json (COMPLETE) and its inputs.zip sha256; "
                                "a pilot job eav never imported",
            **({"depth_model_evidence": found} if found else {})}
    return Source(job_id, kind, files, job, images, prov, depth)


def trace(sha: str, sources: list) -> list:
    """Where a hand-copied file's exact bytes come from: [{"job_id", "file", "relation"}] (outputs first)."""
    out = []
    for src in sources:
        for name, (_, s) in sorted(src.files.items()):
            if s == sha:
                out.append({"job_id": src.job_id, "file": name, "relation": "identical to the job's output"})
    for src in sources:
        for name, s in sorted(src.images.items()):
            if s == sha:
                out.append({"job_id": src.job_id, "file": name, "relation": "identical to the job's input image"})
    return out


def binding_id(scene: str, tag: str, binding: dict) -> str:
    """The adopted job's id: its content's hash, so the same adoption is the same job (idempotent)."""
    h = hashlib.sha256(json.dumps(binding, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:10]
    return f"adopt-{scene}-{tag}-{h}"
