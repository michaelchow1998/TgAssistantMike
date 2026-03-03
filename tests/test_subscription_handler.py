# tests/test_subscription_handler.py
# ============================================================
# Unit tests for _calc_next_billing() in subscription.py.
# This is a pure function (no DB / Telegram calls) so no
# mocking is needed.
# ============================================================

import pytest
from handlers.subscription import _calc_next_billing


class TestCalcNextBillingMonthly:
    def test_monthly_standard(self):
        assert _calc_next_billing("2026-01-15", "monthly", 15) == "2026-02-15"

    def test_monthly_end_of_year_wraps(self):
        assert _calc_next_billing("2026-12-15", "monthly", 15) == "2027-01-15"

    def test_monthly_mid_year(self):
        assert _calc_next_billing("2026-06-10", "monthly", 10) == "2026-07-10"

    def test_monthly_day31_into_april(self):
        # April has 30 days → day clamps to 30
        assert _calc_next_billing("2026-03-31", "monthly", 31) == "2026-04-30"

    def test_monthly_day31_into_february(self):
        # 2026 is not a leap year → Feb has 28 days
        assert _calc_next_billing("2026-01-31", "monthly", 31) == "2026-02-28"

    def test_monthly_day29_into_february_non_leap(self):
        assert _calc_next_billing("2026-01-29", "monthly", 29) == "2026-02-28"

    def test_monthly_day28_into_february(self):
        # 28 is always valid in February
        assert _calc_next_billing("2026-01-28", "monthly", 28) == "2026-02-28"

    def test_monthly_november_to_december(self):
        assert _calc_next_billing("2026-11-15", "monthly", 15) == "2026-12-15"


class TestCalcNextBillingQuarterly:
    def test_quarterly_standard(self):
        assert _calc_next_billing("2026-01-15", "quarterly", 15) == "2026-04-15"

    def test_quarterly_wraps_year(self):
        assert _calc_next_billing("2026-11-15", "quarterly", 15) == "2027-02-15"

    def test_quarterly_day30_into_february(self):
        # November + 3 months = February; 30 → clamp to 28
        assert _calc_next_billing("2025-11-30", "quarterly", 30) == "2026-02-28"

    def test_quarterly_mid_year(self):
        assert _calc_next_billing("2026-04-01", "quarterly", 1) == "2026-07-01"


class TestCalcNextBillingYearly:
    def test_yearly_standard(self):
        assert _calc_next_billing("2026-01-15", "yearly", 15) == "2027-01-15"

    def test_yearly_preserves_month(self):
        assert _calc_next_billing("2026-06-20", "yearly", 20) == "2027-06-20"

    def test_yearly_december(self):
        assert _calc_next_billing("2026-12-01", "yearly", 1) == "2027-12-01"
