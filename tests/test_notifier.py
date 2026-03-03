# tests/test_notifier.py
# ============================================================
# Unit tests for formatting helpers in reminders/notifier.py.
# All functions are pure (no I/O) so no mocking required.
# ============================================================

import pytest
from datetime import date
from decimal import Decimal

from reminders.notifier import (
    fmt_float,
    fmt_int,
    fmt_amount,
    fmt_bar,
    day_diff,
    day_label,
    _split_message,
    MAX_MSG_LEN,
)


# ================================================================
#  fmt_float
# ================================================================

class TestFmtFloat:
    def test_decimal_input(self):
        assert fmt_float(Decimal("1500.5")) == pytest.approx(1500.5)

    def test_string_input(self):
        assert fmt_float("100") == pytest.approx(100.0)

    def test_integer_input(self):
        assert fmt_float(42) == pytest.approx(42.0)

    def test_none_returns_zero(self):
        assert fmt_float(None) == pytest.approx(0.0)

    def test_invalid_string_returns_zero(self):
        assert fmt_float("abc") == pytest.approx(0.0)


# ================================================================
#  fmt_int
# ================================================================

class TestFmtInt:
    def test_decimal_input(self):
        assert fmt_int(Decimal("42")) == 42

    def test_string_input(self):
        assert fmt_int("99") == 99

    def test_integer_input(self):
        assert fmt_int(7) == 7

    def test_none_returns_zero(self):
        assert fmt_int(None) == 0

    def test_invalid_string_returns_zero(self):
        assert fmt_int("abc") == 0


# ================================================================
#  fmt_amount
# ================================================================

class TestFmtAmount:
    def test_whole_number(self):
        assert fmt_amount(Decimal("1500")) == "$1,500"

    def test_large_amount(self):
        assert fmt_amount(Decimal("9999999")) == "$9,999,999"

    def test_rounds_decimals(self):
        # ,.0f uses Python banker's rounding; 2000.5 → 2000
        assert fmt_amount("2000.50") == "$2,000"

    def test_small_amount(self):
        assert fmt_amount(Decimal("99")) == "$99"

    def test_zero(self):
        assert fmt_amount(0) == "$0"


# ================================================================
#  fmt_bar
# ================================================================

class TestFmtBar:
    def test_zero_percent(self):
        result = fmt_bar(0)
        assert result == "░░░░░░░░░░ 0%"

    def test_fifty_percent(self):
        result = fmt_bar(50)
        assert result == "█████░░░░░ 50%"

    def test_hundred_percent(self):
        result = fmt_bar(100)
        assert result == "██████████ 100%"

    def test_custom_width_zero(self):
        result = fmt_bar(0, width=4)
        assert result == "░░░░ 0%"

    def test_custom_width_full(self):
        result = fmt_bar(100, width=4)
        assert result == "████ 100%"

    def test_twenty_five_percent(self):
        # filled = round(0.25 * 10) = round(2.5) = 2 (banker's rounding) or 3
        # Python rounds 2.5 → 2 (banker's rounding)
        result = fmt_bar(25)
        assert "25%" in result

    def test_bar_length_matches_width(self):
        for width in [5, 10, 20]:
            result = fmt_bar(50, width=width)
            filled = result.count("█")
            empty = result.count("░")
            assert filled + empty == width


# ================================================================
#  day_diff
# ================================================================

class TestDayDiff:
    REF = date(2026, 3, 3)

    def test_future_date(self):
        assert day_diff("2026-03-10", self.REF) == 7

    def test_past_date(self):
        assert day_diff("2026-03-01", self.REF) == -2

    def test_same_date(self):
        assert day_diff("2026-03-03", self.REF) == 0

    def test_invalid_date_returns_zero(self):
        assert day_diff("not-a-date", self.REF) == 0


# ================================================================
#  day_label
# ================================================================

class TestDayLabel:
    def test_overdue(self):
        assert day_label(-5) == "逾期 5 天"

    def test_overdue_one_day(self):
        assert day_label(-1) == "逾期 1 天"

    def test_today(self):
        assert day_label(0) == "今天"

    def test_tomorrow(self):
        assert day_label(1) == "明天"

    def test_day_after_tomorrow(self):
        assert day_label(2) == "後天"

    def test_three_days(self):
        assert day_label(3) == "3 天後"

    def test_thirty_days(self):
        assert day_label(30) == "30 天後"


# ================================================================
#  _split_message
# ================================================================

class TestSplitMessage:
    def test_short_message_not_split(self):
        text = "short message"
        assert _split_message(text) == [text]

    def test_exactly_at_limit_not_split(self):
        text = "x" * MAX_MSG_LEN
        chunks = _split_message(text)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_one_over_limit_splits(self):
        text = "x" * (MAX_MSG_LEN + 1)
        chunks = _split_message(text)
        assert len(chunks) == 2
        assert len(chunks[0]) <= MAX_MSG_LEN

    def test_splits_at_double_newline(self):
        part1 = "a" * 3000 + "\n\n"
        part2 = "b" * 3000
        text = part1 + part2  # 6002 chars > 4096
        chunks = _split_message(text)
        assert len(chunks) == 2
        assert chunks[0] == "a" * 3000
        assert chunks[1] == "b" * 3000

    def test_splits_at_single_newline_when_no_paragraph(self):
        part1 = "a" * 3000 + "\n"
        part2 = "b" * 3000
        text = part1 + part2  # 6001 chars > 4096
        chunks = _split_message(text)
        assert len(chunks) == 2
        # First chunk ends before or at limit
        assert len(chunks[0]) <= MAX_MSG_LEN

    def test_hard_split_when_no_good_breakpoint(self):
        # No whitespace or newlines → forced hard split at limit
        text = "x" * 5000
        chunks = _split_message(text)
        assert chunks[0] == "x" * MAX_MSG_LEN
        assert chunks[1] == "x" * (5000 - MAX_MSG_LEN)

    def test_all_chunks_within_limit(self):
        text = ("word " * 1000)  # 5000 chars with spaces
        chunks = _split_message(text)
        for chunk in chunks:
            assert len(chunk) <= MAX_MSG_LEN

    def test_empty_string_returns_list_with_empty(self):
        chunks = _split_message("")
        assert chunks == [""]
