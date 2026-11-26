"""Compute-unit forecast and the standing Colab Pro allowance ledger.

Colab allowance: 60 units per title over the title's whole life (all months) and 100
units per calendar month across titles. Reservations count as spent until
settled with the actual units. These CU caps apply to Colab work only.
Modal runs (`eav modal-run`) are capped in dollars only (owner decision of 26 Nov 2026):
30 USD per UTC month and 6 USD per title over the title's whole life, recorded as
append-only `modal_spend` rows (one record per month in the ledger file, next to the
reservation entries). A job is reserved in CU at build time; when it is run on Modal its
reservation entry is marked `runner: "modal"` and its units are released to 0 (the original
forecast is kept as `reserved_units`), so it no longer counts against the CU caps. Such a job
settles from its Modal rows in USD (`usd`, with `cu_equivalent` kept as information only).
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
MODAL_MONTH_CAP_USD = 30.0
MODAL_TITLE_CAP_USD = 6.0  # lifetime per title: the dollar value of the 60 CU title cap at 0.10/CU
USD_PER_CU = 0.10  # information only (cu_equivalent); Modal spend never counts against CU caps
MODAL_STATUSES = ("ok", "failed", "hard_stopped", "pending", "settled")
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
    return (job["steps"] * rate["s_per_step"] * job["items"] * job["takes"]
            + job["decode_s"] + job["export_s"]) * MARGIN


def forecast(job: dict, rates: dict) -> float:
    return forecast_seconds(job, rates) / 3600 * rates[job["kind"]]["units_per_hour"]


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


def _check_units(units) -> float:
    if isinstance(units, bool) or not isinstance(units, (int, float)) \
            or not math.isfinite(units) or units < 0:
        raise ValueError(f"units must be a finite number >= 0, got {units!r}")
    return units


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def _raw(self) -> list:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _load(self) -> list:
        """The reservation entries (modal_spend records are kept apart; old ledgers have none)."""
        return [e for e in self._raw() if "modal_spend" not in e]

    def _modal_records(self) -> list:
        return [e for e in self._raw() if "modal_spend" in e]

    def _save(self, entries: list) -> None:
        self._write(list(entries) + self._modal_records())

    def _write(self, everything: list) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".ledger-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(everything, f, indent=2)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def modal_rows(self, month=None, job_id=None) -> list:
        """Modal spend rows, oldest first, optionally for one UTC month and/or one job."""
        return [r for rec in self._modal_records()
                if month is None or rec["modal_spend"] == month
                for r in rec["rows"] if job_id is None or r["job_id"] == job_id]

    def modal_month_usd(self, month: str) -> float:
        return float(sum(r["usd"] for r in self.modal_rows(month=month)))

    def modal_job_usd(self, job_id: str):
        """(total usd of every Modal session of the job, number of rows)."""
        rows = self.modal_rows(job_id=job_id)
        return float(sum(r["usd"] for r in rows)), len(rows)

    def modal_units(self, job_id: str):
        """CU-equivalent of the job's Modal rows (usd / USD_PER_CU, 2 decimals), None if no rows.
        Information only: Modal spend never counts against the CU caps."""
        usd, n = self.modal_job_usd(job_id)
        return round(usd / USD_PER_CU, 2) if n else None

    def modal_title_usd(self, title, edition_id=None) -> float:
        """Lifetime Modal spend of one title (every month, pending rows included): the rows of
        every job whose reservation entry belongs to the title."""
        jobs = {e["job_id"] for e in self._load() if self._mine(e, title, edition_id)}
        return float(sum(r["usd"] for r in self.modal_rows() if r["job_id"] in jobs))

    @staticmethod
    def _over(spent: float, worst_case_usd: float, cap: float) -> bool:
        return round(spent + worst_case_usd, 9) > cap

    def check_modal_month(self, month: str, worst_case_usd: float) -> None:
        spent = self.modal_month_usd(month)
        if self._over(spent, worst_case_usd, MODAL_MONTH_CAP_USD):
            raise BudgetExceeded(
                f"Modal month cap {MODAL_MONTH_CAP_USD:.2f} USD would be exceeded for {month}: "
                f"spent {spent:.2f} USD, worst-case forecast {worst_case_usd:.2f} USD, "
                f"remaining {max(MODAL_MONTH_CAP_USD - spent, 0):.2f} USD")

    def check_modal_title(self, title, worst_case_usd: float, edition_id=None) -> None:
        spent = self.modal_title_usd(title, edition_id)
        if self._over(spent, worst_case_usd, MODAL_TITLE_CAP_USD):
            raise BudgetExceeded(
                f"Modal title cap {MODAL_TITLE_CAP_USD:.2f} USD (lifetime) would be exceeded for "
                f"{title!r}: spent {spent:.2f} USD, worst-case forecast {worst_case_usd:.2f} USD, "
                f"remaining {max(MODAL_TITLE_CAP_USD - spent, 0):.2f} USD")

    def check_modal(self, month: str, title, worst_case_usd: float, edition_id=None) -> None:
        """Both Modal dollar caps, checked before Modal is contacted (pending rows count)."""
        self.check_modal_month(month, worst_case_usd)
        self.check_modal_title(title, worst_case_usd, edition_id)

    def move_to_modal(self, job_id: str, at: str) -> float:
        """The job is run on Modal: release its CU reservation (units -> 0; the forecast is kept as
        reserved_units) and record that it moved, so the Colab CU caps no longer count it.
        Idempotent (a resumed run changes nothing). Returns the CU released."""
        entries = self._load()
        entry = next((e for e in entries if e["job_id"] == job_id), None)
        if entry is None:
            raise KeyError(job_id)
        if entry.get("runner") == "modal":
            return 0.0
        if entry["state"] != "reserved":
            raise ValueError(f"job {job_id!r} is already settled; it cannot move to Modal")
        released = entry["units"]
        entry.update(reserved_units=released, units=0.0, runner="modal", moved_to_modal_at=at)
        self._save(entries)
        return released

    def is_modal_job(self, job_id: str) -> bool:
        """Run on Modal: moved there, or (a ledger from before the move was recorded) has rows."""
        entry = next((e for e in self._load() if e["job_id"] == job_id), None)
        return bool(entry and entry.get("runner") == "modal") or bool(self.modal_rows(job_id=job_id))

    def record_modal_spend(self, month: str, job_id: str, usd: float, seconds: float,
                           status: str, at: str) -> str:
        """Append one row to the month's modal_spend record. Returns the row's run_id.
        A "pending" row is a provisional worst-case charge written before Modal is contacted."""
        if status not in MODAL_STATUSES:
            raise ValueError(f"unknown modal status {status!r}")
        _check_units(usd)
        _check_units(seconds)
        everything = self._raw()
        n = sum(len(r["rows"]) for r in everything if "modal_spend" in r)
        run_id = f"{job_id}#{n + 1}"
        row = {"run_id": run_id, "job_id": job_id, "usd": usd, "seconds": seconds, "at": at,
               "status": status}
        for rec in everything:
            if rec.get("modal_spend") == month:
                rec["rows"].append(row)
                break
        else:
            everything.append({"modal_spend": month, "rows": [row]})
        self._write(everything)
        return run_id

    def finish_modal_spend(self, run_id: str, usd: float, seconds: float, status: str) -> None:
        """Replace a row in place (a pending worst-case charge becomes the actual spend)."""
        if status not in MODAL_STATUSES or status == "pending":
            raise ValueError(f"unknown modal status {status!r}")
        _check_units(usd)
        _check_units(seconds)
        everything = self._raw()
        for rec in everything:
            for row in rec.get("rows", ()):
                if row.get("run_id") == run_id:
                    row.update(usd=usd, seconds=seconds, status=status)
                    self._write(everything)
                    return
        raise KeyError(run_id)

    def pending_modal_runs(self, job_id: str) -> list:
        return [r for r in self.modal_rows(job_id=job_id) if r["status"] == "pending"]

    def settle_pending_modal(self, job_id: str, usd: float) -> int:
        """Replace the job's pending rows with the billed amount: the first takes usd, any others 0
        (usd is the total billed for those runs). Returns how many rows were replaced."""
        _check_units(usd)
        pending = self.pending_modal_runs(job_id)
        if not pending:
            raise KeyError(job_id)
        for i, row in enumerate(pending):
            self.finish_modal_spend(row["run_id"], usd if i == 0 else 0.0, row["seconds"], "settled")
        return len(pending)

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
        if self._sum(entries, title, None, edition_id) + units > TITLE_CAP:  # lifetime, all months
            raise BudgetExceeded(f"title cap {TITLE_CAP:g} units exceeded for {title!r}")
        if self._sum(entries, None, month) + units > MONTH_CAP:
            raise BudgetExceeded(f"month cap {MONTH_CAP:g} units exceeded for {month}")
        entry = {"job_id": job_id, "title": title, "month": month, "units": units,
                 "state": "reserved"}
        if edition_id is not None:
            entry.update(edition_id=edition_id, root=root)
        entries.append(entry)
        self._save(entries)

    def settle(self, job_id: str, actual_units: float) -> None:
        """Settle a reservation. A job run on Modal settles from its Modal rows in USD: its CU
        stay 0 (actual_units must be 0) and usd / cu_equivalent are recorded as information."""
        _check_units(actual_units)
        entries = self._load()
        for e in entries:
            if e["job_id"] == job_id:
                if e["state"] == "settled":
                    raise ValueError(f"job already settled: {job_id!r}")
                usd, n = self.modal_job_usd(job_id)
                if e.get("runner") == "modal" or n:
                    if actual_units != 0:
                        raise ValueError(f"job {job_id!r} ran on Modal: it settles from its Modal "
                                         f"rows in USD, never with Colab units ({actual_units:g})")
                    e.setdefault("reserved_units", e["units"])
                    e.update(runner="modal", units=0.0, usd=round(usd, 6),
                             cu_equivalent=round(usd / USD_PER_CU, 2))
                else:
                    e["units"] = actual_units
                e["state"] = "settled"
                self._save(entries)
                return
        raise KeyError(job_id)
