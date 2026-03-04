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


# ================================================================
#  _sec_todos — morning todo section
# ================================================================

class TestSecTodos:
    def _make_todo(self, title, due_date=""):
        return {"title": title, "due_date": due_date, "priority": "medium"}

    def test_no_todos_returns_none(self):
        svc = _make_service()
        result = svc._sec_todos({"todos": []})
        assert result is None

    def test_todos_all_no_due_date_shows_count(self):
        # Todos with no due date → not urgently due → should still show count
        todos = [
            self._make_todo("Task A"),
            self._make_todo("Task B"),
            self._make_todo("Task C"),
        ]
        svc = _make_service()
        result = svc._sec_todos({"todos": todos})
        assert result is not None
        assert "3" in result
        assert "無近期到期" in result

    def test_todos_with_no_urgent_items_shows_count(self):
        # Todos due far in the future (beyond 3-day window) → show count
        todos = [self._make_todo("Far todo", due_date="2026-12-31")]
        svc = _make_service()
        result = svc._sec_todos({"todos": todos})
        assert result is not None
        assert "1" in result
        assert "無近期到期" in result

    def test_urgent_todos_show_count_in_header(self):
        # Overdue todo → normal urgent display, but count in header
        todos = [self._make_todo("Overdue", due_date="2026-02-01")]
        svc = _make_service()
        result = svc._sec_todos({"todos": todos})
        assert result is not None
        assert "1" in result           # count
        assert "逾期" in result        # urgency shown

    def test_count_includes_no_due_date_todos(self):
        # 1 overdue + 1 no-due-date → count = 2
        todos = [
            self._make_todo("Overdue", due_date="2026-02-01"),
            self._make_todo("No due"),
        ]
        svc = _make_service()
        result = svc._sec_todos({"todos": todos})
        assert "2" in result


# ================================================================
#  _sec_health — evening health section
# ================================================================

class TestSecHealth:
    def test_no_meals_returns_none(self):
        svc = _make_service()
        with patch("reminders.reminder_service.get_today_meals", return_value=[]), \
             patch("reminders.reminder_service.get_health_settings", return_value=None), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID):
            result = svc._sec_health()
            assert result is None

    def test_meals_present_shows_meal_lines(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("600"), "date": TODAY},
            {"meal_type": "lunch",     "calories": Decimal("700"), "date": TODAY},
            {"meal_type": "dinner",    "calories": Decimal("500"), "date": TODAY},
        ]
        svc = _make_service()
        with patch("reminders.reminder_service.get_today_meals", return_value=meals), \
             patch("reminders.reminder_service.get_health_settings", return_value=None), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID):
            result = svc._sec_health()
            assert result is not None
            assert "早餐" in result
            assert "600" in result
            assert "午餐" in result
            assert "700" in result
            assert "晚餐" in result
            assert "500" in result

    def test_unrecorded_meal_shown_as_not_recorded(self):
        meals = [{"meal_type": "breakfast", "calories": Decimal("600"), "date": TODAY}]
        svc = _make_service()
        with patch("reminders.reminder_service.get_today_meals", return_value=meals), \
             patch("reminders.reminder_service.get_health_settings", return_value=None), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID):
            result = svc._sec_health()
            assert "（未記錄）" in result

    def test_no_settings_hides_goal_line(self):
        meals = [{"meal_type": "breakfast", "calories": Decimal("600"), "date": TODAY}]
        svc = _make_service()
        with patch("reminders.reminder_service.get_today_meals", return_value=meals), \
             patch("reminders.reminder_service.get_health_settings", return_value=None), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID):
            result = svc._sec_health()
            assert "每日目標" not in result

    def test_all_main_meals_with_settings_shows_goal_progress(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("500"), "date": TODAY},
            {"meal_type": "lunch",     "calories": Decimal("600"), "date": TODAY},
            {"meal_type": "dinner",    "calories": Decimal("500"), "date": TODAY},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        svc = _make_service()
        with patch("reminders.reminder_service.get_today_meals", return_value=meals), \
             patch("reminders.reminder_service.get_health_settings", return_value=settings), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID):
            result = svc._sec_health()
            assert "每日目標" in result
            assert "1,700" in result   # goal = 2200 - 500
            assert "剩餘" in result    # 1700 - 1600 = 100 remaining
            assert "✅" in result

    def test_over_goal_shows_surplus(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("700"), "date": TODAY},
            {"meal_type": "lunch",     "calories": Decimal("800"), "date": TODAY},
            {"meal_type": "dinner",    "calories": Decimal("500"), "date": TODAY},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        svc = _make_service()
        with patch("reminders.reminder_service.get_today_meals", return_value=meals), \
             patch("reminders.reminder_service.get_health_settings", return_value=settings), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID):
            result = svc._sec_health()
            assert "超出" in result
            assert "⚠️" in result

    def test_missing_main_meal_shows_tdee_fill_warning(self):
        meals = [{"meal_type": "breakfast", "calories": Decimal("600"), "date": TODAY}]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        svc = _make_service()
        with patch("reminders.reminder_service.get_today_meals", return_value=meals), \
             patch("reminders.reminder_service.get_health_settings", return_value=settings), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID):
            result = svc._sec_health()
            assert "缺少主食記錄" in result
            assert "TDEE" in result
            assert "2,200" in result


class TestEveningPreviewIncludesHealth:
    def test_health_section_included_when_meals_exist(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("600"), "date": TODAY},
            {"meal_type": "lunch",     "calories": Decimal("700"), "date": TODAY},
            {"meal_type": "dinner",    "calories": Decimal("500"), "date": TODAY},
        ]
        svc = _make_service()
        with patch("reminders.reminder_service.get_schedules_effective_on", return_value=[]), \
             patch("reminders.reminder_service.get_pending_todos", return_value=[]), \
             patch("reminders.reminder_service.get_pending_payments", return_value=[]), \
             patch("reminders.reminder_service.get_active_subscriptions", return_value=[]), \
             patch("reminders.reminder_service.get_active_work", return_value=[]), \
             patch("reminders.reminder_service.get_today_meals", return_value=meals), \
             patch("reminders.reminder_service.get_health_settings", return_value=None), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID), \
             patch("reminders.reminder_service.send") as mock_send:
            svc.evening_preview()
            msg = mock_send.call_args[0][0]
            assert "今日健康" in msg

    def test_health_section_omitted_when_no_meals(self):
        svc = _make_service()
        with patch("reminders.reminder_service.get_schedules_effective_on", return_value=[]), \
             patch("reminders.reminder_service.get_pending_todos", return_value=[]), \
             patch("reminders.reminder_service.get_pending_payments", return_value=[]), \
             patch("reminders.reminder_service.get_active_subscriptions", return_value=[]), \
             patch("reminders.reminder_service.get_active_work", return_value=[]), \
             patch("reminders.reminder_service.get_today_meals", return_value=[]), \
             patch("reminders.reminder_service.get_health_settings", return_value=None), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID), \
             patch("reminders.reminder_service.send") as mock_send:
            svc.evening_preview()
            msg = mock_send.call_args[0][0]
            assert "今日健康" not in msg


# ================================================================
#  _generate_recurring_records — 1st of month auto-generation
# ================================================================

class TestFirstOfMonthGeneration:
    def _make_template(self):
        from decimal import Decimal
        return {
            "SK": "FIN_RECURRING#ULID001",
            "title": "薪水",
            "amount": Decimal("20000"),
            "fin_type": "income",
            "day_of_month": 1,
            "category": "salary",
            "end_month": None,
            "status": "active",
        }

    def test_generates_record_on_first_of_month(self):
        svc = _make_service(today_str="2026-04-01")
        template = self._make_template()
        with patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID), \
             patch("reminders.reminder_service.get_active_recurring_templates", return_value=[template]), \
             patch("reminders.reminder_service.get_fin_records_for_month", return_value=[]), \
             patch("reminders.reminder_service.put_item") as mock_put, \
             patch("reminders.reminder_service.next_short_id", return_value=1), \
             patch("reminders.reminder_service.generate_ulid", return_value="NEWULID"):
            result = svc._generate_recurring_records()
            assert mock_put.called
            assert result == 1
            # Verify the item structure
            item = mock_put.call_args[0][0]
            assert item["fin_type"] == "income"
            assert item["title"] == "薪水"
            assert item["recurring_id"] == "ULID001"
            assert item["date"] == "2026-04-01"

    def test_skips_if_record_already_exists(self):
        from decimal import Decimal
        svc = _make_service(today_str="2026-04-01")
        template = self._make_template()
        existing_record = {
            "SK": "FIN#EXISTING",
            "recurring_id": "ULID001",
            "fin_type": "income",
        }
        with patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID), \
             patch("reminders.reminder_service.get_active_recurring_templates", return_value=[template]), \
             patch("reminders.reminder_service.get_fin_records_for_month", return_value=[existing_record]), \
             patch("reminders.reminder_service.put_item") as mock_put:
            result = svc._generate_recurring_records()
            assert not mock_put.called
            assert result == 0

    def test_not_first_of_month_skips(self):
        svc = _make_service(today_str="2026-04-05")
        with patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID), \
             patch("reminders.reminder_service.get_active_recurring_templates") as mock_tpl, \
             patch("reminders.reminder_service.put_item") as mock_put:
            result = svc._generate_recurring_records()
            assert not mock_tpl.called
            assert not mock_put.called
            assert result == 0

    def test_skips_template_past_end_month(self):
        svc = _make_service(today_str="2026-04-01")
        template = self._make_template()
        template["end_month"] = "2026-03"  # already past
        with patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID), \
             patch("reminders.reminder_service.get_active_recurring_templates", return_value=[template]), \
             patch("reminders.reminder_service.get_fin_records_for_month", return_value=[]), \
             patch("reminders.reminder_service.put_item") as mock_put:
            result = svc._generate_recurring_records()
            assert not mock_put.called
            assert result == 0

    def test_includes_template_within_end_month(self):
        svc = _make_service(today_str="2026-04-01")
        template = self._make_template()
        template["end_month"] = "2026-06"  # not yet past
        with patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID), \
             patch("reminders.reminder_service.get_active_recurring_templates", return_value=[template]), \
             patch("reminders.reminder_service.get_fin_records_for_month", return_value=[]), \
             patch("reminders.reminder_service.put_item") as mock_put, \
             patch("reminders.reminder_service.next_short_id", return_value=1), \
             patch("reminders.reminder_service.generate_ulid", return_value="NEWULID"):
            result = svc._generate_recurring_records()
            assert mock_put.called
            assert result == 1

    def test_morning_briefing_includes_generated_count(self):
        svc = _make_service(today_str="2026-04-01")
        template = self._make_template()
        with patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID), \
             patch("reminders.reminder_service.get_active_recurring_templates", return_value=[template]), \
             patch("reminders.reminder_service.get_fin_records_for_month", return_value=[]), \
             patch("reminders.reminder_service.put_item"), \
             patch("reminders.reminder_service.next_short_id", return_value=1), \
             patch("reminders.reminder_service.generate_ulid", return_value="NEWULID"), \
             patch("reminders.reminder_service.get_schedules_effective_on", return_value=[]), \
             patch("reminders.reminder_service.get_pending_todos", return_value=[]), \
             patch("reminders.reminder_service.get_pending_payments", return_value=[]), \
             patch("reminders.reminder_service.get_active_subscriptions", return_value=[]), \
             patch("reminders.reminder_service.get_active_work", return_value=[]), \
             patch("reminders.reminder_service.send") as mock_send:
            svc.morning_briefing()
            msg = mock_send.call_args[0][0]
            assert "週期財務記錄" in msg
            assert "1" in msg