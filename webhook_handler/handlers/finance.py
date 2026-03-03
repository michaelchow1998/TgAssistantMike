# webhook_handler/handlers/finance.py
# ============================================================
# 財務管理 — /add_payment, /add_income, /add_expense,
#            /payments, /paid, /finance_summary
# ============================================================

import json
import logging
from decimal import Decimal
from datetime import datetime

from boto3.dynamodb.conditions import Key, Attr

from bot_constants import (
    ENTITY_FIN,
    FIN_TYPE_PAYMENT,
    FIN_TYPE_INCOME,
    FIN_TYPE_EXPENSE,
    FIN_STATUS_PENDING,
    FIN_STATUS_PAID,
    FIN_STATUS_CANCELLED,
    FIN_CATEGORIES,
    CONV_MODULE_FINANCE,
    CONV_MODULE_EDIT_FIN,
)
from bot_config import get_owner_id
from bot_telegram import (
    send_message,
    edit_message_text,
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
    parse_amount,
    parse_short_id,
    is_past_date,
    validate_text_length,
    get_now,
    get_today,
    get_today_date,
    format_date_full,
    format_date_short,
    format_currency,
    days_until_display,
    escape_markdown,
)

logger = logging.getLogger(__name__)

# Display mapping for finance types
_FIN_TYPE_DISPLAY = {
    FIN_TYPE_PAYMENT: {"label": "應付款項", "emoji": "💳", "verb": "新增應付款項"},
    FIN_TYPE_INCOME:  {"label": "收入",     "emoji": "💵", "verb": "新增收入"},
    FIN_TYPE_EXPENSE: {"label": "支出",     "emoji": "💸", "verb": "新增支出"},
}


# ================================================================
#  Conversation starters
# ================================================================

def handle_add_payment(user_id, chat_id):
    _start_conversation(user_id, chat_id, FIN_TYPE_PAYMENT)


def handle_add_income(user_id, chat_id):
    _start_conversation(user_id, chat_id, FIN_TYPE_INCOME)


def handle_add_expense(user_id, chat_id):
    _start_conversation(user_id, chat_id, FIN_TYPE_EXPENSE)


def _start_conversation(user_id, chat_id, fin_type):
    info = _FIN_TYPE_DISPLAY[fin_type]
    set_conversation(user_id, CONV_MODULE_FINANCE, "title", {"fin_type": fin_type})
    send_message(
        chat_id,
        f"{info['emoji']} *{info['verb']}*\n\n請輸入項目名稱：",
    )


# ----------------------------------------------------------------
#  Text input dispatcher
# ----------------------------------------------------------------

def handle_step(user_id, chat_id, text, step, data):
    if data.get("_module") == CONV_MODULE_EDIT_FIN:
        _edit_fin_handle_step(user_id, chat_id, text, step, data)
        return

    if step == "title":
        _step_title(user_id, chat_id, text, data)
    elif step == "amount":
        _step_amount(user_id, chat_id, text, data)
    elif step == "date":
        _step_date(user_id, chat_id, text, data)
    elif step == "category":
        send_message(chat_id, "請點選上方按鈕選擇分類。")
    elif step == "notes":
        _step_notes(user_id, chat_id, text, data)
    elif step == "confirm":
        send_message(chat_id, "請點選上方按鈕確認或取消。")
    else:
        logger.warning(f"Unknown finance step: {step}")
        send_message(chat_id, "⚠️ 未知的步驟，請輸入 /cancel 重新開始。")


# ----------------------------------------------------------------
#  Callback dispatcher
# ----------------------------------------------------------------

def handle_callback(user_id, chat_id, message_id, callback_data, step, data):
    if data.get("_module") == CONV_MODULE_EDIT_FIN:
        _edit_fin_handle_callback(user_id, chat_id, message_id, callback_data, step, data)
        return

    # --- Date: skip (only for payment) ---
    if callback_data == "fin_skip_date":
        if step != "date":
            return
        data["date"] = ""
        update_conversation(user_id, "category", data)
        _ask_category(chat_id)

    # --- Category ---
    elif callback_data.startswith("fin_cat_"):
        if step != "category":
            return
        category = callback_data[len("fin_cat_"):]
        if category not in FIN_CATEGORIES:
            send_message(chat_id, "❌ 無效的分類，請重新選擇。")
            return
        data["category"] = category
        update_conversation(user_id, "notes", data)
        _ask_notes(chat_id)

    # --- Notes: skip ---
    elif callback_data == "fin_skip_notes":
        if step != "notes":
            return
        data["notes"] = ""
        update_conversation(user_id, "confirm", data)
        _ask_confirm(chat_id, data)

    # --- Confirm / Cancel ---
    elif callback_data == "fin_confirm":
        if step != "confirm":
            return
        _do_save(user_id, chat_id, data)

    elif callback_data == "fin_cancel":
        delete_conversation(user_id)
        send_message(chat_id, "✅ 已取消操作。")


# ================================================================
#  Step handlers
# ================================================================

def _step_title(user_id, chat_id, text, data):
    valid, err = validate_text_length(text, 1, 100)
    if not valid:
        send_message(chat_id, f"❌ {err}")
        return

    data["title"] = text.strip()
    update_conversation(user_id, "amount", data)
    send_message(chat_id, "💲 請輸入金額（例如 `1500` 或 `299.50`）：")


def _step_amount(user_id, chat_id, text, data):
    amount = parse_amount(text)
    if amount is None:
        send_message(
            chat_id,
            "❌ 金額格式不正確。\n"
            "請輸入正數，最多兩位小數，例如 `1500` 或 `299.50`。",
        )
        return

    # Store as string to survive DynamoDB/JSON round-trip
    data["amount"] = str(amount)
    update_conversation(user_id, "date", data)
    _ask_date(chat_id, data.get("fin_type", ""))


def _step_date(user_id, chat_id, text, data):
    date_str = parse_date(text)
    if date_str is None:
        send_message(chat_id, "❌ 無法辨識日期格式，請重新輸入。")
        return

    fin_type = data.get("fin_type", "")
    # For income/expense, allow past dates (recording historical entries)
    # For payment, don't allow past due dates
    if fin_type == FIN_TYPE_PAYMENT and is_past_date(date_str):
        send_message(chat_id, "❌ 付款到期日不能是過去的日期，請重新輸入。")
        return

    data["date"] = date_str
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

def _ask_date(chat_id, fin_type):
    if fin_type == FIN_TYPE_PAYMENT:
        label = "📆 請輸入付款到期日："
        skip_label = "⏭ 無到期日"
    elif fin_type == FIN_TYPE_INCOME:
        label = "📆 請輸入收入日期："
        skip_label = None
    else:
        label = "📆 請輸入支出日期："
        skip_label = None

    text = (
        f"{label}\n\n"
        "支援格式：\n"
        "• `今天`、`明天`、`後天`\n"
        "• `下週一` ~ `下週日`\n"
        "• `下個月15號`\n"
        "• `2026-03-15` 或 `03/15`"
    )

    if skip_label:
        send_message(
            chat_id,
            text,
            reply_markup=build_skip_keyboard("fin_skip_date", skip_label),
        )
    else:
        send_message(chat_id, text)


def _ask_category(chat_id):
    rows = []
    row = []
    for key, info in FIN_CATEGORIES.items():
        row.append({
            "text": f"{info['emoji']} {info['display']}",
            "callback_data": f"fin_cat_{key}",
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
        reply_markup=build_skip_keyboard("fin_skip_notes"),
    )


def _ask_confirm(chat_id, data):
    fin_type = data.get("fin_type", "")
    type_info = _FIN_TYPE_DISPLAY.get(fin_type, {})
    type_label = type_info.get("label", "")
    type_emoji = type_info.get("emoji", "💰")

    amount = Decimal(data.get("amount", "0"))
    cat_info = FIN_CATEGORIES.get(data.get("category", "other"), {})
    cat_display = f"{cat_info.get('emoji', '')} {cat_info.get('display', '')}"

    fin_date = data.get("date", "")
    if fin_type == FIN_TYPE_PAYMENT:
        date_label = "📆 到期日"
    elif fin_type == FIN_TYPE_INCOME:
        date_label = "📆 收入日期"
    else:
        date_label = "📆 支出日期"
    date_display = format_date_full(fin_date) if fin_date else "未設定"

    notes_display = data.get("notes") or "無"

    text = (
        f"📋 *確認{type_info.get('verb', '')}*\n\n"
        f"{type_emoji} 類型：{type_label}\n"
        f"📌 名稱：{escape_markdown(data['title'])}\n"
        f"💲 金額：{format_currency(amount)}\n"
        f"{date_label}：{date_display}\n"
        f"📁 分類：{cat_display}\n"
        f"📝 備註：{escape_markdown(notes_display)}\n\n"
        "確認新增？"
    )
    send_message(
        chat_id,
        text,
        reply_markup=build_confirm_keyboard("fin_confirm", "fin_cancel"),
    )


# ================================================================
#  Save to DynamoDB
# ================================================================

def _do_save(user_id, chat_id, data):
    owner_id = get_owner_id()
    new_ulid = generate_ulid()
    short_id = get_next_short_id(ENTITY_FIN)
    now = get_now()

    fin_type = data.get("fin_type", FIN_TYPE_EXPENSE)
    fin_date = data.get("date", "") or ""
    category = data.get("category", "other")
    amount = Decimal(data.get("amount", "0"))

    # Determine initial status
    if fin_type == FIN_TYPE_PAYMENT:
        status = FIN_STATUS_PENDING
    else:
        status = FIN_STATUS_PAID  # income/expense are "paid" on creation

    # Sort key: date + ULID for chronological ordering
    sort_date = fin_date if fin_date else now.strftime("%Y-%m-%d")

    item = {
        "PK": f"USER#{owner_id}",
        "SK": f"FIN#{new_ulid}",
        "entity_type": ENTITY_FIN,
        "short_id": short_id,
        "fin_type": fin_type,
        "title": data["title"],
        "amount": amount,
        "date": fin_date,
        "category": category,
        "notes": data.get("notes", ""),
        "status": status,
        "created_at": now.isoformat(),
        # GSI keys
        "GSI1PK": f"USER#{owner_id}#FIN#{fin_type}",
        "GSI1SK": f"{sort_date}#{new_ulid}",
        "GSI2PK": f"USER#{owner_id}#FIN#{category}",
        "GSI2SK": f"{sort_date}#{new_ulid}",
        "GSI3PK": ENTITY_FIN,
        "GSI3SK": format_short_id(short_id),
    }

    put_item(item)
    delete_conversation(user_id)

    type_info = _FIN_TYPE_DISPLAY.get(fin_type, {})
    date_display = format_date_full(fin_date) if fin_date else "未設定"

    send_message(
        chat_id,
        f"✅ {type_info.get('label', '項目')}已新增！\n\n"
        f"{type_info.get('emoji', '💰')} {escape_markdown(data['title'])}\n"
        f"💲 {format_currency(amount)}\n"
        f"📆 {date_display}\n"
        f"🔖 ID: `{short_id}`",
    )

    logger.info(json.dumps({
        "event_type": "finance_created",
        "short_id": short_id,
        "fin_type": fin_type,
        "amount": str(amount),
    }))


# ================================================================
#  /payments — 待付款項
# ================================================================

def handle_payments(user_id, chat_id):
    owner_id = get_owner_id()

    items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#FIN#{FIN_TYPE_PAYMENT}",
        filter_expr=Attr("status").eq(FIN_STATUS_PENDING),
    )

    if not items:
        send_message(chat_id, "💳 *待付款項*\n\n目前沒有待付款項 🎉")
        return

    # Sort: date ASC (no-date last)
    def sort_key(item):
        d = item.get("date", "") or "9999-12-31"
        return d

    items.sort(key=sort_key)

    today = get_today()
    total_amount = sum(Decimal(str(i.get("amount", 0))) for i in items)

    lines = [
        f"💳 *待付款項*（共 {len(items)} 筆）\n"
        f"💲 合計：{format_currency(total_amount)}\n"
    ]

    for item in items:
        amount = Decimal(str(item.get("amount", 0)))
        cat_info = FIN_CATEGORIES.get(item.get("category", "other"), {})
        cat_emoji = cat_info.get("emoji", "📦")

        fin_date = item.get("date", "")
        if fin_date:
            dl_rel = days_until_display(fin_date)
            date_text = f"📆 {format_date_short(fin_date)}（{dl_rel}）"
        else:
            date_text = "📆 無到期日"

        overdue_flag = ""
        if fin_date and fin_date < today:
            overdue_flag = " ⚠️"

        lines.append(
            f"{cat_emoji} *{escape_markdown(item.get('title', ''))}*{overdue_flag}\n"
            f"  💲 {format_currency(amount)}  {date_text}\n"
            f"  🔖 `{item.get('short_id', '')}`"
        )

    lines.append(f"\n標記已付：`/paid ID`")
    send_message(chat_id, "\n".join(lines))


# ================================================================
#  /paid ID — 標記已付
# ================================================================

def handle_paid(user_id, chat_id, args):
    sid = parse_short_id(args)
    if sid is None:
        send_message(chat_id, "❌ 請提供款項 ID，例如：`/paid 3`")
        return

    item = query_gsi3(ENTITY_FIN, sid)
    if item is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{sid}` 的財務項目。")
        return

    if item.get("fin_type") != FIN_TYPE_PAYMENT:
        send_message(chat_id, f"⚠️ ID `{sid}` 不是應付款項，無法標記已付。")
        return

    status = item.get("status", "")
    if status == FIN_STATUS_PAID:
        send_message(chat_id, f"⚠️ 款項 `{sid}` 已經是已付狀態。")
        return
    if status == FIN_STATUS_CANCELLED:
        send_message(chat_id, f"⚠️ 款項 `{sid}` 已被取消。")
        return

    now = get_now()
    update_item(
        pk=item["PK"],
        sk=item["SK"],
        update_expr="SET #st = :s, paid_at = :p",
        expr_values={
            ":s": FIN_STATUS_PAID,
            ":p": now.isoformat(),
        },
        expr_names={"#st": "status"},
    )

    amount = Decimal(str(item.get("amount", 0)))
    send_message(
        chat_id,
        f"✅ 已標記為已付！\n\n"
        f"📌 {escape_markdown(item.get('title', ''))}\n"
        f"💲 {format_currency(amount)}\n"
        f"🔖 ID: `{sid}`",
    )

    logger.info(json.dumps({
        "event_type": "payment_paid",
        "short_id": sid,
        "amount": str(amount),
    }))


# ================================================================
#  /finance_summary — 月度統計
# ================================================================

def handle_finance_summary(user_id, chat_id, args=""):
    import re
    owner_id = get_owner_id()
    today_date = get_today_date()

    # Parse optional month argument (YYYY-MM)
    if args and args.strip():
        m = re.match(r"^(\d{4}-(?:0[1-9]|1[0-2]))$", args.strip())
        if not m:
            send_message(chat_id, "❌ 月份格式不正確，請使用 `YYYY-MM`，例如：`/finance_summary 2026-02`")
            return
        month_prefix = m.group(1)
    else:
        month_prefix = today_date.strftime("%Y-%m")

    month_label = month_prefix[:4] + "年" + month_prefix[5:7] + "月"

    # --- Fetch income ---
    income_items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#FIN#{FIN_TYPE_INCOME}",
        sk_condition=Key("GSI1SK").begins_with(month_prefix),
    )

    # --- Fetch expenses ---
    expense_items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#FIN#{FIN_TYPE_EXPENSE}",
        sk_condition=Key("GSI1SK").begins_with(month_prefix),
    )

    # --- Fetch payments (paid this month) ---
    payment_items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#FIN#{FIN_TYPE_PAYMENT}",
        sk_condition=Key("GSI1SK").begins_with(month_prefix),
    )
    paid_payments = [p for p in payment_items if p.get("status") == FIN_STATUS_PAID]
    pending_payments = [p for p in payment_items if p.get("status") == FIN_STATUS_PENDING]

    # --- Calculate totals ---
    total_income = sum(Decimal(str(i.get("amount", 0))) for i in income_items)
    total_expense = sum(Decimal(str(i.get("amount", 0))) for i in expense_items)
    total_paid = sum(Decimal(str(i.get("amount", 0))) for i in paid_payments)
    total_pending = sum(Decimal(str(i.get("amount", 0))) for i in pending_payments)

    total_outflow = total_expense + total_paid
    net = total_income - total_outflow

    # --- Category breakdown for expenses ---
    expense_by_cat = {}
    for item in expense_items:
        cat = item.get("category", "other")
        amt = Decimal(str(item.get("amount", 0)))
        expense_by_cat[cat] = expense_by_cat.get(cat, Decimal("0")) + amt

    # Sort categories by amount DESC
    sorted_cats = sorted(expense_by_cat.items(), key=lambda x: x[1], reverse=True)

    # --- Build message ---
    net_emoji = "📈" if net >= 0 else "📉"

    lines = [
        f"💰 *{month_label} 財務摘要*\n",
        f"💵 收入：{format_currency(total_income)}（{len(income_items)} 筆）",
        f"💸 支出：{format_currency(total_expense)}（{len(expense_items)} 筆）",
        f"💳 已付款：{format_currency(total_paid)}（{len(paid_payments)} 筆）",
        f"⏳ 待付款：{format_currency(total_pending)}（{len(pending_payments)} 筆）",
        f"",
        f"{net_emoji} 淨額（收入 - 支出 - 已付款）：{format_currency(net)}",
    ]

    if sorted_cats:
        lines.append("")
        lines.append("📊 *支出分類明細*")
        for cat, amt in sorted_cats:
            cat_info = FIN_CATEGORIES.get(cat, {})
            emoji = cat_info.get("emoji", "📦")
            display = cat_info.get("display", cat)
            # Calculate percentage
            pct = (amt / total_expense * 100) if total_expense > 0 else Decimal("0")
            lines.append(f"  {emoji} {display}：{format_currency(amt)}（{pct:.0f}%）")

    if not income_items and not expense_items and not payment_items:
        lines = [
            f"💰 *{month_label} 財務摘要*\n",
            f"{month_label}尚無任何財務紀錄。",
            "",
            "提示：若記錄在其他月份，可指定月份，例如：",
            "`/finance_summary 2026-02`",
        ]

    send_message(chat_id, "\n".join(lines))


# ================================================================
#  /del_fin ID — 刪除財務記錄
# ================================================================

def handle_del_fin(user_id, chat_id, args):
    sid = parse_short_id(args)
    if sid is None:
        send_message(chat_id, "❌ 請提供財務記錄 ID，例如：`/del_fin 3`")
        return

    item = query_gsi3(ENTITY_FIN, sid)
    if item is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{sid}` 的財務記錄。")
        return

    if item.get("status") == FIN_STATUS_CANCELLED:
        send_message(chat_id, f"⚠️ 記錄 `{sid}` 已被刪除。")
        return

    fin_type = item.get("fin_type", "")
    type_info = _FIN_TYPE_DISPLAY.get(fin_type, {})
    type_emoji = type_info.get("emoji", "💰")
    amount = Decimal(str(item.get("amount", 0)))

    text = (
        f"🗑️ *確認刪除財務記錄？*\n\n"
        f"{type_emoji} {escape_markdown(item.get('title', ''))}\n"
        f"💲 {format_currency(amount)}\n"
        f"🔖 ID: `{sid}`"
    )
    send_message(
        chat_id,
        text,
        reply_markup=build_confirm_keyboard(
            f"delfin_confirm_{sid}",
            f"delfin_cancel_{sid}",
        ),
    )


def handle_del_fin_callback(user_id, chat_id, message_id, callback_data):
    """Handle delfin_confirm_<sid> / delfin_cancel_<sid> standalone callbacks."""
    if callback_data.startswith("delfin_confirm_"):
        raw = callback_data[len("delfin_confirm_"):]
        sid = parse_short_id(raw)
        if sid is None:
            return

        item = query_gsi3(ENTITY_FIN, sid)
        if item is None:
            edit_message_text(chat_id, message_id, f"❌ 找不到 ID `{sid}`。")
            return

        update_item(
            pk=item["PK"],
            sk=item["SK"],
            update_expr="SET #st = :s",
            expr_values={":s": FIN_STATUS_CANCELLED},
            expr_names={"#st": "status"},
        )

        amount = Decimal(str(item.get("amount", 0)))
        fin_type = item.get("fin_type", "")
        type_info = _FIN_TYPE_DISPLAY.get(fin_type, {})
        edit_message_text(
            chat_id,
            message_id,
            f"🗑️ 已刪除財務記錄：\n\n"
            f"{type_info.get('emoji', '💰')} {escape_markdown(item.get('title', ''))}\n"
            f"💲 {format_currency(amount)}\n"
            f"🔖 ID: `{sid}`",
        )
        logger.info(json.dumps({
            "event_type": "finance_deleted",
            "short_id": sid,
        }))

    elif callback_data.startswith("delfin_cancel_"):
        edit_message_text(chat_id, message_id, "✅ 已取消刪除。")


# ================================================================
#  /edit_fin ID — 編輯財務記錄
# ================================================================

def handle_edit_fin(user_id, chat_id, args):
    sid = parse_short_id(args)
    if sid is None:
        send_message(chat_id, "❌ 請提供財務記錄 ID，例如：`/edit_fin 3`")
        return

    item = query_gsi3(ENTITY_FIN, sid)
    if item is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{sid}` 的財務記錄。")
        return

    if item.get("status") == FIN_STATUS_CANCELLED:
        send_message(chat_id, f"⚠️ 記錄 `{sid}` 已被刪除，無法編輯。")
        return

    conv_data = {
        "_module": CONV_MODULE_EDIT_FIN,
        "pk": item["PK"],
        "sk": item["SK"],
        "short_id": sid,
        "fin_type": item.get("fin_type", ""),
    }
    set_conversation(user_id, CONV_MODULE_EDIT_FIN, "choose_field", conv_data)
    _ask_edit_fin_field(chat_id, item)


def _ask_edit_fin_field(chat_id, item):
    fin_type = item.get("fin_type", "")
    type_info = _FIN_TYPE_DISPLAY.get(fin_type, {})
    type_emoji = type_info.get("emoji", "💰")
    amount = Decimal(str(item.get("amount", 0)))
    cat_info = FIN_CATEGORIES.get(item.get("category", "other"), {})
    cat_display = f"{cat_info.get('emoji', '')} {cat_info.get('display', '')}"
    fin_date = item.get("date", "")
    date_display = format_date_full(fin_date) if fin_date else "未設定"
    notes = item.get("notes", "") or "無"

    text = (
        f"✏️ *編輯財務記錄：{escape_markdown(item.get('title', ''))}*\n\n"
        f"{type_emoji} 類型：{type_info.get('label', '')}\n"
        f"1️⃣ 名稱：{escape_markdown(item.get('title', ''))}\n"
        f"2️⃣ 金額：{format_currency(amount)}\n"
        f"3️⃣ 日期：{date_display}\n"
        f"4️⃣ 分類：{cat_display}\n"
        f"5️⃣ 備註：{escape_markdown(notes)}\n\n"
        "請選擇要編輯的欄位："
    )
    rows = [
        [
            {"text": "1️⃣ 名稱", "callback_data": "editfin_field_title"},
            {"text": "2️⃣ 金額", "callback_data": "editfin_field_amount"},
        ],
        [
            {"text": "3️⃣ 日期", "callback_data": "editfin_field_date"},
            {"text": "4️⃣ 分類", "callback_data": "editfin_field_category"},
        ],
        [
            {"text": "5️⃣ 備註", "callback_data": "editfin_field_notes"},
        ],
        [
            {"text": "✅ 完成編輯", "callback_data": "editfin_done"},
        ],
    ]
    send_message(chat_id, text, reply_markup=build_inline_keyboard(rows))


def _reload_fin_item(data):
    """Re-fetch the finance item from DynamoDB using PK/SK stored in conv data."""
    from bot_db import get_item
    return get_item(data["pk"], data["sk"])


def _edit_fin_handle_callback(user_id, chat_id, message_id, callback_data, step, data):
    if step == "choose_field":
        if callback_data == "editfin_done":
            delete_conversation(user_id)
            send_message(chat_id, "✅ 編輯完成。")
            return

        field_map = {
            "editfin_field_title":    ("edit_title",    "請輸入新的名稱："),
            "editfin_field_amount":   ("edit_amount",   "請輸入新的金額："),
            "editfin_field_date":     ("edit_date",     None),
            "editfin_field_category": ("edit_category", None),
            "editfin_field_notes":    ("edit_notes",    "請輸入新的備註（輸入「無」清除）："),
        }

        if callback_data not in field_map:
            return

        new_step, prompt = field_map[callback_data]
        update_conversation(user_id, new_step, data)

        if callback_data == "editfin_field_category":
            _ask_category(chat_id)
        elif callback_data == "editfin_field_date":
            fin_type = data.get("fin_type", "")
            _ask_date(chat_id, fin_type)
        else:
            send_message(chat_id, f"✏️ {prompt}")

    elif step == "edit_category":
        if not callback_data.startswith("fin_cat_"):
            return
        category = callback_data[len("fin_cat_"):]
        if category not in FIN_CATEGORIES:
            send_message(chat_id, "❌ 無效的分類，請重新選擇。")
            return

        owner_id = data["pk"].split("#")[1]
        update_item(
            pk=data["pk"],
            sk=data["sk"],
            update_expr="SET category = :c, GSI2PK = :g2pk",
            expr_values={
                ":c": category,
                ":g2pk": f"USER#{owner_id}#FIN#{category}",
            },
        )
        cat_info = FIN_CATEGORIES.get(category, {})
        cat_display = f"{cat_info.get('emoji', '')} {cat_info.get('display', '')}"
        send_message(chat_id, f"✅ 分類已更新為：{cat_display}")

        update_conversation(user_id, "choose_field", data)
        item = _reload_fin_item(data)
        if item:
            _ask_edit_fin_field(chat_id, item)


def _edit_fin_handle_step(user_id, chat_id, text, step, data):
    if step == "edit_title":
        valid, err = validate_text_length(text, 1, 100)
        if not valid:
            send_message(chat_id, f"❌ {err}")
            return
        new_title = text.strip()
        update_item(
            pk=data["pk"],
            sk=data["sk"],
            update_expr="SET title = :t",
            expr_values={":t": new_title},
        )
        send_message(chat_id, f"✅ 名稱已更新為：{escape_markdown(new_title)}")

    elif step == "edit_amount":
        amount = parse_amount(text)
        if amount is None:
            send_message(chat_id, "❌ 金額格式不正確，請重新輸入。")
            return
        update_item(
            pk=data["pk"],
            sk=data["sk"],
            update_expr="SET amount = :a",
            expr_values={":a": amount},
        )
        send_message(chat_id, f"✅ 金額已更新為：{format_currency(amount)}")

    elif step == "edit_date":
        date_str = parse_date(text)
        if date_str is None:
            send_message(chat_id, "❌ 無法辨識日期格式，請重新輸入。")
            return
        fin_type = data.get("fin_type", "")
        if fin_type == FIN_TYPE_PAYMENT and is_past_date(date_str):
            send_message(chat_id, "❌ 付款到期日不能是過去的日期，請重新輸入。")
            return
        ulid_part = data["sk"].split("#", 1)[1]
        update_item(
            pk=data["pk"],
            sk=data["sk"],
            update_expr="SET #d = :d, GSI1SK = :g1sk, GSI2SK = :g2sk",
            expr_values={
                ":d": date_str,
                ":g1sk": f"{date_str}#{ulid_part}",
                ":g2sk": f"{date_str}#{ulid_part}",
            },
            expr_names={"#d": "date"},
        )
        send_message(chat_id, f"✅ 日期已更新為：{format_date_full(date_str)}")

    elif step == "edit_notes":
        if text.strip() == "無":
            new_notes = ""
        else:
            valid, err = validate_text_length(text, 1, 200)
            if not valid:
                send_message(chat_id, f"❌ {err}")
                return
            new_notes = text.strip()
        update_item(
            pk=data["pk"],
            sk=data["sk"],
            update_expr="SET notes = :n",
            expr_values={":n": new_notes},
        )
        display = escape_markdown(new_notes) if new_notes else "（已清除）"
        send_message(chat_id, f"✅ 備註已更新：{display}")

    else:
        send_message(chat_id, "請點選上方按鈕選擇欄位。")
        return

    # After any text update, return to field picker
    update_conversation(user_id, "choose_field", data)
    item = _reload_fin_item(data)
    if item:
        _ask_edit_fin_field(chat_id, item)