import tempfile
import unittest
from pathlib import Path

import json

from eav.budget import MODAL_MONTH_CAP_USD, MODAL_TITLE_CAP_USD, BudgetExceeded, Ledger, fit_reel_job, forecast, forecast_seconds

RATES = {"reel": {"s_per_step": 1.0, "units_per_hour": 10.0}}


def job(**kw):
    base = {"kind": "reel", "steps": 10, "items": 10, "takes": 2,
            "decode_s": 0, "export_s": 0}
    base.update(kw)
    return base


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = Ledger(Path(self.tmp.name) / "ledger.json")

    def test_forecast_includes_15_percent_margin(self):
        j = job(steps=100, items=1, takes=1, decode_s=30, export_s=20)
        # (100 + 30 + 20) * 1.15 = 172.5 s -> /3600 * 10
        self.assertAlmostEqual(forecast(j, RATES), 172.5 / 3600 * 10)

    def test_title_cap_60(self):
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve("a", "2026-11", 61, "j1")
        self.ledger.reserve("a", "2026-11", 60, "j2")

    def test_title_cap_is_lifetime_across_months(self):
        """R11: 60 CU per title over its whole life; only the 100 CU cap resets monthly."""
        self.ledger.reserve("A", "2026-10", 40, "j1")
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve("A", "2026-11", 25, "j2")
        self.assertEqual(self.ledger.spent("A", None), 40)
        self.ledger.reserve("B", "2026-11", 25, "j3")  # another title is unaffected

    def test_month_cap_100_across_titles(self):
        self.ledger.reserve("A", "2026-11", 55, "j1")
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve("B", "2026-11", 50, "j2")
        self.assertEqual(self.ledger.spent(None, "2026-11"), 55)

    def test_previous_month_not_counted(self):
        self.ledger.reserve("A", "2026-10", 55, "j1")
        self.ledger.reserve("B", "2026-10", 35, "j2")
        self.ledger.reserve("C", "2026-11", 60, "j3")
        self.ledger.reserve("D", "2026-11", 40, "j4")
        self.assertEqual(self.ledger.spent(None, "2026-11"), 100)

    def test_two_reservations_cannot_jointly_exceed(self):
        self.ledger.reserve("A", "2026-11", 40, "j1")
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve("A", "2026-11", 25, "j2")
        # persisted: a fresh Ledger sees the first reservation
        again = Ledger(self.ledger.path)
        with self.assertRaises(BudgetExceeded):
            again.reserve("A", "2026-11", 25, "j3")
        self.ledger.settle("j1", 10)
        self.assertEqual(self.ledger.spent("A", "2026-11"), 10)
        with self.assertRaises(ValueError):
            self.ledger.reserve("A", "2026-11", 1, "j1")

    def test_fit_cuts_takes_before_shots(self):
        j = job(takes=3, items=10)
        one_take = forecast(job(takes=1, items=10), RATES)
        out = fit_reel_job(j, RATES, one_take + 0.01)
        self.assertEqual((out["takes"], out["items"]), (1, 10))
        self.assertEqual(j["takes"], 3)
        tight = forecast(job(takes=1, items=9), RATES)
        out = fit_reel_job(j, RATES, tight + 0.001)
        self.assertEqual((out["takes"], out["items"]), (1, 9))

    def test_fit_cuts_shots_down_to_one_then_none(self):
        one = forecast(job(takes=1, items=1), RATES)
        out = fit_reel_job(job(), RATES, one + 1e-9)
        self.assertEqual((out["takes"], out["items"]), (1, 1))
        self.assertIsNone(fit_reel_job(job(), RATES, one - 1e-9))

    def test_reel_clips_forecast_uses_measured_seconds_per_clip(self):
        """R20: Wan clips are forecast at the measured end-to-end seconds per finished clip."""
        rates = {"reel_clips": {"clip_s": 500.0, "units_per_hour": 1.94}}
        j = {"kind": "reel_clips", "steps": 24, "items": 5, "takes": 1}
        self.assertAlmostEqual(forecast_seconds(j, rates), 5 * 500 * 1.15)
        self.assertAlmostEqual(forecast(j, rates), 5 * 500 * 1.15 / 3600 * 1.94)
        # the Wan contract's minimum allocation is 600 s, so a tiny batch reserves at least that
        self.assertAlmostEqual(forecast_seconds({**j, "items": 1}, rates), 600)

    def test_reserve_rejects_nan_inf_negative(self):
        for bad in (float("nan"), float("inf"), -1, -0.5, "5", True):
            with self.assertRaises(ValueError):
                self.ledger.reserve("a", "2026-11", bad, "jx")
        self.assertEqual(self.ledger.spent(None, "2026-11"), 0)

    def test_settle_rejects_nan_inf_negative(self):
        self.ledger.reserve("a", "2026-11", 10, "j1")
        for bad in (float("nan"), float("inf"), -1, "5"):
            with self.assertRaises(ValueError):
                self.ledger.settle("j1", bad)
        self.assertEqual(self.ledger.spent("a", "2026-11"), 10)

    def test_settle_twice_rejected(self):
        self.ledger.reserve("a", "2026-11", 10, "j1")
        self.ledger.settle("j1", 4)
        with self.assertRaises(ValueError):
            self.ledger.settle("j1", 9)
        self.assertEqual(self.ledger.spent("a", "2026-11"), 4)


class ModalSpendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ledger.json"
        self.ledger = Ledger(self.path)

    def test_old_ledger_without_modal_spend_loads(self):
        self.path.write_text(json.dumps([{"job_id": "j", "title": "t", "month": "2026-11",
                                          "units": 3.0, "state": "reserved"}]))
        self.assertEqual(self.ledger.modal_month_usd("2026-11"), 0.0)
        self.assertEqual(self.ledger.spent(None, "2026-11"), 3.0)
        self.ledger.check_modal_month("2026-11", MODAL_MONTH_CAP_USD)  # exactly the cap is fine

    def test_rows_append_per_month_and_do_not_disturb_reservations(self):
        self.ledger.reserve("t", "2026-11", 5, "j1")
        self.ledger.record_modal_spend("2026-11", "j1", 0.25, 10.0, "failed", "a")
        self.ledger.record_modal_spend("2026-11", "j1", 0.50, 20.0, "ok", "b")
        self.ledger.record_modal_spend("2026-12", "j2", 1.0, 30.0, "hard_stopped", "c")
        self.ledger.settle("j1", 0.5)  # a Modal job: its Colab portion (0.5 CU) plus its USD
        self.ledger.reserve("t", "2026-12", 1, "j2")
        self.assertEqual(self.ledger.modal_month_usd("2026-11"), 0.75)
        self.assertEqual(self.ledger.modal_job_usd("j1"), (0.75, 2))
        self.assertEqual(self.ledger.modal_units("j1"), 7.5)
        self.assertIsNone(self.ledger.modal_units("nope"))
        self.assertEqual(self.ledger.spent("t", None), 1.5)  # Modal spend is not Colab CU
        j1 = next(e for e in json.loads(self.path.read_text()) if e.get("job_id") == "j1")
        self.assertEqual((j1["state"], j1["units"], j1["usd"], j1["cu_equivalent"],
                          j1["runner"], j1["reserved_units"]),
                         ("settled", 0.5, 0.75, 7.5, "modal", 5))
        self.assertEqual(self.ledger.modal_title_usd("t"), 1.75)
        with self.assertRaises(ValueError):
            self.ledger.record_modal_spend("2026-11", "j1", 1, 1, "weird", "d")

    def test_move_to_modal_releases_the_cu_reservation_once(self):
        self.ledger.reserve("t", "2026-11", 40, "j1")
        self.ledger.reserve("u", "2026-11", 60, "j2")
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve("v", "2026-11", 1, "j3")  # 100 CU month full
        self.assertEqual(self.ledger.move_to_modal("j1", "at", 4), 36)  # 4 CU already used in Colab
        self.assertEqual(self.ledger.move_to_modal("j1", "later", 4), 0.0)  # idempotent (resume)
        with self.assertRaises(ValueError):
            self.ledger.move_to_modal("j1", "later", 3)  # never lowered
        self.assertEqual(self.ledger.spent(None, "2026-11"), 64)
        self.assertEqual(self.ledger.spent("t", None), 4)
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve("v", "2026-11", 37, "j3")
        self.ledger.reserve("v", "2026-11", 36, "j3")  # only the released 36 CU are Colab's again
        j1 = next(e for e in json.loads(self.path.read_text()) if e.get("job_id") == "j1")
        self.assertEqual((j1["runner"], j1["units"], j1["colab_units"], j1["reserved_units"],
                          j1["state"], j1["moved_to_modal_at"]), ("modal", 4, 4, 40, "reserved", "at"))
        self.assertEqual(self.ledger.move_to_modal("j1", "again", 4.5), 0.0)  # Colab ran again
        self.assertEqual(self.ledger.spent("t", None), 4.5)
        self.assertEqual(self.ledger.colab_units_before_modal("j1"), 4.5)
        self.assertTrue(self.ledger.is_modal_job("j1"))
        self.assertFalse(self.ledger.is_modal_job("j2"))
        self.ledger.settle("j2", 3)
        with self.assertRaises(ValueError):
            self.ledger.move_to_modal("j2", "at", 0)  # settled: never moves
        with self.assertRaises(KeyError):
            self.ledger.move_to_modal("nope", "at", 0)
        with self.assertRaises(ValueError):
            self.ledger.move_to_modal("j3", "at", -1)

    def test_title_cap_6_usd_boundary_and_month_cap(self):
        self.assertEqual(MODAL_TITLE_CAP_USD, 6.0)
        self.ledger.reserve("t", "2026-10", 1, "j1")
        self.ledger.reserve("t", "2026-11", 1, "j2")
        self.ledger.reserve("big", "2026-11", 1, "k1")
        self.ledger.record_modal_spend("2026-10", "j1", 3.00, 1.0, "ok", "a")  # lifetime: all months
        self.ledger.record_modal_spend("2026-11", "j2", 2.50, 1.0, "pending", "b")  # pending counts
        self.ledger.record_modal_spend("2026-11", "k1", 20.0, 1.0, "ok", "c")  # another title
        self.assertEqual(self.ledger.modal_title_usd("t"), 5.50)
        with self.assertRaises(BudgetExceeded) as cm:
            self.ledger.check_modal("2026-11", "t", 0.60)
        for word in ("title cap", "5.50", "0.60", "0.50"):
            self.assertIn(word, str(cm.exception))
        self.ledger.check_modal("2026-11", "t", 0.50)  # exactly the cap is fine
        self.ledger.check_modal("2026-11", "other", 0.60)
        with self.assertRaises(BudgetExceeded) as cm:  # month: 22.50 + 8 > 30 though title room
            self.ledger.check_modal("2026-11", "fresh", 8.0)
        self.assertIn("month cap", str(cm.exception))

    def test_title_cap_keyed_by_edition(self):
        self.ledger.reserve("slug-a", "2026-11", 1, "j1", edition_id="ed-1", root="a")
        self.ledger.record_modal_spend("2026-11", "j1", 5.30, 1.0, "ok", "a")
        self.ledger.check_modal("2026-11", "slug-b", 0.60, edition_id="ed-1")  # 5.90 allowed
        self.ledger.record_modal_spend("2026-11", "j1", 0.20, 1.0, "ok", "b")
        with self.assertRaises(BudgetExceeded):
            self.ledger.check_modal("2026-11", "slug-b", 0.60, edition_id="ed-1")
        self.ledger.check_modal("2026-11", "slug-a", 0.60, edition_id="ed-2")

    def test_check_modal_month_boundary(self):
        self.ledger.record_modal_spend("2026-11", "j", 29.50, 1.0, "ok", "a")
        with self.assertRaises(BudgetExceeded) as cm:
            self.ledger.check_modal_month("2026-11", 0.60)
        self.assertIn("29.50", str(cm.exception))
        self.ledger.check_modal_month("2026-11", 0.50)

    def test_replay_job_makes_the_jobs_rows_exactly_the_saved_ones(self):
        self.ledger.reserve("t", "2026-11", 1.0, "a")
        self.ledger.reserve("t", "2026-11", 1.0, "b")
        run_a = self.ledger.record_modal_spend("2026-11", "a", 2.0, 0.0, "pending", "t")
        base = json.loads(self.ledger.path.read_text())
        self.ledger.release_pending_modal(run_a)  # the runner refused job a
        saved = json.loads(self.ledger.path.read_text())
        self.ledger._write(base)  # the fresh head still has a's pending row ...
        self.ledger.record_modal_spend("2026-11", "b", 1.5, 0.0, "pending", "t")  # ... and b's new row
        self.ledger.record_modal_spend("2026-12", "a", 0.7, 0.0, "pending", "t")  # stray a row
        self.ledger.replay_job("a", saved)
        self.assertEqual(self.ledger.modal_rows(job_id="a"), [])
        self.assertEqual([(r["job_id"], r["usd"]) for r in self.ledger.modal_rows()], [("b", 1.5)])
        self.assertEqual({e["job_id"] for e in self.ledger._load()}, {"a", "b"})
        # a saved finished row replaces the head's pending row with the same run_id
        self.ledger.record_modal_spend("2026-11", "a", 2.0, 0.0, "pending", "t")
        head = json.loads(self.ledger.path.read_text())
        (row,) = self.ledger.modal_rows(job_id="a")
        self.ledger.finish_modal_spend(row["run_id"], 0.3, 9.0, "ok")
        saved = json.loads(self.ledger.path.read_text())
        self.ledger._write(head)
        self.ledger.replay_job("a", saved)
        self.assertEqual([(r["run_id"], r["usd"], r["status"]) for r in self.ledger.modal_rows(job_id="a")],
                         [(row["run_id"], 0.3, "ok")])
        self.assertEqual([r["usd"] for r in self.ledger.modal_rows(job_id="b")], [1.5])


class ModalFixWaveTests(unittest.TestCase):
    """F1: run_ids never reused (I3), billed reconciliation (I1), undoing a move (I4)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ledger.json"
        self.ledger = Ledger(self.path)

    def entry(self, job_id):
        return next(e for e in json.loads(self.path.read_text()) if e.get("job_id") == job_id)

    def test_run_id_is_never_reused_after_a_release(self):
        """The review's scratch case: K#1 pending, J#2 failed; release K#1; J's next is never J#2."""
        for j in ("K", "J"):
            self.ledger.reserve("t", "2026-11", 1.0, j)
        k1 = self.ledger.record_modal_spend("2026-11", "K", 0.5, 0.0, "pending", "a")
        j1 = self.ledger.record_modal_spend("2026-11", "J", 0.4, 1.0, "failed", "b")
        self.assertEqual((k1, j1), ("K#1", "J#1"))  # numbered per job
        self.ledger.release_pending_modal(k1)
        self.assertEqual(self.ledger.record_modal_spend("2026-11", "K", 0.5, 0.0, "pending", "c"), "K#2")
        j2 = self.ledger.record_modal_spend("2026-11", "J", 0.9, 0.0, "pending", "d")
        self.assertEqual(j2, "J#2")
        self.ledger.release_pending_modal(j2)  # released: the entry remembers it was issued
        self.assertEqual(self.entry("J")["modal_runs_issued"], 2)
        j3 = self.ledger.record_modal_spend("2026-11", "J", 0.9, 0.0, "pending", "e")
        self.assertEqual(j3, "J#3")
        self.ledger.finish_modal_spend(j3, 0.10, 5.0, "ok")
        self.assertEqual([(r["run_id"], r["usd"], r["status"]) for r in self.ledger.modal_rows(job_id="J")],
                         [("J#1", 0.4, "failed"), ("J#3", 0.10, "ok")])

    def test_run_id_without_an_entry_counts_rows_and_refuses_a_duplicate(self):
        self.ledger.record_modal_spend("2026-10", "x", 0.1, 1.0, "ok", "a")
        self.assertEqual(self.ledger.record_modal_spend("2026-11", "x", 0.1, 1.0, "ok", "b"), "x#2")
        everything = json.loads(self.path.read_text())
        everything[-1]["rows"].append({"run_id": "x#3", "job_id": "other", "usd": 0, "seconds": 0,
                                       "at": "c", "status": "ok"})  # a hand-made clash
        self.path.write_text(json.dumps(everything))
        with self.assertRaises(ValueError):
            self.ledger.record_modal_spend("2026-11", "x", 0.1, 1.0, "ok", "d")
        self.assertEqual(Ledger.run_number("narration-film-01-r3-c1of2#12"), 12)
        self.assertEqual(Ledger.run_number("no-suffix"), 0)

    def test_bill_a_finished_row_keeps_the_estimate(self):
        self.ledger.reserve("t", "2026-11", 1.0, "j")
        r1 = self.ledger.record_modal_spend("2026-11", "j", 0.0227, 102.0, "failed", "a")
        self.assertEqual([r["run_id"] for r in self.ledger.unbilled_modal_runs("j")], [r1])
        self.assertEqual(self.ledger.bill_modal_run("j", 0.0), [r1])  # the only unbilled row
        (row,) = self.ledger.modal_rows(job_id="j")
        self.assertEqual((row["usd"], row["estimated_usd"], row["billed"], row["status"]),
                         (0.0, 0.0227, True, "failed"))
        self.assertEqual(self.ledger.modal_month_usd("2026-11"), 0.0)  # the caps read the billed figure
        with self.assertRaises(KeyError):
            self.ledger.bill_modal_run("j", 0.1)  # nothing unbilled left: name the row
        self.ledger.bill_modal_run("j", 0.01, run_id=r1)  # a second correction keeps the first estimate
        (row,) = self.ledger.modal_rows(job_id="j")
        self.assertEqual((row["usd"], row["estimated_usd"]), (0.01, 0.0227))
        r2 = self.ledger.record_modal_spend("2026-11", "j", 0.5, 9.0, "ok", "b")
        r3 = self.ledger.record_modal_spend("2026-11", "j", 0.6, 9.0, "hard_stopped", "c")
        with self.assertRaises(ValueError):
            self.ledger.bill_modal_run("j", 0.4)  # two unbilled rows: ambiguous
        self.assertEqual(self.ledger.bill_modal_run("j", 0.4, run_id=r3), [r3])
        with self.assertRaises(ValueError):
            self.ledger.bill_modal_run("other", 0.4, run_id=r2)  # not that job's row
        with self.assertRaises(ValueError):
            self.ledger.bill_modal_run("j", -1, run_id=r2)
        r4 = self.ledger.record_modal_spend("2026-11", "j", 0.9, 0.0, "pending", "d")
        self.assertEqual(self.ledger.bill_modal_run("j", 0.2), [r4])  # pending rows first
        row = next(r for r in self.ledger.modal_rows(job_id="j") if r["run_id"] == r4)
        self.assertEqual((row["status"], row["usd"], row["estimated_usd"], row["billed"]),
                         ("settled", 0.2, 0.9, True))

    def test_colab_units_never_exceed_the_reservation(self):
        self.ledger.reserve("t", "2026-11", 2.0, "j")
        with self.assertRaises(ValueError) as cm:
            self.ledger.move_to_modal("j", "at", 2.5)
        self.assertIn("cannot exceed the reservation", str(cm.exception))
        self.assertNotIn("runner", self.entry("j"))
        self.ledger.move_to_modal("j", "at", 1.0)
        with self.assertRaises(ValueError):
            self.ledger.move_to_modal("j", "later", 2.1)  # still bounded by reserved_units
        self.ledger.move_to_modal("j", "later", 2.0)

    def test_undo_move_restores_the_reservation_only_if_modal_never_ran(self):
        self.ledger.reserve("t", "2026-11", 3.0, "j")
        self.ledger.move_to_modal("j", "at", 0.5)
        run = self.ledger.record_modal_spend("2026-11", "j", 0.8, 0.0, "pending", "a")
        self.ledger.release_pending_modal(run)
        self.assertTrue(self.ledger.undo_move_to_modal("j"))
        e = self.entry("j")
        self.assertEqual((e["units"], e["state"], e["modal_runs_issued"]), (3.0, "reserved", 1))
        for key in ("runner", "colab_units", "reserved_units", "moved_to_modal_at"):
            self.assertNotIn(key, e)
        self.assertFalse(self.ledger.is_modal_job("j"))
        self.assertEqual(self.ledger.spent("t", None), 3.0)
        self.assertFalse(self.ledger.undo_move_to_modal("j"))  # not moved: nothing to undo
        self.ledger.move_to_modal("j", "again", 0.0)
        self.ledger.record_modal_spend("2026-11", "j", 0.1, 3.0, "failed", "b")  # Modal ran once
        self.assertFalse(self.ledger.undo_move_to_modal("j"))
        self.assertEqual(self.entry("j")["runner"], "modal")
        self.assertFalse(self.ledger.undo_move_to_modal("nope"))


if __name__ == "__main__":
    unittest.main()
