"""Compute-unit forecast and the standing Colab Pro allowance ledger.

Allowance: 60 units per title over the title's whole life (all months) and 100
units per calendar month across titles. Reservations count as spent until
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
MIN_ITEMS = 8


class BudgetExceeded(Exception):
    pass


def forecast(job: dict, rates: dict) -> float:
    rate = rates[job["kind"]]
    seconds = (job["steps"] * rate["s_per_step"] * job["items"] * job["takes"]
               + job["decode_s"] + job["export_s"]) * MARGIN
    return seconds / 3600 * rate["units_per_hour"]


def fit_reel_job(job: dict, rates: dict, remaining_units: float):
    """Cut takes to 1 first, then items (down to 8). Returns a copy or None."""
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
    def _sum(entries, title, month) -> float:
        """Units for one title (None = all titles) in one month (None = all months)."""
        return float(sum(e["units"] for e in entries
                         if (month is None or e["month"] == month)
                         and (title is None or e["title"] == title)))

    def spent(self, title, month) -> float:
        return self._sum(self._load(), title, month)

    def reserve(self, title, month: str, units: float, job_id: str) -> None:
        _check_units(units)
        entries = self._load()
        if any(e["job_id"] == job_id for e in entries):
            raise ValueError(f"duplicate job_id: {job_id!r}")
        if self._sum(entries, title, None) + units > TITLE_CAP:  # lifetime, all months
            raise BudgetExceeded(f"title cap {TITLE_CAP:g} units exceeded for {title!r}")
        if self._sum(entries, None, month) + units > MONTH_CAP:
            raise BudgetExceeded(f"month cap {MONTH_CAP:g} units exceeded for {month}")
        entries.append({"job_id": job_id, "title": title, "month": month,
                        "units": units, "state": "reserved"})
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
