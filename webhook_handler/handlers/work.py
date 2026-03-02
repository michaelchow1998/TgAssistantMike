# webhook_handler/handlers/work.py
# ============================================================
# 工作進度 — /add_work, /work, /update_progress, /deadlines
# ============================================================

import json
import logging
from datetime import timedelta

from boto3.dynamodb.conditions import Key, Attr

from bot_constants import (
    ENTITY_WORK,
    WORK_STATUS_IN_PROGRESS,
    WORK_STATUS_COMPLETED,
    WORK_STATUS_ON_HOLD,
    WORK_CATEGORIES,
    NO_DUE_DATE_SENTINEL,
    CONV_MODULE_WORK,
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
    parse_short_id,
    parse_percentage,
    is_past_date,
    validate_text_length,
    get_now,
    get_today,
    get_today_date,
    format_date_full,
    format_date_short,
    format_progress_bar,
    days_until,
    days_until_display,
    escape_markdown,
)

logger = logging.getLogger(__name__)


# ================================================================
#  Conversation — /add_work
# ================================================================

def handle_add_work(user_id, chat_id):
    """Start the add-work conversation."""
    set_conversation(user_id, CONV_MODULE_WORK, "title", {})
    send_message(chat_id, "🔨 *新增工作*\n\n請輸入工作標題：")


# ----------------------------------------------------------------
#  Text input dispatcher
# ----------------------------------------------------------------

def handle_step(user_id, chat_id, text, step, data):
    """Route text input to the correct step handler."""
    if step == "title":
        _step_title(user_id, chat_id, text, data)
    elif step == "description":
        _step_description(user_id, chat_id, text, data)
    elif step == "deadline":
        _step_deadline(user_id, chat_id, text, data)
    elif step == "category":
        send_message(chat_id, "請點選上方按鈕選擇分類。")
    elif step == "confirm":
        send_message(chat_id, "請點選上方按鈕確認或取消。")
    else:
        logger.warning(f"Unknown work step: {step}")
        send_message(chat_id, "⚠️ 未知的步驟，請輸入 /cancel 重新開始。")


# ----------------------------------------------------------------
#  Callback dispatcher
# ----------------------------------------------------------------

def handle_callback(user_id, chat_id, message_id, callback_data, step, data):
    """Route callback query to the correct handler."""

    # --- Description: skip ---
    if callback_data == "work_skip_desc":
        if step != "description":
            return
        data["description"] = ""
        update_conversation(user_id, "deadline", data)
        _ask_deadline(chat_id)

    # --- Deadline: skip ---
    elif callback_data == "work_skip_deadline":
        if step != "deadline":
            return
        data["deadline"] = ""
        update_conversation(user_id, "category", data)
        _ask_category(chat_id)

    # --- Category ---
    elif callback_data.startswith("work_cat_"):
        if step != "category":
            return
        category = callback_data[len("work_cat_"):]
        if category not in WORK_CATEGORIES:
            send_message(chat_id, "❌ 無效的分類，請重新選擇。")
            return
        data["category"] = category
        update_conversation(user_id, "confirm", data)
        _ask_confirm(chat_id, data)

    # --- Confirm / Cancel ---
    elif callback_data == "work_confirm":
        if step != "confirm":
            return
        _do_save(user_id, chat_id, data)

    elif callback_data == "work_cancel":
        delete_conversation(user_id)
        send_message(chat_id, "✅ 已取消新增工作。")


# ================================================================
#  Step handlers
# ================================================================

def _step_title(user_id, chat_id, text, data):
    valid, err = validate_text_length(text, 1, 100)
    if not valid:
        send_message(chat_id, f"❌ {err}")
        return

    data["title"] = text.strip()
    update_conversation(user_id, "description", data)
    send_message(
        chat_id,
        "📝 請輸入工作描述（選填）：",
        reply_markup=build_skip_keyboard("work_skip_desc"),
    )


def _step_description(user_id, chat_id, text, data):
    valid, err = validate_text_length(text, 1, 500)
    if not valid:
        send_message(chat_id, f"❌ {err}")
        return

    data["description"] = text.strip()
    update_conversation(user_id, "deadline", data)
    _ask_deadline(chat_id)


def _step_deadline(user_id, chat_id, text, data):
    date_str = parse_date(text)
    if date_str is None:
        send_message(chat_id, "❌ 無法辨識日期格式，請重新輸入或點選跳過。")
        return
    if is_past_date(date_str):
        send_message(chat_id, "❌ 不能選擇過去的日期，請重新輸入。")
        return

    data["deadline"] = date_str
    update_conversation(user_id, "category", data)
    _ask_category(chat_id)


# ================================================================
#  Prompt helpers
# ================================================================

def _ask_deadline(chat_id):
    send_message(
        chat_id,
        "📆 請輸入截止日期：\n\n"
        "支援格式：\n"
        "• `今天`、`明天`、`後天`\n"
        "• `下週一` ~ `下週日`\n"
        "• `下個月15號`\n"
        "• `2026-03-15` 或 `03/15`",
        reply_markup=build_skip_keyboard("work_skip_deadline", "⏭ 無截止日"),
    )


def _ask_category(chat_id):
    rows = []
    row = []
    for key, info in WORK_CATEGORIES.items():
        row.append({
            "text": f"{info['emoji']} {info['display']}",
            "callback_data": f"work_cat_{key}",
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


def _ask_confirm(chat_id, data):
    cat_info = WORK_CATEGORIES.get(data.get("category", "other"), {})
    cat_display = f"{cat_info.get('emoji', '')} {cat_info.get('display', '')}"

    deadline = data.get("deadline", "")
    deadline_display = format_date_full(deadline) if deadline else "無截止日"

    desc_display = data.get("description") or "無"

    text = (
        "📋 *確認新增工作*\n\n"
        f"📌 標題：{escape_markdown(data['title'])}\n"
        f"📝 描述：{escape_markdown(desc_display)}\n"
        f"📆 截止日：{deadline_display}\n"
        f"📁 分類：{cat_display}\n"
        f"📊 進度：0%\n\n"
        "確認新增？"
    )
    send_message(
        chat_id,
        text,
        reply_markup=build_confirm_keyboard("work_confirm", "work_cancel"),
    )


# ================================================================
#  Save to DynamoDB
# ================================================================

def _do_save(user_id, chat_id, data):
    owner_id = get_owner_id()
    new_ulid = generate_ulid()
    short_id = get_next_short_id(ENTITY_WORK)
    now = get_now()

    deadline = data.get("deadline", "") or ""
    sort_deadline = deadline if deadline else NO_DUE_DATE_SENTINEL
    category = data.get("category", "other")

    item = {
        "PK": f"USER#{owner_id}",
        "SK": f"WORK#{new_ulid}",
        "entity_type": ENTITY_WORK,
        "short_id": short_id,
        "title": data["title"],
        "description": data.get("description", ""),
        "deadline": deadline,
        "category": category,
        "progress": 0,
        "status": WORK_STATUS_IN_PROGRESS,
        "created_at": now.isoformat(),
        # GSI keys
        "GSI1PK": f"USER#{owner_id}#WORK",
        "GSI1SK": f"{sort_deadline}#{new_ulid}",
        "GSI2PK": f"USER#{owner_id}#WORK#{category}",
        "GSI2SK": f"{sort_deadline}#{new_ulid}",
        "GSI3PK": ENTITY_WORK,
        "GSI3SK": format_short_id(short_id),
    }

    put_item(item)
    delete_conversation(user_id)

    deadline_display = format_date_full(deadline) if deadline else "無截止日"

    send_message(
        chat_id,
        f"✅ 工作已新增！\n\n"
        f"📌 {escape_markdown(data['title'])}\n"
        f"📆 截止日：{deadline_display}\n"
        f"📊 進度：{format_progress_bar(0)}\n"
        f"🔖 ID: `{short_id}`",
    )

    logger.info(json.dumps({
        "event_type": "work_created",
        "short_id": short_id,
        "deadline": deadline,
    }))


# ================================================================
#  /work — 查看進行中工作
# ================================================================

def handle_work(user_id, chat_id):
    owner_id = get_owner_id()

    items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#WORK",
        filter_expr=Attr("status").eq(WORK_STATUS_IN_PROGRESS),
    )

    if not items:
        send_message(chat_id, "🔨 *進行中工作*\n\n目前沒有進行中的工作 🎉")
        return

    # Sort: deadline ASC (no-deadline last), then progress DESC
    def sort_key(item):
        dl = item.get("deadline", "") or NO_DUE_DATE_SENTINEL
        progress = int(item.get("progress", 0))
        return (dl, -progress)

    items.sort(key=sort_key)

    today = get_today()
    lines = [f"🔨 *進行中工作*（共 {len(items)} 筆）\n"]

    for item in items:
        progress = int(item.get("progress", 0))
        cat_info = WORK_CATEGORIES.get(item.get("category", "other"), {})
        cat_emoji = cat_info.get("emoji", "📦")

        deadline = item.get("deadline", "")
        if deadline and deadline != NO_DUE_DATE_SENTINEL:
            dl_rel = days_until_display(deadline)
            dl_text = f"📆 {format_date_short(deadline)}（{dl_rel}）"
        else:
            dl_text = "📆 無截止日"

        overdue_flag = ""
        if deadline and deadline < today:
            overdue_flag = " ⚠️"

        lines.append(
            f"{cat_emoji} *{escape_markdown(item.get('title', ''))}*{overdue_flag}\n"
            f"  {format_progress_bar(progress)}\n"
            f"  {dl_text}  `{item.get('short_id', '')}`"
        )
        if item.get("description"):
            lines.append(f"  📝 {escape_markdown(item['description'][:80])}")

    send_message(chat_id, "\n".join(lines))


# ================================================================
#  /update_progress ID % — 更新進度
# ================================================================

def handle_update_progress(user_id, chat_id, args):
    parts = args.split(maxsplit=1)
    if len(parts) < 2:
        send_message(
            chat_id,
            "❌ 格式：`/update_progress ID 百分比`\n"
            "例如：`/update_progress 1 75`",
        )
        return

    sid = parse_short_id(parts[0])
    if sid is None:
        send_message(chat_id, "❌ 無效的工作 ID。")
        return

    pct = parse_percentage(parts[1])
    if pct is None:
        send_message(chat_id, "❌ 進度必須是 0 ~ 100 之間的整數。")
        return

    item = query_gsi3(ENTITY_WORK, sid)
    if item is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{sid}` 的工作。")
        return

    status = item.get("status", "")
    if status == WORK_STATUS_COMPLETED:
        send_message(chat_id, f"⚠️ 工作 `{sid}` 已經完成。")
        return
    if status == WORK_STATUS_ON_HOLD:
        send_message(chat_id, f"⚠️ 工作 `{sid}` 目前暫停中，請先恢復後再更新進度。")
        return

    old_progress = int(item.get("progress", 0))
    now = get_now()

    # Auto-complete if progress reaches 100
    if pct >= 100:
        update_item(
            pk=item["PK"],
            sk=item["SK"],
            update_expr="SET progress = :p, #st = :s, completed_at = :c",
            expr_values={
                ":p": 100,
                ":s": WORK_STATUS_COMPLETED,
                ":c": now.isoformat(),
            },
            expr_names={"#st": "status"},
        )
        send_message(
            chat_id,
            f"🎉 工作已完成！\n\n"
            f"📌 {escape_markdown(item.get('title', ''))}\n"
            f"📊 {format_progress_bar(100)}\n"
            f"🔖 ID: `{sid}`",
        )
        logger.info(json.dumps({
            "event_type": "work_completed",
            "short_id": sid,
        }))
        return

    update_item(
        pk=item["PK"],
        sk=item["SK"],
        update_expr="SET progress = :p",
        expr_values={":p": pct},
    )

    send_message(
        chat_id,
        f"📊 進度已更新！\n\n"
        f"📌 {escape_markdown(item.get('title', ''))}\n"
        f"📊 {format_progress_bar(old_progress)} → {format_progress_bar(pct)}\n"
        f"🔖 ID: `{sid}`",
    )

    logger.info(json.dumps({
        "event_type": "work_progress_updated",
        "short_id": sid,
        "old_progress": old_progress,
        "new_progress": pct,
    }))


# ================================================================
#  /deadlines — 即將到期工作（7 天內）
# ================================================================

def handle_deadlines(user_id, chat_id):
    owner_id = get_owner_id()
    today = get_today()
    today_date = get_today_date()
    end_date = today_date + timedelta(days=7)
    end_str = end_date.strftime("%Y-%m-%d")

    items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#WORK",
        sk_condition=Key("GSI1SK").between(f"0000-00-00#", f"{end_str}#~"),
        filter_expr=Attr("status").eq(WORK_STATUS_IN_PROGRESS),
    )

    if not items:
        send_message(
            chat_id,
            "⏰ *即將到期工作*（7 天內）\n\n沒有即將到期的工作 🎉",
        )
        return

    # Filter: only items with real deadlines within range
    filtered = []
    for item in items:
        dl = item.get("deadline", "")
        if dl and dl != NO_DUE_DATE_SENTINEL and dl <= end_str:
            filtered.append(item)

    if not filtered:
        send_message(
            chat_id,
            "⏰ *即將到期工作*（7 天內）\n\n沒有即將到期的工作 🎉",
        )
        return

    # Sort by deadline ASC
    filtered.sort(key=lambda x: x.get("deadline", ""))

    # Separate overdue vs upcoming
    overdue = [i for i in filtered if i.get("deadline", "") < today]
    upcoming = [i for i in filtered if i.get("deadline", "") >= today]

    lines = [f"⏰ *即將到期工作*（共 {len(filtered)} 筆）\n"]

    if overdue:
        lines.append("🔴 *已逾期*")
        for item in overdue:
            _append_deadline_item(lines, item)
        lines.append("")

    if upcoming:
        lines.append("🟡 *即將到期*")
        for item in upcoming:
            _append_deadline_item(lines, item)

    send_message(chat_id, "\n".join(lines))


def _append_deadline_item(lines, item):
    """Helper to format a single deadline item line."""
    progress = int(item.get("progress", 0))
    deadline = item.get("deadline", "")
    dl_rel = days_until_display(deadline)
    cat_info = WORK_CATEGORIES.get(item.get("category", "other"), {})
    cat_emoji = cat_info.get("emoji", "📦")

    lines.append(
        f"  {cat_emoji} *{escape_markdown(item.get('title', ''))}*\n"
        f"    📆 {format_date_short(deadline)}（{dl_rel}）\n"
        f"    {format_progress_bar(progress)}  `{item.get('short_id', '')}`"
    )