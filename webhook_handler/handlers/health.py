# webhook_handler/handlers/health.py
# ============================================================
# 健康管理 — /set_health, /add_meal, /health
# ============================================================

import re
import logging
from calendar import monthrange, isleap
from datetime import datetime, timedelta
from decimal import Decimal

from boto3.dynamodb.conditions import Key

from bot_constants import (
    ENTITY_HEALTH,
    CONV_MODULE_HEALTH,
    CONV_MODULE_SET_HEALTH,
    HEALTH_MEAL_DISPLAY,
)
from bot_config import get_owner_id
from bot_telegram import (
    send_message,
    edit_message_text,
    build_inline_keyboard,
    build_confirm_keyboard,
)
from bot_db import (
    get_item,
    put_item,
    query_gsi1,
    set_conversation,
    update_conversation,
    delete_conversation,
)
from bot_utils import (
    get_now,
    get_today,
    get_weekday_name,
)

logger = logging.getLogger(__name__)


# ================================================================
#  Command entry points
# ================================================================

def handle_set_health(user_id, chat_id):
    owner_id = get_owner_id()
    settings = _get_settings(owner_id)

    if settings:
        tdee = int(settings["tdee"])
        deficit = int(settings["deficit"])
        daily_goal = tdee - deficit
        preamble = (
            f"📋 *目前設定*\n"
            f"TDEE：{tdee:,} kcal  赤字：{deficit:,} kcal  目標：{daily_goal:,} kcal\n\n"
        )
    else:
        preamble = ""

    set_conversation(user_id, CONV_MODULE_SET_HEALTH, "tdee", {})
    send_message(chat_id, f"{preamble}🔢 請輸入你的每日 TDEE（整數，例如 2200）：")


def handle_add_meal(user_id, chat_id):
    set_conversation(user_id, CONV_MODULE_HEALTH, "meal_type", {})
    _ask_meal_type(chat_id)


def handle_health(user_id, chat_id, args=""):
    owner_id = get_owner_id()
    args = (args or "").strip()

    if not args:
        _render_today_summary(chat_id, owner_id, get_today())
        return

    if args == "week":
        monday, today_end = _get_week_range(get_today())
        _render_weekly_report(chat_id, owner_id, monday, today_end)
        return

    m = re.match(r"^(\d{4})-(\d{2})$", args)
    if m and 1 <= int(m.group(2)) <= 12:
        _render_monthly_report(chat_id, owner_id, args)
        return

    m = re.match(r"^(\d{4})$", args)
    if m and 2000 <= int(m.group(1)) <= 2099:
        _render_yearly_report(chat_id, owner_id, args)
        return

    send_message(
        chat_id,
        "❌ 格式錯誤。\n\n用法：\n"
        "• `/health` — 今日飲食記錄\n"
        "• `/health week` — 本週記錄\n"
        "• `/health 2026-03` — 月報\n"
        "• `/health 2026` — 年報",
    )


# ================================================================
#  Conversation: text input steps
# ================================================================

def handle_step(user_id, chat_id, text, step, data):
    owner_id = get_owner_id()

    # ── set_health flow ──────────────────────────────────────────
    if step == "tdee":
        val = _parse_positive_int(text)
        if val is None:
            send_message(chat_id, "❌ 請輸入有效的正整數（例如 2200）：")
            return
        data["tdee"] = val
        update_conversation(user_id, "deficit", data)
        send_message(chat_id, "🔢 請輸入每日目標赤字（整數，例如 500；無赤字請輸入 0）：")

    elif step == "deficit":
        val = _parse_non_negative_int(text)
        if val is None:
            send_message(chat_id, "❌ 請輸入有效的整數（例如 500）：")
            return
        data["deficit"] = val
        update_conversation(user_id, "confirm", data)
        _ask_confirm_settings(chat_id, data["tdee"], data["deficit"])

    # ── add_meal flow ────────────────────────────────────────────
    elif step == "calories":
        cal = _parse_calories(text)
        if cal is None:
            send_message(chat_id, "❌ 請輸入有效的卡路里數值（1–9999 的整數）：")
            return
        meal_type = data.get("meal_type")
        if not meal_type:
            delete_conversation(user_id)
            send_message(chat_id, "❌ 發生錯誤，請重新輸入 /add\\_meal。")
            return
        date_str = data.get("date", get_today())
        _save_meal(owner_id, date_str, meal_type, cal)
        delete_conversation(user_id)
        info = HEALTH_MEAL_DISPLAY[meal_type]
        send_message(chat_id, f"✅ 已記錄 {info['emoji']} {info['label']}：{cal:,} kcal")
        _render_today_summary(chat_id, owner_id, date_str)

    else:
        send_message(chat_id, "🚧 未知步驟，請輸入 /cancel 取消。")


# ================================================================
#  Conversation: button callbacks
# ================================================================

def handle_callback(user_id, chat_id, message_id, callback_data, step, data):
    owner_id = get_owner_id()

    # ── meal type selection ──────────────────────────────────────
    if callback_data in ("meal_breakfast", "meal_lunch", "meal_dinner", "meal_other"):
        meal_type = callback_data[len("meal_"):]  # "breakfast" / "lunch" / "dinner" / "other"
        data["meal_type"] = meal_type
        data["date"] = get_today()
        update_conversation(user_id, "calories", data)
        info = HEALTH_MEAL_DISPLAY[meal_type]
        edit_message_text(
            chat_id, message_id,
            f"已選擇 {info['emoji']} {info['label']}\n\n🔢 請輸入卡路里數值（1–9999）：",
        )

    # ── set_health confirm / cancel ──────────────────────────────
    elif callback_data == "sethealth_confirm":
        tdee = data.get("tdee")
        deficit = data.get("deficit")
        _save_settings(owner_id, tdee, deficit)
        delete_conversation(user_id)
        daily_goal = tdee - deficit
        edit_message_text(
            chat_id, message_id,
            f"✅ *健康設定已儲存*\n"
            f"TDEE：{tdee:,} kcal  赤字：{deficit:,} kcal\n"
            f"每日目標：{daily_goal:,} kcal",
        )

    elif callback_data == "sethealth_cancel":
        delete_conversation(user_id)
        edit_message_text(chat_id, message_id, "❌ 已取消健康設定。")

    else:
        logger.warning(f"Unknown health callback: {callback_data}")


# ================================================================
#  Private: DB helpers
# ================================================================

def _get_settings(owner_id):
    return get_item(f"USER#{owner_id}", "HEALTH_SETTINGS#active")


def _get_meals_for_date(owner_id, date_str):
    return query_gsi1(
        gsi1pk=f"USER#{owner_id}#HEALTH",
        sk_condition=Key("GSI1SK").begins_with(date_str),
    )


def _get_meals_for_month(owner_id, month_prefix):
    return query_gsi1(
        gsi1pk=f"USER#{owner_id}#HEALTH",
        sk_condition=Key("GSI1SK").begins_with(month_prefix),
    )


def _get_meals_for_week(owner_id, monday_str, today_str):
    """Fetch all meal records between monday_str and today_str (inclusive)."""
    return query_gsi1(
        gsi1pk=f"USER#{owner_id}#HEALTH",
        sk_condition=Key("GSI1SK").between(monday_str, today_str + "#~"),
    )


def _get_week_range(today_str):
    """Return (monday_str, today_str) for the week containing today_str."""
    dt = datetime.strptime(today_str, "%Y-%m-%d")
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%Y-%m-%d"), today_str


def _save_meal(owner_id, date_str, meal_type, calories):
    put_item({
        "PK": f"USER#{owner_id}",
        "SK": f"HEALTH#{date_str}#{meal_type}",
        "entity_type": ENTITY_HEALTH,
        "date": date_str,
        "meal_type": meal_type,
        "calories": Decimal(str(calories)),
        "updated_at": get_now().isoformat(),
        "GSI1PK": f"USER#{owner_id}#HEALTH",
        "GSI1SK": f"{date_str}#{meal_type}",
    })


def _save_settings(owner_id, tdee, deficit):
    put_item({
        "PK": f"USER#{owner_id}",
        "SK": "HEALTH_SETTINGS#active",
        "tdee": Decimal(str(tdee)),
        "deficit": Decimal(str(deficit)),
        "updated_at": get_now().isoformat(),
    })


# ================================================================
#  Private: Telegram UI builders
# ================================================================

def _ask_meal_type(chat_id):
    kb = build_inline_keyboard([
        [
            {"text": "🌅 早餐", "callback_data": "meal_breakfast"},
            {"text": "☀️ 午餐", "callback_data": "meal_lunch"},
        ],
        [
            {"text": "🌙 晚餐", "callback_data": "meal_dinner"},
            {"text": "🍎 其他", "callback_data": "meal_other"},
        ],
    ])
    send_message(chat_id, "🍽 請選擇餐點類型：", reply_markup=kb)


def _ask_confirm_settings(chat_id, tdee, deficit):
    daily_goal = tdee - deficit
    kb = build_confirm_keyboard("sethealth_confirm", "sethealth_cancel")
    send_message(
        chat_id,
        f"📊 *健康設定確認*\n"
        f"──────────────────────\n"
        f"TDEE：{tdee:,} kcal\n"
        f"目標赤字：{deficit:,} kcal\n"
        f"每日目標攝取：{daily_goal:,} kcal\n"
        f"──────────────────────\n"
        f"確認儲存？",
        reply_markup=kb,
    )


# ================================================================
#  Private: Report renderers
# ================================================================

def _render_today_summary(chat_id, owner_id, date_str):
    weekday = get_weekday_name(date_str)
    meals = _get_meals_for_date(owner_id, date_str)
    meal_map = {m["meal_type"]: int(m["calories"]) for m in meals}

    lines = [
        "🥗 *今日飲食記錄*",
        f"📆 {date_str}（{weekday}）",
        "──────────────────────",
    ]

    actual_total = 0
    for meal_type in ("breakfast", "lunch", "dinner", "other"):
        info = HEALTH_MEAL_DISPLAY[meal_type]
        if meal_type in meal_map:
            cal = meal_map[meal_type]
            actual_total += cal
            lines.append(f"{info['emoji']} {info['label']}：{cal:,} kcal")
        else:
            lines.append(f"{info['emoji']} {info['label']}：（未記錄）")

    lines.append("──────────────────────")
    lines.append(f"總攝取：{actual_total:,} kcal")

    settings = _get_settings(owner_id)
    if settings:
        tdee = int(settings["tdee"])
        deficit = int(settings["deficit"])
        daily_goal = tdee - deficit
        effective, was_filled = _effective_daily_calories(meal_map, tdee)

        if was_filled:
            lines.append(f"⚠️ 缺少主食記錄，以 TDEE 計算：{effective:,} kcal")

        remaining = daily_goal - effective
        lines += [
            "",
            "📊 *目標進度*",
            f"TDEE：{tdee:,} kcal  目標赤字：{deficit:,} kcal",
            f"每日目標：{daily_goal:,} kcal",
            f"剩餘：{remaining:,} kcal ✅" if remaining >= 0
            else f"超出：{abs(remaining):,} kcal ⚠️",
        ]

    send_message(chat_id, "\n".join(lines))


def _render_monthly_report(chat_id, owner_id, month_str):
    meals = _get_meals_for_month(owner_id, month_str)
    settings = _get_settings(owner_id)
    daily_goal = None
    if settings:
        daily_goal = int(settings["tdee"]) - int(settings["deficit"])

    # Group by date → daily totals
    day_totals = {}
    for meal in meals:
        d = meal["date"]
        day_totals[d] = day_totals.get(d, 0) + int(meal["calories"])

    num_days = len(day_totals)
    total_intake = sum(day_totals.values())
    avg_intake = round(total_intake / num_days) if num_days > 0 else 0

    lines = [
        f"📊 *{month_str} 健康月報*",
        "──────────────────────",
        f"📅 有記錄天數：{num_days} 天",
        f"🔥 平均日攝取：{avg_intake:,} kcal",
    ]

    if daily_goal is not None:
        days_ok = sum(1 for cal in day_totals.values() if cal <= daily_goal)
        days_over = num_days - days_ok
        lines += [
            f"🎯 每日目標：{daily_goal:,} kcal",
            f"✅ 達標天數：{days_ok} 天 / ⚠️ 超標天數：{days_over} 天",
        ]

    year, month = int(month_str[:4]), int(month_str[5:7])
    days_in_month = monthrange(year, month)[1]

    lines.append("──────────────────────")
    lines.append(f"各月合計攝取：{total_intake:,} kcal")
    if daily_goal is not None:
        target_total = daily_goal * days_in_month
        lines.append(f"目標合計：{target_total:,} kcal")

    send_message(chat_id, "\n".join(lines))


def _render_weekly_report(chat_id, owner_id, monday_str, today_str):
    meals = _get_meals_for_week(owner_id, monday_str, today_str)
    settings = _get_settings(owner_id)
    tdee = int(settings["tdee"]) if settings else None
    daily_goal = (int(settings["tdee"]) - int(settings["deficit"])) if settings else None

    # Group by date → {meal_type: calories}
    day_meal_maps = {}
    for meal in meals:
        d = meal["date"]
        if d not in day_meal_maps:
            day_meal_maps[d] = {}
        day_meal_maps[d][meal["meal_type"]] = int(meal["calories"])

    # Build ordered list of days Mon → today
    monday_dt = datetime.strptime(monday_str, "%Y-%m-%d")
    today_dt = datetime.strptime(today_str, "%Y-%m-%d")
    days = []
    cur = monday_dt
    while cur <= today_dt:
        days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    _WD = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    lines = [
        "📊 *本週飲食記錄*",
        f"📆 {monday_str}（週一）~ {today_str}（{_WD[today_dt.weekday()]}）",
        "──────────────────────",
    ]

    counted_days = 0
    total_for_avg = 0
    fill_count = 0
    days_ok = 0
    days_over = 0

    for d in days:
        wd = _WD[datetime.strptime(d, "%Y-%m-%d").weekday()]
        meal_map = day_meal_maps.get(d)
        if not meal_map:
            lines.append(f"{wd} {d}：（無記錄）")
            continue
        effective, was_filled = _effective_daily_calories(meal_map, tdee)
        counted_days += 1
        total_for_avg += effective
        if was_filled:
            fill_count += 1
            lines.append(f"{wd} {d}：⚠️ 缺主食，以 TDEE 計 {effective:,} kcal")
        else:
            status = ""
            if daily_goal is not None:
                status = " ✅" if effective <= daily_goal else " ⚠️"
            lines.append(f"{wd} {d}：{effective:,} kcal{status}")
        if daily_goal is not None:
            if effective <= daily_goal:
                days_ok += 1
            else:
                days_over += 1

    lines.append("──────────────────────")
    avg = round(total_for_avg / counted_days) if counted_days > 0 else 0
    fill_note = f"（含 TDEE 填補：{fill_count} 天）" if fill_count > 0 else ""
    lines.append(f"平均日攝取：{avg:,} kcal{fill_note}")

    if daily_goal is not None:
        lines += [
            f"🎯 每日目標：{daily_goal:,} kcal",
            f"✅ 達標天數：{days_ok} 天 / ⚠️ 超標天數：{days_over} 天",
        ]

    send_message(chat_id, "\n".join(lines))


def _render_yearly_report(chat_id, owner_id, year_str):
    meals = query_gsi1(
        gsi1pk=f"USER#{owner_id}#HEALTH",
        sk_condition=Key("GSI1SK").begins_with(f"{year_str}-"),
    )
    settings = _get_settings(owner_id)
    tdee = int(settings["tdee"]) if settings else None
    daily_goal = (int(settings["tdee"]) - int(settings["deficit"])) if settings else None

    # Group by date → {meal_type: calories}
    day_meal_maps = {}
    for meal in meals:
        d = meal["date"]
        if d not in day_meal_maps:
            day_meal_maps[d] = {}
        day_meal_maps[d][meal["meal_type"]] = int(meal["calories"])

    num_days = 0
    total_intake = 0
    fill_count = 0
    days_ok = 0
    days_over = 0
    month_stats = {}  # "YYYY-MM" → {days, total, days_ok, days_over}

    for d, meal_map in day_meal_maps.items():
        effective, was_filled = _effective_daily_calories(meal_map, tdee)
        num_days += 1
        total_intake += effective
        if was_filled:
            fill_count += 1
        if daily_goal is not None:
            if effective <= daily_goal:
                days_ok += 1
            else:
                days_over += 1
        month_key = d[:7]
        if month_key not in month_stats:
            month_stats[month_key] = {"days": 0, "total": 0, "days_ok": 0, "days_over": 0}
        month_stats[month_key]["days"] += 1
        month_stats[month_key]["total"] += effective
        if daily_goal is not None:
            if effective <= daily_goal:
                month_stats[month_key]["days_ok"] += 1
            else:
                month_stats[month_key]["days_over"] += 1

    avg_intake = round(total_intake / num_days) if num_days > 0 else 0
    fill_note = f"（含 TDEE 填補：{fill_count} 天）" if fill_count > 0 else ""

    lines = [
        f"📊 *{year_str} 年健康年報*",
        "──────────────────────",
        f"📅 有記錄天數：{num_days} 天{fill_note}",
        f"🔥 平均日攝取：{avg_intake:,} kcal",
    ]

    if daily_goal is not None:
        lines += [
            f"🎯 每日目標：{daily_goal:,} kcal",
            f"✅ 達標天數：{days_ok} 天 / ⚠️ 超標天數：{days_over} 天",
        ]

    if month_stats:
        lines += ["──────────────────────", "*月份摘要*"]
        for month_key in sorted(month_stats.keys()):
            ms = month_stats[month_key]
            month_avg = round(ms["total"] / ms["days"]) if ms["days"] > 0 else 0
            month_label = f"{int(month_key[5:7]):02d}月"
            if daily_goal is not None:
                lines.append(
                    f"{month_label}：平均 {month_avg:,} kcal — ✅ {ms['days_ok']}天 ⚠️ {ms['days_over']}天"
                )
            else:
                lines.append(f"{month_label}：平均 {month_avg:,} kcal — {ms['days']}天有記錄")

    year_int = int(year_str)
    days_in_year = 366 if isleap(year_int) else 365
    lines.append("──────────────────────")
    lines.append(f"全年總攝取：{total_intake:,} kcal")
    if daily_goal is not None:
        target_total = daily_goal * days_in_year
        lines.append(f"目標合計：{target_total:,} kcal（{days_in_year}天 × {daily_goal:,}）")

    send_message(chat_id, "\n".join(lines))


# ================================================================
#  Private: Input parsers
# ================================================================

def _parse_calories(text):
    """Parse 1–9999 integer for calories."""
    try:
        val = int(text.strip())
        return val if 1 <= val <= 9999 else None
    except (ValueError, AttributeError):
        return None


def _parse_positive_int(text):
    """Parse a positive integer (> 0)."""
    try:
        val = int(text.strip())
        return val if val > 0 else None
    except (ValueError, AttributeError):
        return None


def _parse_non_negative_int(text):
    """Parse a non-negative integer (>= 0)."""
    try:
        val = int(text.strip())
        return val if val >= 0 else None
    except (ValueError, AttributeError):
        return None


def _effective_daily_calories(meal_map, tdee):
    """
    Returns (effective_calories: int, was_filled: bool).
    If tdee is set and any of breakfast/lunch/dinner is missing from meal_map,
    return tdee as a conservative estimate for that day.
    """
    if tdee is not None:
        main_meals = {"breakfast", "lunch", "dinner"}
        if not main_meals.issubset(meal_map.keys()):
            return tdee, True
    return sum(meal_map.values()), False
