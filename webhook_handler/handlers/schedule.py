# webhook_handler/handlers/schedule.py
# ============================================================
# 行程管理 — /add_schedule, /today, /week, /cancel_schedule
# ============================================================

import json
import logging
from datetime import timedelta

from boto3.dynamodb.conditions import Key, Attr

from bot_constants import (
    ENTITY_SCH,
    SCH_STATUS_ACTIVE,
    SCH_STATUS_CANCELLED,
    SCH_CATEGORIES,
    CONV_MODULE_SCHEDULE,
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
)

logger = logging.getLogger(__name__)


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
    elif step == "time":
        _step_time(user_id, chat_id, text, data)
    elif step == "category":
        send_message(chat_id, "請點選上方按鈕選擇分類。")
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
    if callback_data == "sch_skip_time":
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
    update_conversation(user_id, "date", data)
    send_message(
        chat_id,
        "📆 請輸入日期：\n\n"
        "支援格式：\n"
        "• `今天`、`明天`、`後天`\n"
        "• `下週一` ~ `下週日`\n"
        "• `下個月15號`\n"
        "• `2026-03-15` 或 `03/15`",
    )


def _step_date(user_id, chat_id, text, data):
    date_str = parse_date(text)
    if date_str is None:
        send_message(chat_id, "❌ 無法辨識日期格式，請重新輸入。")
        return
    if is_past_date(date_str):
        send_message(chat_id, "❌ 不能選擇過去的日期，請重新輸入。")
        return

    data["date"] = date_str
    update_conversation(user_id, "time", data)
    send_message(
        chat_id,
        "⏰ 請輸入時間（格式 `HH:MM`，如 `14:30`）：",
        reply_markup=build_skip_keyboard("sch_skip_time"),
    )


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

    text = (
        "📋 *確認新增行程*\n\n"
        f"📌 標題：{escape_markdown(data['title'])}\n"
        f"📆 日期：{format_date_full(data['date'])}\n"
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
        "created_at": now.isoformat(),
        # GSI keys
        "GSI1PK": f"USER#{owner_id}#SCH",
        "GSI1SK": f"{data['date']}#{sort_time}#{new_ulid}",
        "GSI2PK": f"USER#{owner_id}#SCH#{category}",
        "GSI2SK": f"{data['date']}#{new_ulid}",
        "GSI3PK": ENTITY_SCH,
        "GSI3SK": format_short_id(short_id),
    }

    put_item(item)
    delete_conversation(user_id)

    send_message(
        chat_id,
        f"✅ 行程已新增！\n\n"
        f"📌 {escape_markdown(data['title'])}\n"
        f"📆 {format_date_full(data['date'])}"
        f"{' ⏰ ' + time_str if time_str else ''}\n"
        f"🔖 ID: `{short_id}`",
    )

    logger.info(json.dumps({
        "event_type": "schedule_created",
        "short_id": short_id,
        "date": data["date"],
    }))


# ================================================================
#  /today — 今日行程
# ================================================================

def handle_today(user_id, chat_id):
    owner_id = get_owner_id()
    today = get_today()

    items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#SCH",
        sk_condition=Key("GSI1SK").begins_with(f"{today}#"),
        filter_expr=Attr("status").eq(SCH_STATUS_ACTIVE),
    )

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

        lines.append(
            f"{emoji} *{escape_markdown(item.get('title', ''))}*\n"
            f"  {time_display}  |  🔖 `{item.get('short_id', '')}`"
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

    items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#SCH",
        sk_condition=Key("GSI1SK").between(f"{today}#", f"{end_str}#~"),
        filter_expr=Attr("status").eq(SCH_STATUS_ACTIVE),
    )

    if not items:
        send_message(
            chat_id,
            f"📅 *未來 7 天行程*（{today} ~ {end_str}）\n\n"
            "沒有行程 🎉",
        )
        return

    # Group by date
    by_date = {}
    for item in items:
        d = item.get("date", "")
        by_date.setdefault(d, []).append(item)

    total = len(items)
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

            lines.append(
                f"  {emoji} {escape_markdown(item.get('title', ''))}"
                f"  \\[{time_display}\\]"
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