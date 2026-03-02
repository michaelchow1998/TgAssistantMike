# webhook_handler/handlers/schedule.py
# ============================================================
# 行程管理 — /add_schedule, /today, /week, /cancel_schedule
# ============================================================

import json
import logging
from datetime import datetime, timedelta

from boto3.dynamodb.conditions import Key, Attr

from bot_constants import (
    ENTITY_SCH,
    SCH_STATUS_ACTIVE,
    SCH_STATUS_CANCELLED,
    SCH_CATEGORIES,
    CONV_MODULE_SCHEDULE,
    SCH_TYPE_SINGLE,
    SCH_TYPE_PERIOD,
    SCH_TYPE_REPEAT,
    SCH_REPEAT_DAILY,
    SCH_REPEAT_WEEKLY,
    SCH_REPEAT_MONTHLY,
    SCH_REPEAT_CUSTOM,
    SCH_REPEAT_WEEKDAY_NAMES,
)
from bot_config import get_owner_id
from bot_telegram import (
    send_message,
    build_inline_keyboard,
    build_skip_keyboard,
    build_confirm_keyboard,
)
from bot_db import (
    set_conversation,
    update_conversation,
    delete_conversation,
    get_next_short_id,
    put_item,
    query_gsi1,
    query_gsi3,
    update_item,
)
from bot_utils import (
    generate_ulid,
    format_short_id,
    parse_date,
    parse_time,
    parse_short_id,
    is_past_date,
    validate_text_length,
    get_now,
    get_today,
    get_today_date,
    format_date_full,
    get_weekday_name,
    escape_markdown,
    days_until_display,
    is_repeat_occurrence,
)

logger = logging.getLogger(__name__)

_DATE_FORMAT_HINT = (
    "支援格式：\n"
    "• `今天`、`明天`、`後天`\n"
    "• `下週一` ~ `下週日`\n"
    "• `下個月15號`\n"
    "• `2026-03-15` 或 `03/15`"
)


# ================================================================
#  Conversation — /add_schedule
# ================================================================

def handle_add_schedule(user_id, chat_id):
    """Start the add-schedule conversation."""
    set_conversation(user_id, CONV_MODULE_SCHEDULE, "title", {})
    send_message(chat_id, "📅 *新增行程*\n\n請輸入行程標題：")


# ----------------------------------------------------------------
#  Text input dispatcher
# ----------------------------------------------------------------

def handle_step(user_id, chat_id, text, step, data):
    """Route text input to the correct step handler."""
    if step == "title":
        _step_title(user_id, chat_id, text, data)
    elif step == "date":
        _step_date(user_id, chat_id, text, data)
    elif step == "start_date":
        _step_start_date(user_id, chat_id, text, data)
    elif step == "end_date":
        _step_end_date(user_id, chat_id, text, data)
    elif step == "repeat_interval":
        _step_repeat_interval(user_id, chat_id, text, data)
    elif step == "repeat_end_date":
        _step_repeat_end_date(user_id, chat_id, text, data)
    elif step == "time":
        _step_time(user_id, chat_id, text, data)
    elif step == "category":
        send_message(chat_id, "請點選上方按鈕選擇分類。")
    elif step == "type":
        send_message(chat_id, "請點選上方按鈕選擇行程類型。")
    elif step == "repeat_type":
        send_message(chat_id, "請點選上方按鈕選擇重複模式。")
    elif step == "repeat_days":
        send_message(chat_id, "請點選按鈕勾選星期，完成後點「✔️ 完成」。")
    elif step == "notes":
        _step_notes(user_id, chat_id, text, data)
    elif step == "confirm":
        send_message(chat_id, "請點選上方按鈕確認或取消。")
    else:
        logger.warning(f"Unknown schedule step: {step}")
        send_message(chat_id, "⚠️ 未知的步驟，請輸入 /cancel 重新開始。")


# ----------------------------------------------------------------
#  Callback dispatcher
# ----------------------------------------------------------------

def handle_callback(user_id, chat_id, message_id, callback_data, step, data):
    """Route callback query to the correct handler."""

    # ── Schedule type selection ──
    if callback_data in ("sch_type_single", "sch_type_period", "sch_type_repeat"):
        if step != "type":
            return
        stype_map = {
            "sch_type_single": SCH_TYPE_SINGLE,
            "sch_type_period": SCH_TYPE_PERIOD,
            "sch_type_repeat": SCH_TYPE_REPEAT,
        }
        data["schedule_type"] = stype_map[callback_data]
        if callback_data == "sch_type_single":
            update_conversation(user_id, "date", data)
            _ask_date(chat_id)
        else:
            update_conversation(user_id, "start_date", data)
            _ask_start_date(chat_id)

    # ── Repeat pattern selection ──
    elif callback_data.startswith("sch_repeat_type_"):
        if step != "repeat_type":
            return
        rtype_map = {
            "sch_repeat_type_daily":   SCH_REPEAT_DAILY,
            "sch_repeat_type_weekly":  SCH_REPEAT_WEEKLY,
            "sch_repeat_type_monthly": SCH_REPEAT_MONTHLY,
            "sch_repeat_type_custom":  SCH_REPEAT_CUSTOM,
        }
        rtype = rtype_map.get(callback_data)
        if rtype is None:
            return
        data["repeat_type"] = rtype
        if rtype == SCH_REPEAT_WEEKLY:
            data["repeat_days"] = []
            update_conversation(user_id, "repeat_days", data)
            _ask_repeat_days(chat_id, [])
        elif rtype == SCH_REPEAT_CUSTOM:
            update_conversation(user_id, "repeat_interval", data)
            send_message(chat_id, "⏱ 請輸入間隔天數（正整數，如 `7` 表示每 7 天）：")
        else:  # daily, monthly
            update_conversation(user_id, "repeat_end_date", data)
            _ask_repeat_end_date(chat_id)

    # ── Weekday toggle ──
    elif callback_data.startswith("sch_weekday_") and callback_data != "sch_weekday_done":
        if step != "repeat_days":
            return
        try:
            wd_idx = int(callback_data[len("sch_weekday_"):])
            if 0 <= wd_idx <= 6:
                days = list(data.get("repeat_days") or [])
                if wd_idx in days:
                    days.remove(wd_idx)
                else:
                    days.append(wd_idx)
                data["repeat_days"] = days
                update_conversation(user_id, "repeat_days", data)
                _ask_repeat_days(chat_id, days)
        except ValueError:
            pass

    elif callback_data == "sch_weekday_done":
        if step != "repeat_days":
            return
        days = list(data.get("repeat_days") or [])
        if not days:
            send_message(chat_id, "❌ 請至少選擇一個星期。")
            _ask_repeat_days(chat_id, days)
            return
        update_conversation(user_id, "repeat_end_date", data)
        _ask_repeat_end_date(chat_id)

    elif callback_data == "sch_skip_repeat_end":
        if step != "repeat_end_date":
            return
        data["repeat_end_date"] = ""
        update_conversation(user_id, "time", data)
        _ask_time(chat_id)

    elif callback_data == "sch_skip_time":
        if step != "time":
            return
        data["time"] = ""
        update_conversation(user_id, "category", data)
        _ask_category(chat_id)

    elif callback_data.startswith("sch_cat_"):
        if step != "category":
            return
        category = callback_data[len("sch_cat_"):]
        if category not in SCH_CATEGORIES:
            send_message(chat_id, "❌ 無效的分類，請重新選擇。")
            return
        data["category"] = category
        update_conversation(user_id, "notes", data)
        _ask_notes(chat_id)

    elif callback_data == "sch_skip_notes":
        if step != "notes":
            return
        data["notes"] = ""
        update_conversation(user_id, "confirm", data)
        _ask_confirm(chat_id, data)

    elif callback_data == "sch_confirm":
        if step != "confirm":
            return
        _do_save(user_id, chat_id, data)

    elif callback_data == "sch_cancel":
        delete_conversation(user_id)
        send_message(chat_id, "✅ 已取消新增行程。")


# ================================================================
#  Step handlers
# ================================================================

def _step_title(user_id, chat_id, text, data):
    valid, err = validate_text_length(text, 1, 100)
    if not valid:
        send_message(chat_id, f"❌ {err}")
        return

    data["title"] = text.strip()
    update_conversation(user_id, "type", data)
    _ask_type(chat_id)


def _step_date(user_id, chat_id, text, data):
    """Single-occurrence date."""
    date_str = parse_date(text)
    if date_str is None:
        send_message(chat_id, "❌ 無法辨識日期格式，請重新輸入。")
        return
    if is_past_date(date_str):
        send_message(chat_id, "❌ 不能選擇過去的日期，請重新輸入。")
        return

    data["date"] = date_str
    update_conversation(user_id, "time", data)
    _ask_time(chat_id)


def _step_start_date(user_id, chat_id, text, data):
    """Period / repeat start date — stored in data['date']."""
    date_str = parse_date(text)
    if date_str is None:
        send_message(chat_id, "❌ 無法辨識日期格式，請重新輸入。")
        return
    if is_past_date(date_str):
        send_message(chat_id, "❌ 不能選擇過去的日期，請重新輸入。")
        return

    data["date"] = date_str
    schedule_type = data.get("schedule_type")
    if schedule_type == SCH_TYPE_PERIOD:
        update_conversation(user_id, "end_date", data)
        send_message(
            chat_id,
            f"📆 請輸入結束日期（必須在開始日期 {date_str} 之後）：\n\n{_DATE_FORMAT_HINT}",
        )
    else:  # repeat
        update_conversation(user_id, "repeat_type", data)
        _ask_repeat_type(chat_id)


def _step_end_date(user_id, chat_id, text, data):
    date_str = parse_date(text)
    if date_str is None:
        send_message(chat_id, "❌ 無法辨識日期格式，請重新輸入。")
        return
    start_date = data.get("date", "")
    if date_str < start_date:
        send_message(
            chat_id,
            f"❌ 結束日期必須在開始日期（{start_date}）之後，請重新輸入。",
        )
        return

    data["end_date"] = date_str
    update_conversation(user_id, "time", data)
    _ask_time(chat_id)


def _step_repeat_interval(user_id, chat_id, text, data):
    try:
        interval = int(text.strip())
        if interval < 1:
            raise ValueError
    except ValueError:
        send_message(chat_id, "❌ 請輸入一個正整數（如 `7` 表示每 7 天）。")
        return

    data["repeat_interval"] = interval
    update_conversation(user_id, "repeat_end_date", data)
    _ask_repeat_end_date(chat_id)


def _step_repeat_end_date(user_id, chat_id, text, data):
    date_str = parse_date(text)
    if date_str is None:
        send_message(
            chat_id,
            "❌ 無法辨識日期格式，請重新輸入，或點選「跳過」不設定結束日期。",
        )
        return
    start_date = data.get("date", "")
    if date_str < start_date:
        send_message(
            chat_id,
            f"❌ 結束日期必須在開始日期（{start_date}）之後，請重新輸入。",
        )
        return

    data["repeat_end_date"] = date_str
    update_conversation(user_id, "time", data)
    _ask_time(chat_id)


def _step_time(user_id, chat_id, text, data):
    time_str = parse_time(text)
    if time_str is None:
        send_message(
            chat_id,
            "❌ 時間格式不正確，請輸入 `HH:MM`（如 `09:30`），或點選跳過。",
        )
        return

    data["time"] = time_str
    update_conversation(user_id, "category", data)
    _ask_category(chat_id)


def _step_notes(user_id, chat_id, text, data):
    valid, err = validate_text_length(text, 1, 200)
    if not valid:
        send_message(chat_id, f"❌ {err}")
        return

    data["notes"] = text.strip()
    update_conversation(user_id, "confirm", data)
    _ask_confirm(chat_id, data)


# ================================================================
#  Prompt helpers
# ================================================================

def _ask_type(chat_id):
    rows = [[
        {"text": "📅 單次", "callback_data": "sch_type_single"},
        {"text": "📆 期間", "callback_data": "sch_type_period"},
        {"text": "🔁 重複", "callback_data": "sch_type_repeat"},
    ]]
    send_message(
        chat_id,
        "📋 請選擇行程類型：",
        reply_markup=build_inline_keyboard(rows),
    )


def _ask_date(chat_id):
    send_message(
        chat_id,
        f"📆 請輸入日期：\n\n{_DATE_FORMAT_HINT}",
    )


def _ask_start_date(chat_id):
    send_message(
        chat_id,
        f"📆 請輸入開始日期：\n\n{_DATE_FORMAT_HINT}",
    )


def _ask_repeat_type(chat_id):
    rows = [
        [
            {"text": "🔁 每天",     "callback_data": "sch_repeat_type_daily"},
            {"text": "📅 每週",     "callback_data": "sch_repeat_type_weekly"},
        ],
        [
            {"text": "🗓 每月",     "callback_data": "sch_repeat_type_monthly"},
            {"text": "⏱ 自訂間隔", "callback_data": "sch_repeat_type_custom"},
        ],
    ]
    send_message(
        chat_id,
        "🔁 請選擇重複模式：",
        reply_markup=build_inline_keyboard(rows),
    )


def _ask_repeat_days(chat_id, selected_days):
    rows = []
    row = []
    for i, name in enumerate(SCH_REPEAT_WEEKDAY_NAMES):
        checked = "✅ " if i in selected_days else ""
        row.append({
            "text": f"{checked}{name}",
            "callback_data": f"sch_weekday_{i}",
        })
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": "✔️ 完成", "callback_data": "sch_weekday_done"}])
    send_message(
        chat_id,
        "📅 請選擇每週重複的星期（可多選）：",
        reply_markup=build_inline_keyboard(rows),
    )


def _ask_repeat_end_date(chat_id):
    send_message(
        chat_id,
        f"📆 請輸入重複結束日期（選填）：\n\n{_DATE_FORMAT_HINT}\n\n或點選「跳過」表示不限制結束日期。",
        reply_markup=build_skip_keyboard("sch_skip_repeat_end"),
    )


def _ask_time(chat_id):
    send_message(
        chat_id,
        "⏰ 請輸入時間（格式 `HH:MM`，如 `14:30`）：",
        reply_markup=build_skip_keyboard("sch_skip_time"),
    )


def _ask_category(chat_id):
    rows = []
    row = []
    for key, info in SCH_CATEGORIES.items():
        row.append({
            "text": f"{info['emoji']} {info['display']}",
            "callback_data": f"sch_cat_{key}",
        })
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    send_message(
        chat_id,
        "📁 請選擇分類：",
        reply_markup=build_inline_keyboard(rows),
    )


def _ask_notes(chat_id):
    send_message(
        chat_id,
        "📝 請輸入備註（選填）：",
        reply_markup=build_skip_keyboard("sch_skip_notes"),
    )


def _ask_confirm(chat_id, data):
    cat_info = SCH_CATEGORIES.get(data.get("category", "other"), {})
    cat_display = f"{cat_info.get('emoji', '')} {cat_info.get('display', '')}"
    time_display = data.get("time") or "未設定"
    notes_display = data.get("notes") or "無"
    schedule_type = data.get("schedule_type", SCH_TYPE_SINGLE)

    if schedule_type == SCH_TYPE_SINGLE:
        date_display = format_date_full(data["date"])
        type_display = "📅 單次"
    elif schedule_type == SCH_TYPE_PERIOD:
        date_display = f"{data['date']} ~ {data.get('end_date', '?')}"
        type_display = "📆 期間"
    else:
        date_display = f"{data['date']} 起"
        type_display = _format_repeat_label(data)

    text = (
        "📋 *確認新增行程*\n\n"
        f"📌 標題：{escape_markdown(data['title'])}\n"
        f"類型：{type_display}\n"
        f"📆 日期：{date_display}\n"
        f"⏰ 時間：{time_display}\n"
        f"📁 分類：{cat_display}\n"
        f"📝 備註：{escape_markdown(notes_display)}\n\n"
        "確認新增？"
    )
    send_message(
        chat_id,
        text,
        reply_markup=build_confirm_keyboard("sch_confirm", "sch_cancel"),
    )


# ================================================================
#  Display helpers
# ================================================================

def _format_repeat_label(data):
    """Human-readable repeat pattern label."""
    rtype = data.get("repeat_type", "")
    if rtype == SCH_REPEAT_DAILY:
        base = "🔁 每天"
    elif rtype == SCH_REPEAT_WEEKLY:
        days = sorted(data.get("repeat_days") or [])
        day_names = "".join(SCH_REPEAT_WEEKDAY_NAMES[i] for i in days if 0 <= i < 7)
        base = f"🔁 每週{day_names}"
    elif rtype == SCH_REPEAT_MONTHLY:
        try:
            day_num = datetime.strptime(data["date"], "%Y-%m-%d").day
            base = f"🔁 每月{day_num}號"
        except (KeyError, ValueError):
            base = "🔁 每月"
    elif rtype == SCH_REPEAT_CUSTOM:
        interval = data.get("repeat_interval", 1)
        base = f"🔁 每{interval}天"
    else:
        base = "🔁 重複"

    end_date = data.get("repeat_end_date", "")
    return f"{base}（至 {end_date}）" if end_date else base


def _get_type_badge(item):
    """Inline badge string appended after time in schedule lists."""
    schedule_type = item.get("schedule_type", SCH_TYPE_SINGLE)
    if schedule_type == SCH_TYPE_PERIOD:
        return f"  📆{item.get('date', '')}~{item.get('end_date', '')}"
    if schedule_type == SCH_TYPE_REPEAT:
        rtype = item.get("repeat_type", "")
        if rtype == SCH_REPEAT_DAILY:
            return "  🔁每天"
        if rtype == SCH_REPEAT_WEEKLY:
            days = sorted(item.get("repeat_days") or [])
            names = "".join(SCH_REPEAT_WEEKDAY_NAMES[i] for i in days if 0 <= i < 7)
            return f"  🔁每週{names}"
        if rtype == SCH_REPEAT_MONTHLY:
            try:
                d = datetime.strptime(item["date"], "%Y-%m-%d").day
                return f"  🔁每月{d}號"
            except (KeyError, ValueError):
                return "  🔁每月"
        if rtype == SCH_REPEAT_CUSTOM:
            return f"  🔁每{item.get('repeat_interval', '?')}天"
        return "  🔁重複"
    return ""


# ================================================================
#  Save to DynamoDB
# ================================================================

def _do_save(user_id, chat_id, data):
    owner_id = get_owner_id()
    new_ulid = generate_ulid()
    short_id = get_next_short_id(ENTITY_SCH)
    now = get_now()

    time_str = data.get("time", "")
    sort_time = time_str if time_str else "00:00"
    category = data.get("category", "other")
    schedule_type = data.get("schedule_type", SCH_TYPE_SINGLE)

    item = {
        "PK": f"USER#{owner_id}",
        "SK": f"SCH#{new_ulid}",
        "entity_type": ENTITY_SCH,
        "short_id": short_id,
        "title": data["title"],
        "date": data["date"],
        "time": time_str,
        "category": category,
        "notes": data.get("notes", ""),
        "status": SCH_STATUS_ACTIVE,
        "schedule_type": schedule_type,
        "created_at": now.isoformat(),
        # GSI keys — GSI1SK always uses start_date
        "GSI1PK": f"USER#{owner_id}#SCH",
        "GSI1SK": f"{data['date']}#{sort_time}#{new_ulid}",
        "GSI2PK": f"USER#{owner_id}#SCH#{category}",
        "GSI2SK": f"{data['date']}#{new_ulid}",
        "GSI3PK": ENTITY_SCH,
        "GSI3SK": format_short_id(short_id),
    }

    if schedule_type == SCH_TYPE_PERIOD:
        item["end_date"] = data.get("end_date", "")
    elif schedule_type == SCH_TYPE_REPEAT:
        item["repeat_type"] = data.get("repeat_type", "")
        if data.get("repeat_days"):
            item["repeat_days"] = [int(d) for d in data["repeat_days"]]
        if data.get("repeat_interval"):
            item["repeat_interval"] = int(data["repeat_interval"])
        if data.get("repeat_end_date"):
            item["repeat_end_date"] = data["repeat_end_date"]

    put_item(item)
    delete_conversation(user_id)

    type_note = ""
    if schedule_type == SCH_TYPE_PERIOD:
        type_note = f"\n📆 期間至 {data.get('end_date', '')}"
    elif schedule_type == SCH_TYPE_REPEAT:
        type_note = f"\n{_format_repeat_label(data)}"

    send_message(
        chat_id,
        f"✅ 行程已新增！\n\n"
        f"📌 {escape_markdown(data['title'])}\n"
        f"📆 {format_date_full(data['date'])}"
        f"{' ⏰ ' + time_str if time_str else ''}"
        f"{type_note}\n"
        f"🔖 ID: `{short_id}`",
    )

    logger.info(json.dumps({
        "event_type": "schedule_created",
        "short_id": short_id,
        "date": data["date"],
        "schedule_type": schedule_type,
    }))


# ================================================================
#  Query helper — all effective schedules on a given date
# ================================================================

def _get_schedules_on(owner_id, date_str):
    """All active schedules effective on date_str (single + period + repeat)."""
    gsi1pk = f"USER#{owner_id}#SCH"
    active = Attr("status").eq(SCH_STATUS_ACTIVE)

    # 1. Items whose GSI1SK starts on date_str (any type starting today)
    same_day = query_gsi1(
        gsi1pk=gsi1pk,
        sk_condition=Key("GSI1SK").begins_with(f"{date_str}#"),
        filter_expr=active,
    )

    # 2. Period items that started before date_str but end on/after date_str
    earlier_period = query_gsi1(
        gsi1pk=gsi1pk,
        sk_condition=Key("GSI1SK").between("0000-01-01#", f"{date_str}#"),
        filter_expr=(
            active
            & Attr("schedule_type").eq(SCH_TYPE_PERIOD)
            & Attr("end_date").gte(date_str)
        ),
    )

    # 3. Repeat items that started before date_str — filter by occurrence
    repeat_candidates = query_gsi1(
        gsi1pk=gsi1pk,
        sk_condition=Key("GSI1SK").between("0000-01-01#", f"{date_str}#"),
        filter_expr=(
            active
            & Attr("schedule_type").eq(SCH_TYPE_REPEAT)
        ),
    )
    earlier_repeats = [r for r in repeat_candidates if is_repeat_occurrence(r, date_str)]

    # Merge — deduplicate by SK; apply occurrence check to repeat items in same_day
    seen = set()
    results = []
    for item in same_day:
        sk = item["SK"]
        if sk in seen:
            continue
        seen.add(sk)
        if (item.get("schedule_type") == SCH_TYPE_REPEAT
                and not is_repeat_occurrence(item, date_str)):
            continue
        results.append(item)

    for item in earlier_period + earlier_repeats:
        sk = item["SK"]
        if sk not in seen:
            seen.add(sk)
            results.append(item)

    return sorted(results, key=lambda x: x.get("GSI1SK", ""))


# ================================================================
#  /today — 今日行程
# ================================================================

def handle_today(user_id, chat_id):
    owner_id = get_owner_id()
    today = get_today()

    items = _get_schedules_on(owner_id, today)

    if not items:
        send_message(
            chat_id,
            f"📅 *{today}（{get_weekday_name(today)}）的行程*\n\n"
            "今天沒有行程 🎉",
        )
        return

    lines = [
        f"📅 *{today}（{get_weekday_name(today)}）的行程*\n"
        f"共 {len(items)} 筆\n"
    ]

    for item in items:
        time_str = item.get("time", "")
        time_display = f"⏰ {time_str}" if time_str else "🕐 全天"
        cat_info = SCH_CATEGORIES.get(item.get("category", "other"), {})
        emoji = cat_info.get("emoji", "📦")
        badge = _get_type_badge(item)

        lines.append(
            f"{emoji} *{escape_markdown(item.get('title', ''))}*\n"
            f"  {time_display}{badge}  |  🔖 `{item.get('short_id', '')}`"
        )
        if item.get("notes"):
            lines.append(f"  📝 {escape_markdown(item['notes'])}")

    send_message(chat_id, "\n".join(lines))


# ================================================================
#  /week — 未來 7 天行程
# ================================================================

def handle_week(user_id, chat_id):
    owner_id = get_owner_id()
    today = get_today()
    today_date = get_today_date()
    end_date = today_date + timedelta(days=6)
    end_str = end_date.strftime("%Y-%m-%d")

    by_date = {}
    for i in range(7):
        day = (today_date + timedelta(days=i)).strftime("%Y-%m-%d")
        day_items = _get_schedules_on(owner_id, day)
        if day_items:
            by_date[day] = day_items

    if not by_date:
        send_message(
            chat_id,
            f"📅 *未來 7 天行程*（{today} ~ {end_str}）\n\n"
            "沒有行程 🎉",
        )
        return

    total = sum(len(v) for v in by_date.values())
    lines = [
        f"📅 *未來 7 天行程*（{today} ~ {end_str}）\n"
        f"共 {total} 筆\n"
    ]

    for d in sorted(by_date.keys()):
        wd = get_weekday_name(d)
        rel = days_until_display(d)
        lines.append(f"\n📆 *{d}（{wd}）— {rel}*")

        for item in by_date[d]:
            time_str = item.get("time", "")
            time_display = time_str if time_str else "全天"
            cat_info = SCH_CATEGORIES.get(item.get("category", "other"), {})
            emoji = cat_info.get("emoji", "📦")
            badge = _get_type_badge(item)

            lines.append(
                f"  {emoji} {escape_markdown(item.get('title', ''))}"
                f"  \\[{time_display}\\]{badge}"
                f"  `{item.get('short_id', '')}`"
            )

    send_message(chat_id, "\n".join(lines))


# ================================================================
#  /cancel_schedule ID — 取消行程
# ================================================================

def handle_cancel_schedule(user_id, chat_id, args):
    sid = parse_short_id(args)
    if sid is None:
        send_message(
            chat_id,
            "❌ 請提供行程 ID，例如：`/cancel_schedule 3`",
        )
        return

    item = query_gsi3(ENTITY_SCH, sid)
    if item is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{sid}` 的行程。")
        return

    if item.get("status") == SCH_STATUS_CANCELLED:
        send_message(chat_id, f"⚠️ 行程 `{sid}` 已經是取消狀態。")
        return

    update_item(
        pk=item["PK"],
        sk=item["SK"],
        update_expr="SET #st = :s",
        expr_values={":s": SCH_STATUS_CANCELLED},
        expr_names={"#st": "status"},
    )

    send_message(
        chat_id,
        f"✅ 已取消行程：\n\n"
        f"📌 {escape_markdown(item.get('title', ''))}\n"
        f"📆 {format_date_full(item.get('date', ''))}\n"
        f"🔖 ID: `{sid}`",
    )

    logger.info(json.dumps({
        "event_type": "schedule_cancelled",
        "short_id": sid,
    }))
