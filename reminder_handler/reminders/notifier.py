# reminders/notifier.py
# ============================================================
# Telegram 通知層 — 訊息格式化 + 發送
#
# 職責：
#   1. 取得 owner chat_id（SSM Parameter Store）
#   2. 自動分割超長訊息（Telegram 4096 上限）
#   3. 發送 Markdown 訊息
#   4. 共用格式化 helper functions
# ============================================================

import logging
from decimal import Decimal

from bot_telegram import send_message   # shared layer
from bot_config import get_owner_id    # shared layer

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────

MAX_MSG_LEN = 4096
DIV = "─" * 22
WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]
PRIO_ICON = {"high": "🔴", "medium": "🟡", "low": "🟢"}

_cached_chat_id = None


# ================================================================
#  Chat ID
# ================================================================

def get_owner_chat_id():
    """取得 owner chat_id（與 owner_id 相同，快取）。"""
    global _cached_chat_id
    if _cached_chat_id is None:
        _cached_chat_id = get_owner_id()
    return _cached_chat_id


# ================================================================
#  Message Sending
# ================================================================

def _split_message(text, limit=MAX_MSG_LEN):
    """自動分割超過 limit 的訊息，在換行處切割。"""
    if len(text) <= limit:
        return [text]

    chunks, remaining = [], text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break

        pos = -1
        for sep in ["\n\n", "\n", " "]:
            p = remaining.rfind(sep, 0, limit)
            if p > limit // 4:
                pos = p
                break
        if pos < 0:
            pos = limit

        chunks.append(remaining[:pos].rstrip())
        remaining = remaining[pos:].lstrip("\n")

    return chunks


def send(text):
    """發送訊息至 owner，自動分割超長訊息。"""
    chat_id = get_owner_chat_id()
    for chunk in _split_message(text):
        try:
            send_message(chat_id, chunk, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")


# ================================================================
#  Formatting Helpers
# ================================================================

def fmt_float(val):
    """Decimal / str → float。"""
    if isinstance(val, Decimal):
        return float(val)
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def fmt_int(val):
    """Decimal / str → int。"""
    if isinstance(val, Decimal):
        return int(val)
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def fmt_amount(val):
    """格式化金額：$1,500。"""
    return f"${fmt_float(val):,.0f}"


def fmt_bar(pct, width=10):
    """進度條：█████░░░░░ 50%。"""
    filled = round(pct / 100 * width)
    return f"{'█' * filled}{'░' * (width - filled)} {pct}%"


def day_diff(date_str, ref_date):
    """date_str 與 ref_date 的天數差。正 = 未來，負 = 逾期。"""
    from datetime import datetime
    try:
        return (datetime.strptime(date_str, "%Y-%m-%d").date() - ref_date).days
    except (ValueError, TypeError):
        return 0


def day_label(d):
    """天數差 → 人類可讀標籤。"""
    if d < 0:
        return f"逾期 {abs(d)} 天"
    if d == 0:
        return "今天"
    if d == 1:
        return "明天"
    if d == 2:
        return "後天"
    return f"{d} 天後"