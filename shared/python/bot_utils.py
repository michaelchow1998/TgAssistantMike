# shared/python/bot_utils.py
# ============================================================
# 工具函數：日期解析、格式化、驗證、ULID、進度條、貨幣
# ============================================================

import re
import logging
from calendar import monthrange
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation

import pytz
import ulid as ulid_lib

from bot_constants import (
    DEFAULT_TIMEZONE,
    DEFAULT_CURRENCY,
    SHORT_ID_PAD_WIDTH,
    PROGRESS_BAR_WIDTH,
    PROGRESS_BAR_FILLED,
    PROGRESS_BAR_EMPTY,
    NO_DUE_DATE_SENTINEL,
)

logger = logging.getLogger(__name__)

WEEKDAY_NAMES = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]

_tz = None


def _get_tz():
    global _tz
    if _tz is None:
        _tz = pytz.timezone(DEFAULT_TIMEZONE)
    return _tz


# ===== Date / Time Helpers =====

def get_now():
    """Current datetime in HKT."""
    return datetime.now(_get_tz())


def get_today():
    """Today's date string YYYY-MM-DD in HKT."""
    return get_now().strftime("%Y-%m-%d")


def get_today_date():
    """Today as a date object in HKT."""
    return get_now().date()


def get_weekday_name(date_str):
    """Chinese weekday name from YYYY-MM-DD string."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return WEEKDAY_NAMES[dt.weekday()]


# ===== ID Generation =====

def generate_ulid():
    """Generate a new ULID string."""
    return str(ulid_lib.ULID())


def format_short_id(short_id):
    """Zero-pad a short_id for GSI3SK storage."""
    return str(int(short_id)).zfill(SHORT_ID_PAD_WIDTH)


# ===== Date Parsing =====

def parse_date(text):
    """
    Parse a variety of date input formats.
    Returns YYYY-MM-DD string, or None if unparseable.
    """
    text = text.strip()
    today = get_today_date()

    # --- Chinese shortcuts ---
    shortcuts = {
        "今天": today,
        "明天": today + timedelta(days=1),
        "後天": today + timedelta(days=2),
        "大後天": today + timedelta(days=3),
    }
    if text in shortcuts:
        return shortcuts[text].strftime("%Y-%m-%d")

    # --- 下週X / 下周X ---
    weekday_map = {}
    for i, (a, b) in enumerate([
        ("下週一", "下周一"), ("下週二", "下周二"), ("下週三", "下周三"),
        ("下週四", "下周四"), ("下週五", "下周五"), ("下週六", "下周六"),
        ("下週日", "下周日"),
    ]):
        weekday_map[a] = i
        weekday_map[b] = i

    if text in weekday_map:
        target_wd = weekday_map[text]
        current_wd = today.weekday()  # 0=Mon
        # Jump to next Monday, then add target weekday offset
        days_to_next_monday = (7 - current_wd) % 7 or 7
        result = today + timedelta(days=days_to_next_monday + target_wd)
        return result.strftime("%Y-%m-%d")

    # --- 下個月N號 ---
    m = re.match(r"下個月(\d{1,2})號", text)
    if m:
        day = int(m.group(1))
        if 1 <= day <= 31:
            year, month = today.year, today.month + 1
            if month > 12:
                month, year = 1, year + 1
            day = min(day, monthrange(year, month)[1])
            return date(year, month, day).strftime("%Y-%m-%d")
        return None

    # --- YYYY-MM-DD  or  YYYY/MM/DD ---
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})$", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime("%Y-%m-%d")
        except ValueError:
            return None

    # --- MM-DD / MM/DD / M/D ---
    m = re.match(r"(\d{1,2})[-/](\d{1,2})$", text)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        try:
            d = date(today.year, month, day)
            if d < today:
                d = date(today.year + 1, month, day)
            return d.strftime("%Y-%m-%d")
        except ValueError:
            return None

    return None


def is_past_date(date_str):
    """True if date_str is strictly before today."""
    return date_str < get_today()


def parse_time(text):
    """Parse HH:MM time. Returns HH:MM string or None."""
    text = text.strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", text)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if 0 <= h <= 23 and 0 <= mi <= 59:
        return f"{h:02d}:{mi:02d}"
    return None


# ===== Numeric Parsing =====

def parse_amount(text):
    """Parse a money amount. Returns Decimal or None."""
    text = text.strip().replace(",", "")
    try:
        amount = Decimal(text)
        if amount <= 0 or amount > Decimal("9999999.99"):
            return None
        if amount.as_tuple().exponent < -2:
            return None
        return amount
    except (InvalidOperation, ValueError):
        return None


def parse_percentage(text):
    """Parse 0-100 integer. Returns int or None."""
    text = text.strip().rstrip("%")
    try:
        v = int(text)
        return v if 0 <= v <= 100 else None
    except ValueError:
        return None


def parse_short_id(text):
    """Parse a positive integer short ID. Returns int or None."""
    text = text.strip()
    try:
        v = int(text)
        return v if v > 0 else None
    except ValueError:
        return None


def parse_day_of_month(text):
    """Parse 1-31. Returns int or None."""
    text = text.strip()
    try:
        v = int(text)
        return v if 1 <= v <= 31 else None
    except ValueError:
        return None


# ===== Validation =====

def validate_text_length(text, min_len=1, max_len=100):
    """Returns (is_valid, error_message_or_None)."""
    if not text or len(text.strip()) < min_len:
        return False, f"輸入不可為空，請至少輸入 {min_len} 個字元。"
    if len(text.strip()) > max_len:
        return False, f"輸入過長，最多 {max_len} 個字元。"
    return True, None


# ===== Display Formatters =====

def format_progress_bar(progress):
    """█████████░░░░░░░░░░░ 45%"""
    filled = round(progress / (100 / PROGRESS_BAR_WIDTH))
    empty = PROGRESS_BAR_WIDTH - filled
    return f"{PROGRESS_BAR_FILLED * filled}{PROGRESS_BAR_EMPTY * empty} {progress}%"


def format_currency(amount, currency=DEFAULT_CURRENCY):
    """$5,000.00 HKD"""
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    return f"${amount:,.2f} {currency}"


def format_date_short(date_str):
    """MM/DD or '無截止日'."""
    if not date_str or date_str == NO_DUE_DATE_SENTINEL:
        return "無截止日"
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").strftime("%m/%d")
    except ValueError:
        return date_str


def format_date_full(date_str):
    """YYYY-MM-DD (週X) or '未設定'."""
    if not date_str:
        return "未設定"
    try:
        wd = get_weekday_name(date_str)
        return f"{date_str} ({wd})"
    except ValueError:
        return date_str


def days_until(date_str):
    """Days from today to date_str. Negative = past."""
    today_dt = datetime.strptime(get_today(), "%Y-%m-%d")
    target_dt = datetime.strptime(date_str, "%Y-%m-%d")
    return (target_dt - today_dt).days


def days_until_display(date_str):
    """Human-readable relative day string."""
    d = days_until(date_str)
    if d < 0:
        return f"逾期 {abs(d)} 天"
    if d == 0:
        return "今天"
    if d == 1:
        return "明天"
    if d == 2:
        return "後天"
    return f"剩 {d} 天"


def escape_markdown(text):
    """Escape Telegram Markdown V1 special chars in user-supplied text."""
    if not text:
        return ""
    for ch in ("_", "*", "`", "["):
        text = text.replace(ch, f"\\{ch}")
    return text