import json
import tempfile
import unittest
from pathlib import Path

from eav.budget import BudgetExceeded, Ledger, title_cap, fit_reel_job, forecast, forecast_seconds

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

    def _caps(self, content):
        (Path(self.tmp.name) / "title-caps.json").write_text(
            content if isinstance(content, str) else json.dumps(content), encoding="utf-8")

    def test_title_cap_override_allows_up_to_100(self):
        self._caps({"bicharak": 100})
        self.assertEqual(title_cap(self.ledger.path, "bicharak"), 100.0)
        self.ledger.reserve("bicharak", "2026-11", 95, "j1")
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve("bicharak", "2026-12", 101, "j2")

    def test_title_cap_default_60_without_file(self):
        self.assertEqual(title_cap(self.ledger.path, "bicharak"), 60.0)
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve("bicharak", "2026-11", 61, "j1")

    def test_title_caps_file_rejects_non_numbers(self):
        for bad in ({"bicharak": "100"}, {"bicharak": True}, {"bicharak": -1}):
            self._caps(bad)
            with self.assertRaises(ValueError):
                title_cap(self.ledger.path, "bicharak")
        self._caps({"bicharak": "100"})
        with self.assertRaises(ValueError):
            self.ledger.reserve("bicharak", "2026-11", 1, "j1")

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


if __name__ == "__main__":
    unittest.main()
