# tests/test_bot_utils.py
# ============================================================
# Unit tests for shared/python/bot_utils.py
# Pure-function tests — only get_today / get_today_date are
# mocked to keep dates deterministic.
# ============================================================

import pytest
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

from bot_utils import (
    parse_date,
    parse_time,
    parse_amount,
    parse_percentage,
    parse_short_id,
    parse_day_of_month,
    validate_text_length,
    format_short_id,
    format_progress_bar,
    format_currency,
    format_date_short,
    format_date_full,
    get_weekday_name,
    days_until,
    days_until_display,
    is_past_date,
    escape_markdown,
    is_repeat_occurrence,
)
from bot_constants import NO_DUE_DATE_SENTINEL

# Fixed "today" used across tests: 2026-03-03 (Tuesday)
TODAY = date(2026, 3, 3)
TODAY_STR = "2026-03-03"


# ================================================================
#  parse_date — Chinese shortcuts
# ================================================================

class TestParseDateShortcuts:
    def test_jintian(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("今天") == "2026-03-03"

    def test_mingtian(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("明天") == "2026-03-04"

    def test_houtian(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("後天") == "2026-03-05"

    def test_da_houtian(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("大後天") == "2026-03-06"


# ================================================================
#  parse_date — next-week shortcuts
# ================================================================

class TestParseDateNextWeek:
    # Today is Tuesday 2026-03-03 (weekday index 1)
    # Next Monday: +6 days → 2026-03-09
    # Next Friday: +6+4 days → 2026-03-13
    # Next Sunday: +6+6 days → 2026-03-15

    def test_xia_zhou_yi(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("下週一") == "2026-03-09"

    def test_xia_zhou_yi_alt_spelling(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("下周一") == "2026-03-09"

    def test_xia_zhou_wu(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("下週五") == "2026-03-13"

    def test_xia_zhou_ri(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("下週日") == "2026-03-15"

    def test_xia_zhou_liu(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("下週六") == "2026-03-14"


# ================================================================
#  parse_date — next month
# ================================================================

class TestParseDateNextMonth:
    def test_next_month_day_15(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("下個月15號") == "2026-04-15"

    def test_next_month_day_clamped_to_30(self):
        # April has 30 days; day 31 should clamp to 30
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("下個月31號") == "2026-04-30"

    def test_next_month_wraps_year(self):
        # Today = December → next month = January next year
        dec = date(2026, 12, 1)
        with patch("bot_utils.get_today_date", return_value=dec):
            assert parse_date("下個月15號") == "2027-01-15"

    def test_next_month_feb_clamp(self):
        # Next month is February (28 days); day 30 clamps to 28
        jan = date(2026, 1, 15)
        with patch("bot_utils.get_today_date", return_value=jan):
            assert parse_date("下個月30號") == "2026-02-28"


# ================================================================
#  parse_date — ISO and MM/DD formats
# ================================================================

class TestParseDateFormats:
    def test_iso_hyphen(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("2026-03-15") == "2026-03-15"

    def test_iso_slash(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("2026/03/15") == "2026-03-15"

    def test_mmdd_future(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("03/15") == "2026-03-15"

    def test_mmdd_today(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("03/03") == "2026-03-03"

    def test_mmdd_past_wraps_next_year(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("03/01") == "2027-03-01"

    def test_mmdd_hyphen_separator(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("03-15") == "2026-03-15"

    def test_invalid_month(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("2026-13-01") is None

    def test_invalid_day(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("2026-02-30") is None

    def test_garbage_string(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("abc") is None

    def test_empty_string(self):
        with patch("bot_utils.get_today_date", return_value=TODAY):
            assert parse_date("") is None


# ================================================================
#  parse_time
# ================================================================

class TestParseTime:
    def test_valid_zero(self):
        assert parse_time("0:00") == "00:00"

    def test_valid_morning(self):
        assert parse_time("08:00") == "08:00"

    def test_valid_late_night(self):
        assert parse_time("23:59") == "23:59"

    def test_valid_no_leading_zero(self):
        assert parse_time("9:30") == "09:30"

    def test_invalid_hour_too_high(self):
        assert parse_time("24:00") is None

    def test_invalid_minute_too_high(self):
        assert parse_time("08:60") is None

    def test_invalid_format(self):
        assert parse_time("abc") is None

    def test_invalid_no_colon(self):
        assert parse_time("0800") is None

    def test_invalid_negative(self):
        assert parse_time("-1:00") is None


# ================================================================
#  parse_amount
# ================================================================

class TestParseAmount:
    def test_integer(self):
        assert parse_amount("100") == Decimal("100")

    def test_decimal_two_places(self):
        assert parse_amount("1500.50") == Decimal("1500.50")

    def test_max_value(self):
        assert parse_amount("9999999.99") == Decimal("9999999.99")

    def test_comma_separated(self):
        assert parse_amount("1,500") == Decimal("1500")

    def test_zero_is_invalid(self):
        assert parse_amount("0") is None

    def test_negative_is_invalid(self):
        assert parse_amount("-100") is None

    def test_too_many_decimals(self):
        assert parse_amount("9999999.999") is None

    def test_over_max_value(self):
        assert parse_amount("10000000") is None

    def test_string_abc(self):
        assert parse_amount("abc") is None

    def test_empty_string(self):
        assert parse_amount("") is None


# ================================================================
#  parse_percentage
# ================================================================

class TestParsePercentage:
    def test_zero(self):
        assert parse_percentage("0") == 0

    def test_fifty(self):
        assert parse_percentage("50") == 50

    def test_hundred(self):
        assert parse_percentage("100") == 100

    def test_with_percent_sign(self):
        assert parse_percentage("45%") == 45

    def test_below_zero(self):
        assert parse_percentage("-1") is None

    def test_above_hundred(self):
        assert parse_percentage("101") is None

    def test_string_abc(self):
        assert parse_percentage("abc") is None


# ================================================================
#  parse_short_id
# ================================================================

class TestParseShortId:
    def test_one(self):
        assert parse_short_id("1") == 1

    def test_large(self):
        assert parse_short_id("99999") == 99999

    def test_zero_is_invalid(self):
        assert parse_short_id("0") is None

    def test_negative_is_invalid(self):
        assert parse_short_id("-1") is None

    def test_string_is_invalid(self):
        assert parse_short_id("abc") is None


# ================================================================
#  parse_day_of_month
# ================================================================

class TestParseDayOfMonth:
    def test_one(self):
        assert parse_day_of_month("1") == 1

    def test_fifteen(self):
        assert parse_day_of_month("15") == 15

    def test_thirty_one(self):
        assert parse_day_of_month("31") == 31

    def test_zero_is_invalid(self):
        assert parse_day_of_month("0") is None

    def test_thirty_two_is_invalid(self):
        assert parse_day_of_month("32") is None

    def test_string_is_invalid(self):
        assert parse_day_of_month("abc") is None


# ================================================================
#  validate_text_length
# ================================================================

class TestValidateTextLength:
    def test_valid(self):
        ok, msg = validate_text_length("hello")
        assert ok is True
        assert msg is None

    def test_empty_string(self):
        ok, msg = validate_text_length("")
        assert ok is False
        assert msg is not None

    def test_too_long(self):
        ok, msg = validate_text_length("a" * 101)
        assert ok is False
        assert msg is not None

    def test_custom_min_len_fails(self):
        ok, msg = validate_text_length("hi", min_len=3)
        assert ok is False

    def test_custom_max_len_passes(self):
        ok, msg = validate_text_length("hello", max_len=10)
        assert ok is True

    def test_custom_max_len_fails(self):
        ok, msg = validate_text_length("hello world", max_len=5)
        assert ok is False


# ================================================================
#  format_short_id
# ================================================================

class TestFormatShortId:
    def test_one(self):
        assert format_short_id(1) == "00001"

    def test_hundred(self):
        assert format_short_id(100) == "00100"

    def test_max_5_digits(self):
        assert format_short_id(99999) == "99999"


# ================================================================
#  format_progress_bar
# ================================================================

class TestFormatProgressBar:
    def test_zero_percent(self):
        bar = format_progress_bar(0)
        assert "░" * 20 in bar
        assert "0%" in bar

    def test_fifty_percent(self):
        bar = format_progress_bar(50)
        assert "█" * 10 in bar
        assert "░" * 10 in bar
        assert "50%" in bar

    def test_hundred_percent(self):
        bar = format_progress_bar(100)
        assert "█" * 20 in bar
        assert "100%" in bar

    def test_forty_five_percent(self):
        # filled = round(45 / 5) = 9
        bar = format_progress_bar(45)
        assert "█" * 9 in bar
        assert "45%" in bar


# ================================================================
#  format_currency
# ================================================================

class TestFormatCurrency:
    def test_whole_amount(self):
        assert format_currency(Decimal("1500")) == "$1,500.00 HKD"

    def test_decimal_amount(self):
        assert format_currency(Decimal("0.50")) == "$0.50 HKD"

    def test_large_amount(self):
        assert format_currency(Decimal("9999999.99")) == "$9,999,999.99 HKD"

    def test_custom_currency(self):
        assert format_currency(Decimal("1500"), "USD") == "$1,500.00 USD"

    def test_integer_input_converted(self):
        assert format_currency(5000) == "$5,000.00 HKD"


# ================================================================
#  format_date_short
# ================================================================

class TestFormatDateShort:
    def test_normal_date(self):
        assert format_date_short("2026-03-15") == "03/15"

    def test_sentinel_returns_no_due_date(self):
        assert format_date_short(NO_DUE_DATE_SENTINEL) == "無截止日"

    def test_empty_string_returns_no_due_date(self):
        assert format_date_short("") == "無截止日"

    def test_none_returns_no_due_date(self):
        assert format_date_short(None) == "無截止日"


# ================================================================
#  format_date_full
# ================================================================

class TestFormatDateFull:
    def test_monday(self):
        # 2026-03-02 is a Monday
        assert format_date_full("2026-03-02") == "2026-03-02 (週一)"

    def test_tuesday(self):
        # 2026-03-03 is a Tuesday
        assert format_date_full("2026-03-03") == "2026-03-03 (週二)"

    def test_empty_string_returns_not_set(self):
        assert format_date_full("") == "未設定"

    def test_none_returns_not_set(self):
        assert format_date_full(None) == "未設定"


# ================================================================
#  get_weekday_name
# ================================================================

class TestGetWeekdayName:
    def test_monday(self):
        assert get_weekday_name("2026-03-02") == "週一"

    def test_tuesday(self):
        assert get_weekday_name("2026-03-03") == "週二"

    def test_wednesday(self):
        assert get_weekday_name("2026-03-04") == "週三"

    def test_saturday(self):
        assert get_weekday_name("2026-03-07") == "週六"

    def test_sunday(self):
        assert get_weekday_name("2026-03-08") == "週日"


# ================================================================
#  days_until  &  is_past_date
# ================================================================

class TestDaysUntil:
    def test_future_date(self):
        with patch("bot_utils.get_today", return_value=TODAY_STR):
            assert days_until("2026-03-10") == 7

    def test_past_date_is_negative(self):
        with patch("bot_utils.get_today", return_value=TODAY_STR):
            assert days_until("2026-03-01") == -2

    def test_today_is_zero(self):
        with patch("bot_utils.get_today", return_value=TODAY_STR):
            assert days_until("2026-03-03") == 0


class TestIsPastDate:
    def test_past_date(self):
        with patch("bot_utils.get_today", return_value=TODAY_STR):
            assert is_past_date("2026-03-01") is True

    def test_today_is_not_past(self):
        with patch("bot_utils.get_today", return_value=TODAY_STR):
            assert is_past_date("2026-03-03") is False

    def test_future_date_is_not_past(self):
        with patch("bot_utils.get_today", return_value=TODAY_STR):
            assert is_past_date("2026-03-04") is False


# ================================================================
#  days_until_display
# ================================================================

class TestDaysUntilDisplay:
    def test_today(self):
        with patch("bot_utils.get_today", return_value=TODAY_STR):
            assert days_until_display("2026-03-03") == "今天"

    def test_tomorrow(self):
        with patch("bot_utils.get_today", return_value=TODAY_STR):
            assert days_until_display("2026-03-04") == "明天"

    def test_day_after_tomorrow(self):
        with patch("bot_utils.get_today", return_value=TODAY_STR):
            assert days_until_display("2026-03-05") == "後天"

    def test_past_shows_overdue(self):
        with patch("bot_utils.get_today", return_value=TODAY_STR):
            result = days_until_display("2026-03-01")
            assert result == "逾期 2 天"

    def test_future_shows_remaining(self):
        with patch("bot_utils.get_today", return_value=TODAY_STR):
            result = days_until_display("2026-03-10")
            assert result == "剩 7 天"


# ================================================================
#  escape_markdown
# ================================================================

class TestEscapeMarkdown:
    def test_underscore(self):
        assert escape_markdown("hello_world") == "hello\\_world"

    def test_asterisk(self):
        assert escape_markdown("*bold*") == "\\*bold\\*"

    def test_backtick(self):
        assert escape_markdown("`code`") == "\\`code\\`"

    def test_bracket(self):
        assert escape_markdown("[link]") == "\\[link]"

    def test_no_special_chars(self):
        assert escape_markdown("hello world") == "hello world"

    def test_empty_string(self):
        assert escape_markdown("") == ""

    def test_none(self):
        assert escape_markdown(None) == ""

    def test_multiple_special_chars(self):
        result = escape_markdown("_*`[")
        assert result == "\\_\\*\\`\\["


# ================================================================
#  is_repeat_occurrence — daily
# ================================================================

class TestIsRepeatOccurrenceDaily:
    ITEM = {"date": "2026-03-01", "repeat_type": "daily"}

    def test_on_start_date(self):
        assert is_repeat_occurrence(self.ITEM, "2026-03-01") is True

    def test_after_start(self):
        assert is_repeat_occurrence(self.ITEM, "2026-03-15") is True

    def test_before_start_is_false(self):
        assert is_repeat_occurrence(self.ITEM, "2026-02-28") is False

    def test_after_end_date_is_false(self):
        item = {**self.ITEM, "repeat_end_date": "2026-03-10"}
        assert is_repeat_occurrence(item, "2026-03-11") is False

    def test_on_end_date_is_true(self):
        item = {**self.ITEM, "repeat_end_date": "2026-03-10"}
        assert is_repeat_occurrence(item, "2026-03-10") is True


# ================================================================
#  is_repeat_occurrence — weekly
# ================================================================

class TestIsRepeatOccurrenceWeekly:
    # Starts Mon 2026-03-02, repeats Mon(0) and Fri(4)
    ITEM = {"date": "2026-03-02", "repeat_type": "weekly", "repeat_days": [0, 4]}

    def test_monday_is_occurrence(self):
        assert is_repeat_occurrence(self.ITEM, "2026-03-02") is True

    def test_friday_is_occurrence(self):
        assert is_repeat_occurrence(self.ITEM, "2026-03-06") is True

    def test_tuesday_is_not_occurrence(self):
        assert is_repeat_occurrence(self.ITEM, "2026-03-03") is False

    def test_before_start_is_false(self):
        assert is_repeat_occurrence(self.ITEM, "2026-02-28") is False


# ================================================================
#  is_repeat_occurrence — monthly
# ================================================================

class TestIsRepeatOccurrenceMonthly:
    ITEM = {"date": "2026-03-15", "repeat_type": "monthly"}

    def test_on_start_date(self):
        assert is_repeat_occurrence(self.ITEM, "2026-03-15") is True

    def test_next_month_same_day(self):
        assert is_repeat_occurrence(self.ITEM, "2026-04-15") is True

    def test_different_day_in_same_month(self):
        assert is_repeat_occurrence(self.ITEM, "2026-04-14") is False

    def test_before_start_is_false(self):
        assert is_repeat_occurrence(self.ITEM, "2026-03-14") is False


# ================================================================
#  is_repeat_occurrence — custom (every N days)
# ================================================================

class TestIsRepeatOccurrenceCustom:
    # Every 3 days from 2026-03-01
    ITEM = {"date": "2026-03-01", "repeat_type": "custom", "repeat_interval": "3"}

    def test_start_date(self):
        # day 0: 0 % 3 == 0
        assert is_repeat_occurrence(self.ITEM, "2026-03-01") is True

    def test_three_days_later(self):
        # day 3: 3 % 3 == 0
        assert is_repeat_occurrence(self.ITEM, "2026-03-04") is True

    def test_six_days_later(self):
        assert is_repeat_occurrence(self.ITEM, "2026-03-07") is True

    def test_one_day_later_is_not_occurrence(self):
        # day 1: 1 % 3 != 0
        assert is_repeat_occurrence(self.ITEM, "2026-03-02") is False

    def test_before_start_is_false(self):
        assert is_repeat_occurrence(self.ITEM, "2026-02-28") is False
