# tests/test_health_handler.py
# ============================================================
# Unit tests for webhook_handler/handlers/health.py.
# All external calls (DynamoDB, Telegram, SSM) are mocked.
# ============================================================

import pytest
from decimal import Decimal
from unittest.mock import patch, call, MagicMock

from handlers.health import (
    handle_set_health,
    handle_add_meal,
    handle_health,
    handle_step,
    handle_callback,
    _parse_calories,
    _parse_positive_int,
    _parse_non_negative_int,
    _effective_daily_calories,
)

OWNER_ID = 111
CHAT_ID = 222
MSG_ID = 333
USER_ID = OWNER_ID
TODAY = "2026-03-03"
WEEKDAY = "週二"


# ================================================================
#  Private parsers
# ================================================================

class TestParseCalories:
    def test_minimum_valid(self):
        assert _parse_calories("1") == 1

    def test_maximum_valid(self):
        assert _parse_calories("9999") == 9999

    def test_mid_range(self):
        assert _parse_calories("800") == 800

    def test_zero_is_invalid(self):
        assert _parse_calories("0") is None

    def test_over_max_is_invalid(self):
        assert _parse_calories("10000") is None

    def test_string_is_invalid(self):
        assert _parse_calories("abc") is None

    def test_negative_is_invalid(self):
        assert _parse_calories("-1") is None

    def test_decimal_is_invalid(self):
        assert _parse_calories("800.5") is None

    def test_whitespace_stripped(self):
        assert _parse_calories("  500  ") == 500


class TestParsePositiveInt:
    def test_one_is_valid(self):
        assert _parse_positive_int("1") == 1

    def test_large_is_valid(self):
        assert _parse_positive_int("9999") == 9999

    def test_zero_is_invalid(self):
        assert _parse_positive_int("0") is None

    def test_negative_is_invalid(self):
        assert _parse_positive_int("-100") is None

    def test_string_is_invalid(self):
        assert _parse_positive_int("abc") is None


class TestParseNonNegativeInt:
    def test_zero_is_valid(self):
        assert _parse_non_negative_int("0") == 0

    def test_positive_is_valid(self):
        assert _parse_non_negative_int("500") == 500

    def test_negative_is_invalid(self):
        assert _parse_non_negative_int("-1") is None

    def test_string_is_invalid(self):
        assert _parse_non_negative_int("abc") is None


# ================================================================
#  handle_set_health — command entry point
# ================================================================

class TestHandleSetHealth:
    def test_no_existing_settings_starts_conversation(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.set_conversation") as mock_set_conv, \
             patch("handlers.health.send_message") as mock_send:
            handle_set_health(USER_ID, CHAT_ID)
            mock_set_conv.assert_called_once_with(USER_ID, "set_health", "tdee", {})
            mock_send.assert_called_once()
            # No existing-settings preamble
            assert "目前設定" not in mock_send.call_args[0][1]

    def test_with_existing_settings_shows_preamble(self):
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.set_conversation"), \
             patch("handlers.health.send_message") as mock_send:
            handle_set_health(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "目前設定" in msg
            assert "2,200" in msg
            assert "500" in msg
            assert "1,700" in msg  # daily goal = 2200 - 500


# ================================================================
#  handle_add_meal — command entry point
# ================================================================

class TestHandleAddMeal:
    def test_starts_conversation_and_asks_meal_type(self):
        with patch("handlers.health.set_conversation") as mock_set_conv, \
             patch("handlers.health.send_message") as mock_send:
            handle_add_meal(USER_ID, CHAT_ID)
            mock_set_conv.assert_called_once_with(USER_ID, "health", "meal_type", {})
            mock_send.assert_called_once()
            # The meal-type keyboard should be attached
            _, kwargs = mock_send.call_args
            assert kwargs.get("reply_markup") is not None


# ================================================================
#  handle_health — /health command
# ================================================================

class TestHandleHealth:
    def _today_mocks(self, mock_send):
        """Helper: verify a today-summary call happened."""
        mock_send.assert_called_once()

    def test_no_args_shows_today_summary(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.get_weekday_name", return_value=WEEKDAY), \
             patch("handlers.health.query_gsi1", return_value=[]), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID)
            mock_send.assert_called_once()
            assert TODAY in mock_send.call_args[0][1]

    def test_valid_month_arg_shows_monthly_report(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.query_gsi1", return_value=[]) as mock_query, \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2026-03")
            mock_query.assert_called_once()
            mock_send.assert_called_once()
            assert "2026-03" in mock_send.call_args[0][1]

    def test_invalid_arg_shows_error(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "not-a-month")
            mock_send.assert_called_once()
            assert "❌" in mock_send.call_args[0][1]

    def test_invalid_month_number_shows_error(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2026-13")
            mock_send.assert_called_once()
            assert "❌" in mock_send.call_args[0][1]

    def test_empty_month_arg_treated_as_today(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.get_weekday_name", return_value=WEEKDAY), \
             patch("handlers.health.query_gsi1", return_value=[]), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "")
            assert TODAY in mock_send.call_args[0][1]


# ================================================================
#  handle_step — set_health flow
# ================================================================

class TestHandleStepSetHealth:
    def test_tdee_step_valid_advances_to_deficit(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.update_conversation") as mock_update, \
             patch("handlers.health.send_message"):
            handle_step(USER_ID, CHAT_ID, "2200", "tdee", {})
            mock_update.assert_called_once_with(USER_ID, "deficit", {"tdee": 2200})

    def test_tdee_step_invalid_sends_error(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.update_conversation") as mock_update, \
             patch("handlers.health.send_message") as mock_send:
            handle_step(USER_ID, CHAT_ID, "abc", "tdee", {})
            mock_update.assert_not_called()
            assert "❌" in mock_send.call_args[0][1]

    def test_tdee_step_zero_is_invalid(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.update_conversation") as mock_update, \
             patch("handlers.health.send_message"):
            handle_step(USER_ID, CHAT_ID, "0", "tdee", {})
            mock_update.assert_not_called()

    def test_deficit_step_valid_advances_to_confirm(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.update_conversation") as mock_update, \
             patch("handlers.health.send_message"), \
             patch("handlers.health.build_confirm_keyboard", return_value={}):
            data = {"tdee": 2200}
            handle_step(USER_ID, CHAT_ID, "500", "deficit", data)
            mock_update.assert_called_once_with(USER_ID, "confirm", {"tdee": 2200, "deficit": 500})

    def test_deficit_step_zero_is_accepted(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.update_conversation") as mock_update, \
             patch("handlers.health.send_message"), \
             patch("handlers.health.build_confirm_keyboard", return_value={}):
            data = {"tdee": 2200}
            handle_step(USER_ID, CHAT_ID, "0", "deficit", data)
            mock_update.assert_called_once()
            assert mock_update.call_args[0][2]["deficit"] == 0

    def test_deficit_step_negative_is_rejected(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.update_conversation") as mock_update, \
             patch("handlers.health.send_message"):
            data = {"tdee": 2200}
            handle_step(USER_ID, CHAT_ID, "-100", "deficit", data)
            mock_update.assert_not_called()


# ================================================================
#  handle_step — add_meal flow
# ================================================================

class TestHandleStepAddMeal:
    def _common_patches(self):
        return [
            patch("handlers.health.get_owner_id", return_value=OWNER_ID),
            patch("handlers.health.get_today", return_value=TODAY),
            patch("handlers.health.get_now", return_value=MagicMock(isoformat=lambda: "ts")),
            patch("handlers.health.put_item"),
            patch("handlers.health.delete_conversation"),
            patch("handlers.health.send_message"),
            patch("handlers.health.query_gsi1", return_value=[]),
            patch("handlers.health.get_item", return_value=None),
            patch("handlers.health.get_weekday_name", return_value=WEEKDAY),
        ]

    def test_calories_valid_saves_meal(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.get_now") as mock_now, \
             patch("handlers.health.put_item") as mock_put, \
             patch("handlers.health.delete_conversation") as mock_del, \
             patch("handlers.health.send_message"), \
             patch("handlers.health.query_gsi1", return_value=[]), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.get_weekday_name", return_value=WEEKDAY):
            mock_now.return_value.isoformat.return_value = "2026-03-03T12:00:00"
            data = {"meal_type": "lunch", "date": TODAY}
            handle_step(USER_ID, CHAT_ID, "800", "calories", data)
            mock_put.assert_called_once()
            item = mock_put.call_args[0][0]
            assert item["PK"] == f"USER#{OWNER_ID}"
            assert item["SK"] == f"HEALTH#{TODAY}#lunch"
            assert item["calories"] == Decimal("800")
            assert item["meal_type"] == "lunch"
            assert item["GSI1PK"] == f"USER#{OWNER_ID}#HEALTH"
            assert item["GSI1SK"] == f"{TODAY}#lunch"
            mock_del.assert_called_once_with(USER_ID)

    def test_calories_invalid_sends_error(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.put_item") as mock_put, \
             patch("handlers.health.delete_conversation") as mock_del, \
             patch("handlers.health.send_message") as mock_send:
            data = {"meal_type": "lunch", "date": TODAY}
            handle_step(USER_ID, CHAT_ID, "0", "calories", data)
            mock_put.assert_not_called()
            mock_del.assert_not_called()
            assert "❌" in mock_send.call_args[0][1]

    def test_calories_missing_meal_type_clears_conversation(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.put_item") as mock_put, \
             patch("handlers.health.delete_conversation") as mock_del, \
             patch("handlers.health.send_message"):
            # data has no meal_type
            handle_step(USER_ID, CHAT_ID, "800", "calories", {})
            mock_put.assert_not_called()
            mock_del.assert_called_once_with(USER_ID)

    def test_calories_send_confirmation_then_summary(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.get_now") as mock_now, \
             patch("handlers.health.put_item"), \
             patch("handlers.health.delete_conversation"), \
             patch("handlers.health.send_message") as mock_send, \
             patch("handlers.health.query_gsi1", return_value=[]), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.get_weekday_name", return_value=WEEKDAY):
            mock_now.return_value.isoformat.return_value = "ts"
            data = {"meal_type": "dinner", "date": TODAY}
            handle_step(USER_ID, CHAT_ID, "900", "calories", data)
            # send_message called twice: confirmation + today summary
            assert mock_send.call_count == 2

    def test_unknown_step_sends_error(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.send_message") as mock_send:
            handle_step(USER_ID, CHAT_ID, "anything", "unknown_step", {})
            assert "🚧" in mock_send.call_args[0][1]


# ================================================================
#  handle_callback — meal type selection
# ================================================================

class TestHandleCallbackMealSelection:
    @pytest.mark.parametrize("cb_data,expected_type", [
        ("meal_breakfast", "breakfast"),
        ("meal_lunch",     "lunch"),
        ("meal_dinner",    "dinner"),
        ("meal_other",     "other"),
    ])
    def test_meal_callback_stores_type_and_advances(self, cb_data, expected_type):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.update_conversation") as mock_update, \
             patch("handlers.health.edit_message_text"):
            handle_callback(USER_ID, CHAT_ID, MSG_ID, cb_data, "meal_type", {})
            mock_update.assert_called_once()
            _, new_step, new_data = mock_update.call_args[0]
            assert new_step == "calories"
            assert new_data["meal_type"] == expected_type
            assert new_data["date"] == TODAY

    def test_meal_callback_edits_original_message(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.update_conversation"), \
             patch("handlers.health.edit_message_text") as mock_edit:
            handle_callback(USER_ID, CHAT_ID, MSG_ID, "meal_lunch", "meal_type", {})
            mock_edit.assert_called_once()
            assert mock_edit.call_args[0][0] == CHAT_ID
            assert mock_edit.call_args[0][1] == MSG_ID
            assert isinstance(mock_edit.call_args[0][2], str)


# ================================================================
#  handle_callback — set_health confirm / cancel
# ================================================================

class TestHandleCallbackSetHealth:
    def test_sethealth_confirm_saves_and_deletes_conv(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_now") as mock_now, \
             patch("handlers.health.put_item") as mock_put, \
             patch("handlers.health.delete_conversation") as mock_del, \
             patch("handlers.health.edit_message_text") as mock_edit:
            mock_now.return_value.isoformat.return_value = "2026-03-03T00:00:00"
            data = {"tdee": 2200, "deficit": 500}
            handle_callback(USER_ID, CHAT_ID, MSG_ID, "sethealth_confirm", "confirm", data)
            mock_put.assert_called_once()
            item = mock_put.call_args[0][0]
            assert item["PK"] == f"USER#{OWNER_ID}"
            assert item["SK"] == "HEALTH_SETTINGS#active"
            assert item["tdee"] == Decimal("2200")
            assert item["deficit"] == Decimal("500")
            mock_del.assert_called_once_with(USER_ID)
            mock_edit.assert_called_once()

    def test_sethealth_confirm_message_shows_goal(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_now") as mock_now, \
             patch("handlers.health.put_item"), \
             patch("handlers.health.delete_conversation"), \
             patch("handlers.health.edit_message_text") as mock_edit:
            mock_now.return_value.isoformat.return_value = "ts"
            data = {"tdee": 2200, "deficit": 500}
            handle_callback(USER_ID, CHAT_ID, MSG_ID, "sethealth_confirm", "confirm", data)
            msg = mock_edit.call_args[0][2]
            assert "1,700" in msg  # daily goal = 2200 - 500
            assert "✅" in msg

    def test_sethealth_cancel_deletes_conv(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.delete_conversation") as mock_del, \
             patch("handlers.health.edit_message_text") as mock_edit:
            handle_callback(USER_ID, CHAT_ID, MSG_ID, "sethealth_cancel", "confirm", {})
            mock_del.assert_called_once_with(USER_ID)
            mock_edit.assert_called_once()
            assert "❌" in mock_edit.call_args[0][2]


# ================================================================
#  Today summary content — via handle_health with meal data
# ================================================================

class TestTodaySummaryContent:
    def test_shows_recorded_meals(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("650"), "date": TODAY},
            {"meal_type": "lunch",     "calories": Decimal("800"), "date": TODAY},
        ]
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.get_weekday_name", return_value=WEEKDAY), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "650" in msg
            assert "800" in msg
            assert "1,450" in msg   # total = 650 + 800

    def test_shows_remaining_when_under_goal(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("650"), "date": TODAY},
            {"meal_type": "lunch",     "calories": Decimal("800"), "date": TODAY},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.get_weekday_name", return_value=WEEKDAY), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "1,700" in msg   # daily goal
            assert "250" in msg     # remaining = 1700 - 1450
            assert "✅" in msg

    def test_shows_surplus_when_over_goal(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("1000"), "date": TODAY},
            {"meal_type": "lunch",     "calories": Decimal("1000"), "date": TODAY},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.get_weekday_name", return_value=WEEKDAY), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "300" in msg    # surplus = 2000 - 1700
            assert "⚠️" in msg

    def test_no_settings_hides_goal_section(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.get_weekday_name", return_value=WEEKDAY), \
             patch("handlers.health.query_gsi1", return_value=[]), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "目標進度" not in msg


# ================================================================
#  Monthly report content — via handle_health with YYYY-MM
# ================================================================

class TestMonthlyReportContent:
    def test_no_meals_shows_zero_days(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.query_gsi1", return_value=[]), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2026-03")
            msg = mock_send.call_args[0][1]
            assert "0 天" in msg

    def test_with_meals_counts_recording_days(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("650"),  "date": "2026-03-01"},
            {"meal_type": "lunch",     "calories": Decimal("850"),  "date": "2026-03-01"},
            {"meal_type": "breakfast", "calories": Decimal("700"),  "date": "2026-03-02"},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2026-03")
            msg = mock_send.call_args[0][1]
            assert "2 天" in msg        # two recording days
            # Day 1: 650+850=1500 ≤ 1700 ✓  Day 2: 700 ≤ 1700 ✓
            assert "達標天數：2" in msg
            assert "超標天數：0" in msg

    def test_over_goal_day_counted_correctly(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("1000"), "date": "2026-03-01"},
            {"meal_type": "lunch",     "calories": Decimal("1000"), "date": "2026-03-01"},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2026-03")
            msg = mock_send.call_args[0][1]
            # Day 1 total = 2000 > 1700 goal → over
            assert "超標天數：1" in msg
            assert "達標天數：0" in msg

    def test_target_total_calculated_for_full_month(self):
        # March has 31 days; daily goal = 1700; target_total = 1700 * 31 = 52700
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.query_gsi1", return_value=[]), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2026-03")
            msg = mock_send.call_args[0][1]
            assert "52,700" in msg


class TestEffectiveDailyCalories:
    def test_all_three_main_meals_present_returns_actual_sum(self):
        meal_map = {"breakfast": 500, "lunch": 700, "dinner": 600}
        calories, filled = _effective_daily_calories(meal_map, tdee=2000)
        assert calories == 1800
        assert filled is False

    def test_with_other_meal_also_all_main_present(self):
        meal_map = {"breakfast": 500, "lunch": 700, "dinner": 600, "other": 200}
        calories, filled = _effective_daily_calories(meal_map, tdee=2000)
        assert calories == 2000
        assert filled is False

    def test_missing_breakfast_returns_tdee(self):
        meal_map = {"lunch": 700, "dinner": 600}
        calories, filled = _effective_daily_calories(meal_map, tdee=2200)
        assert calories == 2200
        assert filled is True

    def test_missing_lunch_returns_tdee(self):
        meal_map = {"breakfast": 500, "dinner": 600}
        calories, filled = _effective_daily_calories(meal_map, tdee=2200)
        assert calories == 2200
        assert filled is True

    def test_missing_dinner_returns_tdee(self):
        meal_map = {"breakfast": 500, "lunch": 700}
        calories, filled = _effective_daily_calories(meal_map, tdee=2200)
        assert calories == 2200
        assert filled is True

    def test_empty_meal_map_with_tdee_returns_tdee(self):
        meal_map = {}
        calories, filled = _effective_daily_calories(meal_map, tdee=2200)
        assert calories == 2200
        assert filled is True

    def test_no_tdee_returns_actual_sum_regardless_of_missing(self):
        meal_map = {"breakfast": 500}   # missing lunch + dinner
        calories, filled = _effective_daily_calories(meal_map, tdee=None)
        assert calories == 500
        assert filled is False

    def test_only_other_meal_with_tdee_returns_tdee(self):
        meal_map = {"other": 300}   # no main meals
        calories, filled = _effective_daily_calories(meal_map, tdee=2000)
        assert calories == 2000
        assert filled is True
