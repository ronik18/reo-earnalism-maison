"""Compute-unit forecast and the standing Colab Pro allowance ledger.

Allowance: 60 units per title over the title's whole life (all months) unless the
owner raised it in title-caps.json next to the ledger, and 100 units per calendar
month across titles. Reservations count as spent until
settled with the actual units.
The ledger assumes one writer process at a time.
"""
import json
import math
import os
import tempfile
from pathlib import Path

TITLE_CAP = 60.0
MONTH_CAP = 100.0
MARGIN = 1.15
MIN_ITEMS = 1
# The wan22 batch contract allocates at least 600 s per job, so a reel batch reserves at least that.
REEL_MIN_SECONDS = 600


class BudgetExceeded(Exception):
    pass


def forecast_seconds(job: dict, rates: dict) -> float:
    """Wall-clock seconds the job may use, margin included; the notebooks stop at this time.

    reel_clips is forecast from the measured end-to-end seconds per finished Wan clip
    (rates clip_s: load, denoise, decode and export), never from a step count alone."""
    rate = rates[job["kind"]]
    if job["kind"] == "reel_clips":
        return max(job["items"] * job["takes"] * rate["clip_s"] * MARGIN, REEL_MIN_SECONDS)
    if job["kind"] == "film_clips":  # measured seconds per finished clip by resolution and GPU, margin on the clips
        hd = rate["clip_s_hd_a100"] if job["gpu"] == "a100" else rate["clip_s_hd"]
        return ((job["hd"] * hd + job["sd"] * rate["clip_s_sd"]) * job["takes"] * MARGIN
                + job["decode_s"] + job["export_s"] + job.get("sfx_s", 0))
    return ((job["steps"] * rate["s_per_step"] * job["items"] * job["takes"]
             + job["decode_s"] + job["export_s"]) * MARGIN + job.get("gate_s", 0))


def forecast(job: dict, rates: dict) -> float:
    rate = rates[job["kind"]]
    uph = rate["units_per_hour_" + job["gpu"]] if job["kind"] == "film_clips" else rate["units_per_hour"]
    return forecast_seconds(job, rates) / 3600 * uph


def fit_reel_job(job: dict, rates: dict, remaining_units: float):
    """Cut takes to 1 first, then items (shots, down to 1). Returns a copy or None."""
    fitted = dict(job)
    while True:
        if forecast(fitted, rates) <= remaining_units:
            return fitted
        if fitted["takes"] > 1:
            fitted["takes"] -= 1
        elif fitted["items"] > MIN_ITEMS:
            fitted["items"] -= 1
        else:
            return None


def title_cap(ledger_path, title) -> float:
    """Lifetime cap for one title: its title-caps.json entry next to the ledger, else TITLE_CAP."""
    path = Path(ledger_path).parent / "title-caps.json"
    if not path.exists():
        return TITLE_CAP
    caps = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(caps, dict):
        raise ValueError(f"{path.name} must be a JSON object of title -> units")
    for slug, cap in caps.items():
        if isinstance(cap, bool) or not isinstance(cap, (int, float)) \
                or not math.isfinite(cap) or cap <= 0:
            raise ValueError(f"{path.name}: cap for {slug!r} must be a finite number > 0, got {cap!r}")
    return float(caps.get(title, TITLE_CAP))


def _check_units(units) -> float:
    if isinstance(units, bool) or not isinstance(units, (int, float)) \
            or not math.isfinite(units) or units < 0:
        raise ValueError(f"units must be a finite number >= 0, got {units!r}")
    return units


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _load(self) -> list:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, entries: list) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".ledger-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(entries, f, indent=2)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @staticmethod
    def _mine(e, title, edition_id) -> bool:
        """The title cap is keyed by the export's edition_id (R26); an entry written before
        edition keying (no edition_id) is matched by its slug."""
        if title is None and edition_id is None:
            return True
        if e.get("edition_id") is not None:
            return edition_id is not None and e["edition_id"] == edition_id
        return title is not None and e["title"] == title

    @classmethod
    def _sum(cls, entries, title, month, edition_id=None) -> float:
        """Units for one title (None = all titles) in one month (None = all months)."""
        return float(sum(e["units"] for e in entries
                         if (month is None or e["month"] == month)
                         and cls._mine(e, title, edition_id)))

    def spent(self, title, month, edition_id=None) -> float:
        return self._sum(self._load(), title, month, edition_id)

    def roots(self, edition_id) -> set:
        """Title roots (relative to the ledger's folder) that reserved for this edition."""
        return {e["root"] for e in self._load()
                if e.get("edition_id") == edition_id and e.get("root") is not None}

    def reserve(self, title, month: str, units: float, job_id: str, edition_id=None,
                root=None) -> None:
        _check_units(units)
        entries = self._load()
        if any(e["job_id"] == job_id for e in entries):
            raise ValueError(f"duplicate job_id: {job_id!r}")
        if edition_id is not None and root is not None:
            others = {e.get("root") for e in entries
                      if e.get("edition_id") == edition_id and e.get("root") not in (None, root)}
            if others:
                raise ValueError(f"edition {edition_id} already has a title root on this ledger "
                                 f"({', '.join(sorted(others))}); one root per edition")
        cap = title_cap(self.path, title)
        if self._sum(entries, title, None, edition_id) + units > cap:  # lifetime, all months
            raise BudgetExceeded(f"title cap {cap:g} units exceeded for {title!r}")
        if self._sum(entries, None, month) + units > MONTH_CAP:
            raise BudgetExceeded(f"month cap {MONTH_CAP:g} units exceeded for {month}")
        entry = {"job_id": job_id, "title": title, "month": month, "units": units,
                 "state": "reserved"}
        if edition_id is not None:
            entry.update(edition_id=edition_id, root=root)
        entries.append(entry)
        self._save(entries)

    def settle(self, job_id: str, actual_units: float) -> None:
        _check_units(actual_units)
        entries = self._load()
        for e in entries:
            if e["job_id"] == job_id:
                if e["state"] == "settled":
                    raise ValueError(f"job already settled: {job_id!r}")
                e["units"] = actual_units
                e["state"] = "settled"
                self._save(entries)
                return
        raise KeyError(job_id)
