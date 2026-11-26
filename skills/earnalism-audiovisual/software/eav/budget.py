"""Compute-unit forecast and the standing Colab Pro allowance ledger.

Colab allowance: 60 units per title over the title's whole life (all months) and 100
units per calendar month across titles. Reservations count as spent until
settled with the actual units. These CU caps apply to Colab work only.
Modal runs (`eav modal-run`) are capped in dollars only (owner decision of 26 Nov 2026):
30 USD per UTC month and 6 USD per title over the title's whole life, recorded as
append-only `modal_spend` rows (one record per month in the ledger file, next to the
reservation entries). A job is reserved in CU at build time; when it is run on Modal its
reservation entry is marked `runner: "modal"`; the CU Colab already used on it (`colab_units`,
0 if it never ran there) stay counted against the CU caps and the rest of the reservation is
released (the original forecast is kept as `reserved_units`). Such a job settles with both
portions: the Modal rows in USD (`usd`, with `cu_equivalent` kept as information only) and its
Colab CU (those recorded at the move plus any Colab run after it) against the CU caps.
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

    def modal_rows(self, month=None, job_id=None, exclude_run_id=None) -> list:
        """Modal spend rows, oldest first, optionally for one UTC month and/or one job, optionally
        without one row (a request's own pending row while it is re-checked)."""
        return [r for rec in self._modal_records()
                if month is None or rec["modal_spend"] == month
                for r in rec["rows"] if (job_id is None or r["job_id"] == job_id)
                and (exclude_run_id is None or r.get("run_id") != exclude_run_id)]

    def modal_month_usd(self, month: str, exclude_run_id=None) -> float:
        return float(sum(r["usd"] for r in self.modal_rows(month=month, exclude_run_id=exclude_run_id)))

    def modal_job_usd(self, job_id: str):
        """(total usd of every Modal session of the job, number of rows)."""
        rows = self.modal_rows(job_id=job_id)
        return float(sum(r["usd"] for r in rows)), len(rows)

    def modal_units(self, job_id: str):
        """CU-equivalent of the job's Modal rows (usd / USD_PER_CU, 2 decimals), None if no rows.
        Information only: Modal spend never counts against the CU caps."""
        usd, n = self.modal_job_usd(job_id)
        return round(usd / USD_PER_CU, 2) if n else None

    def modal_title_usd(self, title, edition_id=None, exclude_run_id=None) -> float:
        """Lifetime Modal spend of one title (every month, pending rows included): the rows of
        every job whose reservation entry belongs to the title."""
        jobs = {e["job_id"] for e in self._load() if self._mine(e, title, edition_id)}
        return float(sum(r["usd"] for r in self.modal_rows(exclude_run_id=exclude_run_id)
                         if r["job_id"] in jobs))

    @staticmethod
    def _over(spent: float, worst_case_usd: float, cap: float) -> bool:
        return round(spent + worst_case_usd, 9) > cap

    def check_modal_month(self, month: str, worst_case_usd: float, exclude_run_id=None) -> None:
        spent = self.modal_month_usd(month, exclude_run_id)
        if self._over(spent, worst_case_usd, MODAL_MONTH_CAP_USD):
            raise BudgetExceeded(
                f"Modal month cap {MODAL_MONTH_CAP_USD:.2f} USD would be exceeded for {month}: "
                f"spent {spent:.2f} USD, worst-case forecast {worst_case_usd:.2f} USD, "
                f"remaining {max(MODAL_MONTH_CAP_USD - spent, 0):.2f} USD")

    def check_modal_title(self, title, worst_case_usd: float, edition_id=None,
                          exclude_run_id=None) -> None:
        spent = self.modal_title_usd(title, edition_id, exclude_run_id)
        if self._over(spent, worst_case_usd, MODAL_TITLE_CAP_USD):
            raise BudgetExceeded(
                f"Modal title cap {MODAL_TITLE_CAP_USD:.2f} USD (lifetime) would be exceeded for "
                f"{title!r}: spent {spent:.2f} USD, worst-case forecast {worst_case_usd:.2f} USD, "
                f"remaining {max(MODAL_TITLE_CAP_USD - spent, 0):.2f} USD")

    def check_modal(self, month: str, title, worst_case_usd: float, edition_id=None,
                    exclude_run_id=None) -> None:
        """Both Modal dollar caps, checked before Modal is contacted (pending rows count).
        exclude_run_id leaves out the row whose worst case is being re-checked (modal-run --request)."""
        self.check_modal_month(month, worst_case_usd, exclude_run_id)
        self.check_modal_title(title, worst_case_usd, edition_id, exclude_run_id)

    def move_to_modal(self, job_id: str, at: str, colab_units: float) -> float:
        """The job is run on Modal: colab_units (the CU Colab already showed for this job, 0 if it
        never ran there) stay counted against the CU caps; the rest of the reservation is released
        (the forecast is kept as reserved_units). A later modal-run of the same job passes the
        cumulative Colab CU again: it may grow (a Colab session in between), never shrink.
        Returns the CU released by this call."""
        _check_units(colab_units)
        entries = self._load()
        entry = next((e for e in entries if e["job_id"] == job_id), None)
        if entry is None:
            raise KeyError(job_id)
        if entry["state"] != "reserved":
            raise ValueError(f"job {job_id!r} is already settled; it cannot move to Modal")
        if entry.get("runner") == "modal":
            recorded = entry.get("colab_units", 0.0)
            if colab_units < recorded:
                raise ValueError(f"job {job_id!r} already recorded {recorded:g} CU of Colab work; "
                                 f"--colab-units {colab_units:g} would lower it")
            if colab_units != recorded:
                entry.update(colab_units=colab_units, units=colab_units)
                self._save(entries)
            return 0.0
        released = max(entry["units"] - colab_units, 0.0)
        entry.update(reserved_units=entry["units"], units=colab_units, colab_units=colab_units,
                     runner="modal", moved_to_modal_at=at)
        self._save(entries)
        return released

    def colab_units_before_modal(self, job_id: str) -> float:
        """The Colab CU recorded when the job moved to Modal (0 if none or not moved)."""
        entry = next((e for e in self._load() if e["job_id"] == job_id), None)
        return float(entry.get("colab_units", 0.0)) if entry else 0.0

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

    def _take_row(self, everything, run_id):
        """Remove and return the row run_id (dropping a month record left empty)."""
        for rec in everything:
            for i, row in enumerate(rec.get("rows", ())):
                if row.get("run_id") == run_id:
                    del rec["rows"][i]
                    if "modal_spend" in rec and not rec["rows"]:
                        everything.remove(rec)
                    return row
        raise KeyError(run_id)

    @staticmethod
    def _put_row(everything, month, row):
        for rec in everything:
            if rec.get("modal_spend") == month:
                rec["rows"].append(row)
                return
        everything.append({"modal_spend": month, "rows": [row]})

    def move_modal_row(self, run_id: str, month: str) -> None:
        """Move a pending row (same run_id) into month: a request run in a later UTC month counts
        against that month's cap."""
        everything = self._raw()
        row = self._take_row(everything, run_id)
        if row["status"] != "pending":
            raise ValueError(f"row {run_id} is {row['status']}, not pending")
        self._put_row(everything, month, row)
        self._write(everything)

    def release_pending_modal(self, run_id: str) -> None:
        """Delete a pending row of a run that never contacted Modal (a refused request)."""
        everything = self._raw()
        row = self._take_row(everything, run_id)
        if row["status"] != "pending":
            raise ValueError(f"row {run_id} is {row['status']}, not pending; it is never released")
        self._write(everything)

    def replay_job(self, job_id: str, saved: list) -> None:
        """Re-apply one job's ledger state from saved (another copy of this ledger file) onto this
        one: the job's reservation entry is replaced by the saved entry, and each of the job's saved
        Modal rows replaces the row with the same run_id (inserted into its month if absent). Every
        other entry and row stays as it is here."""
        everything = self._raw()
        entry = next((e for e in saved if "modal_spend" not in e and e.get("job_id") == job_id), None)
        if entry is not None:
            for i, e in enumerate(everything):
                if "modal_spend" not in e and e.get("job_id") == job_id:
                    everything[i] = entry
                    break
            else:
                everything.insert(sum(1 for e in everything if "modal_spend" not in e), entry)
        for rec in saved:
            if "modal_spend" not in rec:
                continue
            for row in rec["rows"]:
                if row.get("job_id") != job_id:
                    continue
                try:
                    self._take_row(everything, row["run_id"])
                except KeyError:
                    pass
                self._put_row(everything, rec["modal_spend"], dict(row))
        self._write(everything)

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
        """Settle a reservation at the actual Colab CU. A job run on Modal also records its Modal
        rows in USD (usd / cu_equivalent as information); actual_units is then its Colab portion
        only (0 if it ran only on Modal), counted against the CU caps."""
        _check_units(actual_units)
        entries = self._load()
        for e in entries:
            if e["job_id"] == job_id:
                if e["state"] == "settled":
                    raise ValueError(f"job already settled: {job_id!r}")
                usd, n = self.modal_job_usd(job_id)
                if e.get("runner") == "modal" or n:
                    e.setdefault("reserved_units", e["units"])
                    e.update(runner="modal", units=actual_units, colab_units=actual_units,
                             usd=round(usd, 6), cu_equivalent=round(usd / USD_PER_CU, 2))
                else:
                    e["units"] = actual_units
                e["state"] = "settled"
                self._save(entries)
                return
        raise KeyError(job_id)
