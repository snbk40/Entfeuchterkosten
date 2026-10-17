"""Tests for the cost meter. They need no Home Assistant.

Run from the repository root with:  python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import sys
import unittest
from zoneinfo import ZoneInfo

_COST = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "entfeuchterkosten"
    / "cost.py"
)
_spec = importlib.util.spec_from_file_location("entfeuchterkosten_cost", _COST)
assert _spec is not None and _spec.loader is not None
cost = importlib.util.module_from_spec(_spec)
sys.modules["entfeuchterkosten_cost"] = cost
_spec.loader.exec_module(cost)

BERLIN = ZoneInfo("Europe/Berlin")
Period = cost.Period


def at(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, *, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=BERLIN)


class ToWatts(unittest.TestCase):
    def test_units(self):
        self.assertEqual(cost.to_watts("250", "W"), 250)
        self.assertEqual(cost.to_watts("0.25", "kW"), 250)
        self.assertEqual(cost.to_watts(250000, "mW"), 250)
        self.assertEqual(cost.to_watts("250", None), 250)

    def test_unusable_readings(self):
        for value, unit in [
            ("unavailable", "W"),
            ("unknown", "W"),
            (None, "W"),
            ("nan", "W"),
            ("inf", "W"),
            ("250", "A"),
        ]:
            self.assertIsNone(cost.to_watts(value, unit), (value, unit))


class CostMeter(unittest.TestCase):
    def test_constant_power(self):
        meter = cost.CostMeter(price=0.30, now=at(2026, 10, 17, 10))
        meter.set_power(500, at(2026, 10, 17, 10))
        meter.advance(at(2026, 10, 17, 12))
        self.assertAlmostEqual(meter.total_kwh, 1.0)
        self.assertAlmostEqual(meter.total_cost, 0.30)
        for period in Period:
            self.assertAlmostEqual(meter.periods[period].cost, 0.30)

    def test_power_holds_until_next_reading(self):
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 17, 10))
        meter.set_power(0, at(2026, 10, 17, 10))
        meter.set_power(1000, at(2026, 10, 17, 11))  # compressor on
        meter.set_power(0, at(2026, 10, 17, 11, 30))  # and off again
        meter.advance(at(2026, 10, 17, 14))
        self.assertAlmostEqual(meter.total_kwh, 0.5)

    def test_unknown_power_is_not_counted(self):
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 17, 10))
        meter.set_power(1000, at(2026, 10, 17, 10))
        meter.set_power(None, at(2026, 10, 17, 11))
        meter.set_power(1000, at(2026, 10, 17, 15))
        meter.advance(at(2026, 10, 17, 16))
        self.assertAlmostEqual(meter.total_kwh, 2.0)

    def test_negative_power_counts_as_zero(self):
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 17, 10))
        meter.set_power(-50, at(2026, 10, 17, 10))
        meter.advance(at(2026, 10, 17, 12))
        self.assertEqual(meter.total_kwh, 0)

    def test_frequent_ticks_add_up_to_the_same(self):
        meter = cost.CostMeter(price=0.30, now=at(2026, 10, 17, 10))
        meter.set_power(500, at(2026, 10, 17, 10))
        for minute in range(1, 121):
            meter.advance(at(2026, 10, 17, 10) + timedelta(minutes=minute))
        self.assertAlmostEqual(meter.total_kwh, 1.0)

    def test_midnight_splits_the_day(self):
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 17, 23))
        meter.set_power(1000, at(2026, 10, 17, 23))
        meter.advance(at(2026, 10, 18, 2))
        self.assertAlmostEqual(meter.total_cost, 3.0)
        self.assertEqual(meter.periods[Period.DAY].start, at(2026, 10, 18))
        self.assertAlmostEqual(meter.periods[Period.DAY].cost, 2.0)
        self.assertAlmostEqual(meter.periods[Period.MONTH].cost, 3.0)

    def test_new_month_and_year(self):
        meter = cost.CostMeter(price=1.0, now=at(2026, 12, 31, 22))
        meter.set_power(1000, at(2026, 12, 31, 22))
        meter.advance(at(2027, 1, 1, 1))
        self.assertAlmostEqual(meter.total_cost, 3.0)
        for period in Period:
            self.assertAlmostEqual(meter.periods[period].cost, 1.0)
        self.assertEqual(meter.periods[Period.YEAR].start, at(2027, 1, 1))

    def test_period_resets_without_power(self):
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 17, 22))
        meter.set_power(1000, at(2026, 10, 17, 22))
        meter.set_power(None, at(2026, 10, 17, 23))
        meter.advance(at(2026, 10, 18, second=1))
        self.assertEqual(meter.periods[Period.DAY].cost, 0)
        self.assertAlmostEqual(meter.periods[Period.MONTH].cost, 1.0)

    def test_day_with_summer_time_change_has_25_hours(self):
        # On 25 October 2026 the clocks in Germany go back by one hour.
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 25))
        meter.set_power(1000, at(2026, 10, 25))
        meter.advance(at(2026, 10, 26))
        self.assertAlmostEqual(meter.total_kwh, 25.0)
        self.assertAlmostEqual(meter.periods[Period.MONTH].cost, 25.0)

    def test_solar_power_is_free(self):
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 17, 10))
        meter.set_power(400, at(2026, 10, 17, 10))
        meter.set_solar_power(300, at(2026, 10, 17, 10))
        self.assertEqual(meter.chargeable_watts, 100)
        self.assertEqual(meter.saved_watts, 300)
        meter.advance(at(2026, 10, 17, 12))
        self.assertAlmostEqual(meter.total_kwh, 0.8)  # all the energy used
        self.assertAlmostEqual(meter.total_cost, 0.2)  # only the chargeable part
        self.assertAlmostEqual(meter.periods[Period.DAY].cost, 0.2)

    def test_more_solar_than_needed_costs_nothing(self):
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 17, 10))
        meter.set_solar_power(600, at(2026, 10, 17, 10))
        meter.set_power(400, at(2026, 10, 17, 10))
        self.assertEqual(meter.chargeable_watts, 0)
        self.assertEqual(meter.saved_watts, 400)  # no more than is used
        meter.advance(at(2026, 10, 17, 12))
        self.assertAlmostEqual(meter.total_kwh, 0.8)
        self.assertEqual(meter.total_cost, 0)

    def test_solar_change_applies_from_then_on(self):
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 17, 10))
        meter.set_power(1000, at(2026, 10, 17, 10))
        meter.set_solar_power(500, at(2026, 10, 17, 11))  # a cloud moves away
        meter.set_solar_power(None, at(2026, 10, 17, 12))  # inverter goes offline
        meter.advance(at(2026, 10, 17, 13))
        self.assertAlmostEqual(meter.total_cost, 1.0 + 0.5 + 1.0)
        self.assertAlmostEqual(meter.total_kwh, 3.0)

    def test_chargeable_power_is_unknown_without_power(self):
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 17, 10))
        meter.set_solar_power(300, at(2026, 10, 17, 10))
        self.assertIsNone(meter.chargeable_watts)
        self.assertIsNone(meter.saved_watts)
        meter.set_power(None, at(2026, 10, 17, 10))
        self.assertIsNone(meter.chargeable_watts)
        self.assertIsNone(meter.saved_watts)

    def test_no_savings_without_solar(self):
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 17, 10))
        meter.set_power(400, at(2026, 10, 17, 10))
        self.assertEqual(meter.saved_watts, 0)
        meter.set_solar_power(None, at(2026, 10, 17, 10))  # inverter offline
        self.assertEqual(meter.saved_watts, 0)

    def test_savings_are_what_solar_covered(self):
        meter = cost.CostMeter(price=0.5, now=at(2026, 10, 17, 10))
        meter.set_power(400, at(2026, 10, 17, 10))
        meter.set_solar_power(300, at(2026, 10, 17, 10))
        meter.advance(at(2026, 10, 17, 12))
        self.assertAlmostEqual(meter.total_savings, 0.6 * 0.5)
        self.assertAlmostEqual(meter.total_cost, 0.2 * 0.5)
        # Costs and savings together: the price of all the energy used
        self.assertAlmostEqual(
            meter.total_cost + meter.total_savings, meter.total_kwh * 0.5
        )
        for period in Period:
            self.assertAlmostEqual(meter.periods[period].savings, 0.3)

    def test_no_savings_beyond_what_is_used(self):
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 17, 10))
        meter.set_power(400, at(2026, 10, 17, 10))
        meter.set_solar_power(1000, at(2026, 10, 17, 10))
        meter.advance(at(2026, 10, 17, 11))
        self.assertAlmostEqual(meter.total_savings, 0.4)

    def test_savings_start_again_at_midnight(self):
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 17, 23))
        meter.set_power(1000, at(2026, 10, 17, 23))
        meter.set_solar_power(1000, at(2026, 10, 17, 23))
        meter.advance(at(2026, 10, 18, 1))
        self.assertAlmostEqual(meter.total_savings, 2.0)
        self.assertAlmostEqual(meter.periods[Period.DAY].savings, 1.0)
        self.assertAlmostEqual(meter.periods[Period.MONTH].savings, 2.0)

    def test_restore_savings_separately_from_costs(self):
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 17, 10))
        meter.restore_period(Period.DAY, 1.5, at(2026, 10, 17))
        meter.restore_period(Period.DAY, 0.7, at(2026, 10, 17), savings=True)
        meter.restore_period(Period.MONTH, 3.0, at(2026, 9, 1), savings=True)
        self.assertEqual(meter.periods[Period.DAY].cost, 1.5)
        self.assertEqual(meter.periods[Period.DAY].savings, 0.7)
        self.assertEqual(meter.periods[Period.MONTH].savings, 0)  # last month

    def test_restore_period_only_while_it_runs(self):
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 17, 10))
        meter.restore_period(Period.DAY, 1.5, at(2026, 10, 17))
        meter.restore_period(Period.MONTH, 4.0, at(2026, 10, 1))
        meter.restore_period(Period.YEAR, 9.0, at(2025, 1, 1))  # last year
        self.assertEqual(meter.periods[Period.DAY].cost, 1.5)
        self.assertEqual(meter.periods[Period.MONTH].cost, 4.0)
        self.assertEqual(meter.periods[Period.YEAR].cost, 0)

    def test_restore_matches_a_time_read_back_from_text(self):
        # The last reset comes back from the saved state as text with an offset.
        meter = cost.CostMeter(price=1.0, now=at(2026, 10, 17, 10))
        start = datetime.fromisoformat(at(2026, 10, 17).isoformat())
        meter.restore_period(Period.DAY, 1.5, start)
        self.assertEqual(meter.periods[Period.DAY].cost, 1.5)


if __name__ == "__main__":
    unittest.main()
