# webhook_handler/handlers/todo.py
# ============================================================
# 待辦事項 — /add_todo, /todos, /done, /del_todo
# ============================================================

import json
import logging

from boto3.dynamodb.conditions import Key, Attr

from bot_constants import (
    ENTITY_TODO,
    TODO_STATUS_PENDING,
    TODO_STATUS_COMPLETED,
    TODO_STATUS_DELETED,
    TODO_CATEGORIES,
    TODO_PRIORITIES,
    NO_DUE_DATE_SENTINEL,
    CONV_MODULE_TODO,
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
    is_past_date,
    validate_text_length,
    get_now,
    get_today,
    format_date_full,
    format_date_short,
    days_until_display,
    escape_markdown,
)

logger = logging.getLogger(__name__)


# ================================================================
#  Conversation — /add_todo
# ================================================================

def handle_add_todo(user_id, chat_id):
    """Start the add-todo conversation."""
    set_conversation(user_id, CONV_MODULE_TODO, "title", {})
    send_message(chat_id, "📝 *新增待辦*\n\n請輸入待辦標題：")


# ----------------------------------------------------------------
#  Text input dispatcher
# ----------------------------------------------------------------

def handle_step(user_id, chat_id, text, step, data):
    """Route text input to the correct step handler."""
    if step == "title":
        _step_title(user_id, chat_id, text, data)
    elif step == "due_date":
        _step_due_date(user_id, chat_id, text, data)
    elif step == "priority":
        send_message(chat_id, "請點選上方按鈕選擇優先級。")
    elif step == "category":
        send_message(chat_id, "請點選上方按鈕選擇分類。")
    elif step == "notes":
        _step_notes(user_id, chat_id, text, data)
    elif step == "confirm":
        send_message(chat_id, "請點選上方按鈕確認或取消。")
    else:
        logger.warning(f"Unknown todo step: {step}")
        send_message(chat_id, "⚠️ 未知的步驟，請輸入 /cancel 重新開始。")


# ----------------------------------------------------------------
#  Callback dispatcher
# ----------------------------------------------------------------

def handle_callback(user_id, chat_id, message_id, callback_data, step, data):
    """Route callback query to the correct handler."""

    # --- Due date: skip ---
    if callback_data == "todo_skip_due":
        if step != "due_date":
            return
        data["due_date"] = ""
        update_conversation(user_id, "priority", data)
        _ask_priority(chat_id)

    # --- Priority ---
    elif callback_data.startswith("todo_pri_"):
        if step != "priority":
            return
        try:
            pri = int(callback_data[len("todo_pri_"):])
        except ValueError:
            return
        if pri not in TODO_PRIORITIES:
            send_message(chat_id, "❌ 無效的優先級，請重新選擇。")
            return
        data["priority"] = pri
        update_conversation(user_id, "category", data)
        _ask_category(chat_id)

    # --- Category ---
    elif callback_data.startswith("todo_cat_"):
        if step != "category":
            return
        category = callback_data[len("todo_cat_"):]
        if category not in TODO_CATEGORIES:
            send_message(chat_id, "❌ 無效的分類，請重新選擇。")
            return
        data["category"] = category
        update_conversation(user_id, "notes", data)
        _ask_notes(chat_id)

    # --- Notes: skip ---
    elif callback_data == "todo_skip_notes":
        if step != "notes":
            return
        data["notes"] = ""
        update_conversation(user_id, "confirm", data)
        _ask_confirm(chat_id, data)

    # --- Confirm / Cancel ---
    elif callback_data == "todo_confirm":
        if step != "confirm":
            return
        _do_save(user_id, chat_id, data)

    elif callback_data == "todo_cancel":
        delete_conversation(user_id)
        send_message(chat_id, "✅ 已取消新增待辦。")


# ================================================================
#  Step handlers
# ================================================================

def _step_title(user_id, chat_id, text, data):
    valid, err = validate_text_length(text, 1, 100)
    if not valid:
        send_message(chat_id, f"❌ {err}")
        return

    data["title"] = text.strip()
    update_conversation(user_id, "due_date", data)
    send_message(
        chat_id,
        "📆 請輸入截止日期：\n\n"
        "支援格式：\n"
        "• `今天`、`明天`、`後天`\n"
        "• `下週一` ~ `下週日`\n"
        "• `下個月15號`\n"
        "• `2026-03-15` 或 `03/15`",
        reply_markup=build_skip_keyboard("todo_skip_due", "⏭ 無截止日"),
    )


def _step_due_date(user_id, chat_id, text, data):
    date_str = parse_date(text)
    if date_str is None:
        send_message(chat_id, "❌ 無法辨識日期格式，請重新輸入或點選跳過。")
        return
    if is_past_date(date_str):
        send_message(chat_id, "❌ 不能選擇過去的日期，請重新輸入。")
        return

    data["due_date"] = date_str
    update_conversation(user_id, "priority", data)
    _ask_priority(chat_id)


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

def _ask_priority(chat_id):
    rows = []
    for pri, info in TODO_PRIORITIES.items():
        rows.append([{
            "text": f"{info['emoji']} {info['display']}",
            "callback_data": f"todo_pri_{pri}",
        }])
    send_message(
        chat_id,
        "🔔 請選擇優先級：",
        reply_markup=build_inline_keyboard(rows),
    )


def _ask_category(chat_id):
    rows = []
    row = []
    for key, info in TODO_CATEGORIES.items():
        row.append({
            "text": f"{info['emoji']} {info['display']}",
            "callback_data": f"todo_cat_{key}",
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
        reply_markup=build_skip_keyboard("todo_skip_notes"),
    )


def _ask_confirm(chat_id, data):
    pri = data.get("priority", 3)
    pri_info = TODO_PRIORITIES.get(pri, {})
    pri_display = f"{pri_info.get('emoji', '')} {pri_info.get('display', '')}"

    cat_info = TODO_CATEGORIES.get(data.get("category", "other"), {})
    cat_display = f"{cat_info.get('emoji', '')} {cat_info.get('display', '')}"

    due = data.get("due_date", "")
    due_display = format_date_full(due) if due else "無截止日"

    notes_display = data.get("notes") or "無"

    text = (
        "📋 *確認新增待辦*\n\n"
        f"📌 標題：{escape_markdown(data['title'])}\n"
        f"📆 截止日：{due_display}\n"
        f"🔔 優先級：{pri_display}\n"
        f"📁 分類：{cat_display}\n"
        f"📝 備註：{escape_markdown(notes_display)}\n\n"
        "確認新增？"
    )
    send_message(
        chat_id,
        text,
        reply_markup=build_confirm_keyboard("todo_confirm", "todo_cancel"),
    )


# ================================================================
#  Save to DynamoDB
# ================================================================

def _do_save(user_id, chat_id, data):
    owner_id = get_owner_id()
    new_ulid = generate_ulid()
    short_id = get_next_short_id(ENTITY_TODO)
    now = get_now()

    due_date = data.get("due_date", "") or ""
    sort_due = due_date if due_date else NO_DUE_DATE_SENTINEL
    category = data.get("category", "other")
    priority = data.get("priority", 3)

    item = {
        "PK": f"USER#{owner_id}",
        "SK": f"TODO#{new_ulid}",
        "entity_type": ENTITY_TODO,
        "short_id": short_id,
        "title": data["title"],
        "due_date": due_date,
        "priority": priority,
        "category": category,
        "notes": data.get("notes", ""),
        "status": TODO_STATUS_PENDING,
        "created_at": now.isoformat(),
        # GSI keys
        "GSI1PK": f"USER#{owner_id}#TODO",
        "GSI1SK": f"{sort_due}#{new_ulid}",
        "GSI2PK": f"USER#{owner_id}#TODO#{category}",
        "GSI2SK": f"{sort_due}#{new_ulid}",
        "GSI3PK": ENTITY_TODO,
        "GSI3SK": format_short_id(short_id),
    }

    put_item(item)
    delete_conversation(user_id)

    due_display = format_date_full(due_date) if due_date else "無截止日"
    pri_info = TODO_PRIORITIES.get(priority, {})

    send_message(
        chat_id,
        f"✅ 待辦已新增！\n\n"
        f"📌 {escape_markdown(data['title'])}\n"
        f"📆 {due_display}\n"
        f"{pri_info.get('emoji', '')} 優先級：{pri_info.get('display', '')}\n"
        f"🔖 ID: `{short_id}`",
    )

    logger.info(json.dumps({
        "event_type": "todo_created",
        "short_id": short_id,
        "due_date": due_date,
    }))


# ================================================================
#  /todos — 查看待辦清單
# ================================================================

def handle_todos(user_id, chat_id):
    owner_id = get_owner_id()

    items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#TODO",
        filter_expr=Attr("status").eq(TODO_STATUS_PENDING),
    )

    if not items:
        send_message(chat_id, "📝 *待辦清單*\n\n目前沒有待辦事項 🎉")
        return

    # Sort: priority ASC, then due_date ASC
    def sort_key(item):
        pri = int(item.get("priority", 3))
        due = item.get("due_date", "") or NO_DUE_DATE_SENTINEL
        return (pri, due)

    items.sort(key=sort_key)

    today = get_today()
    lines = [f"📝 *待辦清單*（共 {len(items)} 筆）\n"]

    for item in items:
        pri = int(item.get("priority", 3))
        pri_info = TODO_PRIORITIES.get(pri, {})
        pri_emoji = pri_info.get("emoji", "⚪")

        due = item.get("due_date", "")
        if due and due != NO_DUE_DATE_SENTINEL:
            due_rel = days_until_display(due)
            due_text = f"📆 {format_date_short(due)}（{due_rel}）"
        else:
            due_text = "📆 無截止日"

        cat_info = TODO_CATEGORIES.get(item.get("category", "other"), {})
        cat_emoji = cat_info.get("emoji", "📦")

        overdue_flag = ""
        if due and due < today:
            overdue_flag = " ⚠️"

        lines.append(
            f"{pri_emoji} *{escape_markdown(item.get('title', ''))}*{overdue_flag}\n"
            f"  {due_text}  {cat_emoji}  `{item.get('short_id', '')}`"
        )
        if item.get("notes"):
            lines.append(f"  📝 {escape_markdown(item['notes'])}")

    send_message(chat_id, "\n".join(lines))


# ================================================================
#  /done ID — 完成待辦
# ================================================================

def handle_done(user_id, chat_id, args):
    sid = parse_short_id(args)
    if sid is None:
        send_message(chat_id, "❌ 請提供待辦 ID，例如：`/done 3`")
        return

    item = query_gsi3(ENTITY_TODO, sid)
    if item is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{sid}` 的待辦。")
        return

    status = item.get("status", "")
    if status == TODO_STATUS_COMPLETED:
        send_message(chat_id, f"⚠️ 待辦 `{sid}` 已經是完成狀態。")
        return
    if status == TODO_STATUS_DELETED:
        send_message(chat_id, f"⚠️ 待辦 `{sid}` 已被刪除。")
        return

    now = get_now()
    update_item(
        pk=item["PK"],
        sk=item["SK"],
        update_expr="SET #st = :s, completed_at = :c",
        expr_values={
            ":s": TODO_STATUS_COMPLETED,
            ":c": now.isoformat(),
        },
        expr_names={"#st": "status"},
    )

    send_message(
        chat_id,
        f"✅ 已完成待辦：\n\n"
        f"📌 {escape_markdown(item.get('title', ''))}\n"
        f"🔖 ID: `{sid}`",
    )

    logger.info(json.dumps({
        "event_type": "todo_completed",
        "short_id": sid,
    }))


# ================================================================
#  /del_todo ID — 刪除待辦
# ================================================================

def handle_del_todo(user_id, chat_id, args):
    sid = parse_short_id(args)
    if sid is None:
        send_message(chat_id, "❌ 請提供待辦 ID，例如：`/del_todo 3`")
        return

    item = query_gsi3(ENTITY_TODO, sid)
    if item is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{sid}` 的待辦。")
        return

    status = item.get("status", "")
    if status == TODO_STATUS_DELETED:
        send_message(chat_id, f"⚠️ 待辦 `{sid}` 已經被刪除。")
        return

    update_item(
        pk=item["PK"],
        sk=item["SK"],
        update_expr="SET #st = :s",
        expr_values={":s": TODO_STATUS_DELETED},
        expr_names={"#st": "status"},
    )

    send_message(
        chat_id,
        f"🗑️ 已刪除待辦：\n\n"
        f"📌 {escape_markdown(item.get('title', ''))}\n"
        f"🔖 ID: `{sid}`",
    )

    logger.info(json.dumps({
        "event_type": "todo_deleted",
        "short_id": sid,
    }))