# tests/test_reminder_service.py
# ============================================================
# Unit tests for ReminderService section builders.
# ============================================================

import pytest
from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from reminders.reminder_service import ReminderService
from reminders.db_queries import get_today_meals, get_health_settings


OWNER_ID = 12345
TODAY = "2026-03-03"


def _make_service(today_str=TODAY):
    """Create a ReminderService bypassing __init__ with a fixed date."""
    svc = object.__new__(ReminderService)
    d = date.fromisoformat(today_str)
    svc.today = d
    svc.today_s = today_str
    svc.wd = ["一", "二", "三", "四", "五", "六", "日"][d.weekday()]
    svc.end_s = (d + timedelta(days=3)).isoformat()
    return svc


# ================================================================
#  DB query helpers
# ================================================================

class TestGetTodayMeals:
    def test_calls_gsi1_with_correct_pk_and_prefix(self):
        with patch("reminders.db_queries._db_query_gsi1") as mock_q, \
             patch("reminders.db_queries._db_get_item"):
            get_today_meals(OWNER_ID, TODAY)
            mock_q.assert_called_once()
            call_kwargs = mock_q.call_args
            assert call_kwargs[1]["gsi1pk"] == f"USER#{OWNER_ID}#HEALTH"

    def test_returns_list_from_query(self):
        fake_meals = [{"meal_type": "breakfast", "calories": Decimal("500")}]
        with patch("reminders.db_queries._db_query_gsi1", return_value=fake_meals), \
             patch("reminders.db_queries._db_get_item"):
            result = get_today_meals(OWNER_ID, TODAY)
            assert result == fake_meals


class TestGetHealthSettings:
    def test_calls_get_item_with_correct_keys(self):
        with patch("reminders.db_queries._db_get_item") as mock_get, \
             patch("reminders.db_queries._db_query_gsi1"):
            get_health_settings(OWNER_ID)
            mock_get.assert_called_once_with(
                f"USER#{OWNER_ID}", "HEALTH_SETTINGS#active"
            )

    def test_returns_none_when_not_found(self):
        with patch("reminders.db_queries._db_get_item", return_value=None), \
             patch("reminders.db_queries._db_query_gsi1"):
            result = get_health_settings(OWNER_ID)
            assert result is None

    def test_returns_settings_dict_when_found(self):
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("reminders.db_queries._db_get_item", return_value=settings), \
             patch("reminders.db_queries._db_query_gsi1"):
            result = get_health_settings(OWNER_ID)
            assert result == settings