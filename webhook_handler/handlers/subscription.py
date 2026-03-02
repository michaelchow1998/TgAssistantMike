# webhook_handler/handlers/subscription.py
# ============================================================
# 訂閱管理 — /add_sub, /subs, /sub_due, /renew_sub,
#            /pause_sub, /resume_sub, /cancel_sub,
#            /edit_sub, /sub_cost
# ============================================================

import json
import logging
from decimal import Decimal
from datetime import date, timedelta

from boto3.dynamodb.conditions import Key, Attr

from bot_constants import (
    ENTITY_SUB,
    SUB_STATUS_ACTIVE,
    SUB_STATUS_PAUSED,
    SUB_STATUS_CANCELLED,
    SUB_CYCLES,
    SUB_CATEGORIES,
    CONV_MODULE_SUBSCRIPTION,
    CONV_MODULE_RESUME_SUB,
    CONV_MODULE_EDIT_SUB,
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
    parse_day_of_month,
    is_past_date,
    validate_text_length,
    get_now,
    get_today,
    get_today_date,
    format_date_full,
    format_date_short,
    format_currency,
    days_until,
    days_until_display,
    escape_markdown,
)

logger = logging.getLogger(__name__)


# ================================================================
#  Helper — calculate next billing date
# ================================================================

def _calc_next_billing(from_date_str, cycle, billing_day):
    """
    Calculate the next billing date from *from_date_str*.
    Returns YYYY-MM-DD string.
    """
    d = date.fromisoformat(from_date_str)
    months = SUB_CYCLES[cycle]["months"]
    new_month = d.month + months
    new_year = d.year
    while new_month > 12:
        new_month -= 12
        new_year += 1

    from calendar import monthrange
    max_day = monthrange(new_year, new_month)[1]
    day = min(billing_day, max_day)
    return date(new_year, new_month, day).strftime("%Y-%m-%d")


# ================================================================
#  Conversation — /add_sub
# ================================================================

def handle_add_sub(user_id, chat_id):
    set_conversation(user_id, CONV_MODULE_SUBSCRIPTION, "name", {})
    send_message(chat_id, "📦 *新增訂閱*\n\n請輸入訂閱名稱：")


# ----------------------------------------------------------------
#  Text input dispatcher
# ----------------------------------------------------------------

def handle_step(user_id, chat_id, text, step, data):
    module = data.get("_module", CONV_MODULE_SUBSCRIPTION)

    if module == CONV_MODULE_EDIT_SUB:
        _edit_handle_step(user_id, chat_id, text, step, data)
        return

    if module == CONV_MODULE_RESUME_SUB:
        _resume_handle_step(user_id, chat_id, text, step, data)
        return

    # --- add_sub steps ---
    if step == "name":
        _step_name(user_id, chat_id, text, data)
    elif step == "amount":
        _step_amount(user_id, chat_id, text, data)
    elif step == "cycle":
        send_message(chat_id, "請點選上方按鈕選擇週期。")
    elif step == "billing_day":
        _step_billing_day(user_id, chat_id, text, data)
    elif step == "next_billing":
        _step_next_billing(user_id, chat_id, text, data)
    elif step == "category":
        send_message(chat_id, "請點選上方按鈕選擇分類。")
    elif step == "notes":
        _step_notes(user_id, chat_id, text, data)
    elif step == "confirm":
        send_message(chat_id, "請點選上方按鈕確認或取消。")
    else:
        logger.warning(f"Unknown subscription step: {step}")
        send_message(chat_id, "⚠️ 未知的步驟，請輸入 /cancel 重新開始。")


# ----------------------------------------------------------------
#  Callback dispatcher
# ----------------------------------------------------------------

def handle_callback(user_id, chat_id, message_id, callback_data, step, data):
    module = data.get("_module", CONV_MODULE_SUBSCRIPTION)

    if module == CONV_MODULE_EDIT_SUB:
        _edit_handle_callback(user_id, chat_id, message_id, callback_data, step, data)
        return

    if module == CONV_MODULE_RESUME_SUB:
        _resume_handle_callback(user_id, chat_id, message_id, callback_data, step, data)
        return

    # --- add_sub callbacks ---

    # Cycle
    if callback_data.startswith("sub_cycle_"):
        if step != "cycle":
            return
        cycle = callback_data[len("sub_cycle_"):]
        if cycle not in SUB_CYCLES:
            send_message(chat_id, "❌ 無效的週期，請重新選擇。")
            return
        data["cycle"] = cycle
        update_conversation(user_id, "billing_day", data)
        send_message(chat_id, "📅 請輸入帳單日（1-31，例如 `15`）：")

    # Category
    elif callback_data.startswith("sub_cat_"):
        if step != "category":
            return
        category = callback_data[len("sub_cat_"):]
        if category not in SUB_CATEGORIES:
            send_message(chat_id, "❌ 無效的分類，請重新選擇。")
            return
        data["category"] = category
        update_conversation(user_id, "notes", data)
        _ask_notes(chat_id)

    # Notes skip
    elif callback_data == "sub_skip_notes":
        if step != "notes":
            return
        data["notes"] = ""
        update_conversation(user_id, "confirm", data)
        _ask_confirm(chat_id, data)

    # Confirm / Cancel
    elif callback_data == "sub_confirm":
        if step != "confirm":
            return
        _do_save(user_id, chat_id, data)

    elif callback_data == "sub_cancel":
        delete_conversation(user_id)
        send_message(chat_id, "✅ 已取消新增訂閱。")


# ================================================================
#  Add-sub step handlers
# ================================================================

def _step_name(user_id, chat_id, text, data):
    valid, err = validate_text_length(text, 1, 100)
    if not valid:
        send_message(chat_id, f"❌ {err}")
        return
    data["name"] = text.strip()
    update_conversation(user_id, "amount", data)
    send_message(chat_id, "💲 請輸入訂閱金額（例如 `78` 或 `15.90`）：")


def _step_amount(user_id, chat_id, text, data):
    amount = parse_amount(text)
    if amount is None:
        send_message(chat_id, "❌ 金額格式不正確，請輸入正數，最多兩位小數。")
        return
    data["amount"] = str(amount)
    update_conversation(user_id, "cycle", data)
    _ask_cycle(chat_id)


def _step_billing_day(user_id, chat_id, text, data):
    day = parse_day_of_month(text)
    if day is None:
        send_message(chat_id, "❌ 請輸入 1-31 的數字。")
        return
    data["billing_day"] = day
    update_conversation(user_id, "next_billing", data)
    send_message(
        chat_id,
        "📆 請輸入下次扣款日：\n\n"
        "支援格式：\n"
        "• `今天`、`明天`、`後天`\n"
        "• `下週一` ~ `下週日`\n"
        "• `下個月15號`\n"
        "• `2026-03-15` 或 `03/15`",
    )


def _step_next_billing(user_id, chat_id, text, data):
    date_str = parse_date(text)
    if date_str is None:
        send_message(chat_id, "❌ 無法辨識日期格式，請重新輸入。")
        return
    if is_past_date(date_str):
        send_message(chat_id, "❌ 下次扣款日不能是過去的日期。")
        return
    data["next_billing"] = date_str
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
#  Add-sub prompt helpers
# ================================================================

def _ask_cycle(chat_id):
    rows = []
    for key, info in SUB_CYCLES.items():
        rows.append([{
            "text": f"{info['emoji']} {info['display']}",
            "callback_data": f"sub_cycle_{key}",
        }])
    send_message(
        chat_id,
        "🔄 請選擇扣款週期：",
        reply_markup=build_inline_keyboard(rows),
    )


def _ask_category(chat_id):
    rows = []
    row = []
    for key, info in SUB_CATEGORIES.items():
        row.append({
            "text": f"{info['emoji']} {info['display']}",
            "callback_data": f"sub_cat_{key}",
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
        reply_markup=build_skip_keyboard("sub_skip_notes"),
    )


def _ask_confirm(chat_id, data):
    amount = Decimal(data.get("amount", "0"))
    cycle_info = SUB_CYCLES.get(data.get("cycle", "monthly"), {})
    cat_info = SUB_CATEGORIES.get(data.get("category", "other"), {})
    cat_display = f"{cat_info.get('emoji', '')} {cat_info.get('display', '')}"
    notes_display = data.get("notes") or "無"
    nb = data.get("next_billing", "")
    nb_display = format_date_full(nb) if nb else "未設定"

    text = (
        "📋 *確認新增訂閱*\n\n"
        f"📦 名稱：{escape_markdown(data['name'])}\n"
        f"💲 金額：{format_currency(amount)}\n"
        f"🔄 週期：{cycle_info.get('display', '')}\n"
        f"📅 帳單日：每月 {data.get('billing_day', '')} 號\n"
        f"📆 下次扣款：{nb_display}\n"
        f"📁 分類：{cat_display}\n"
        f"📝 備註：{escape_markdown(notes_display)}\n\n"
        "確認新增？"
    )
    send_message(
        chat_id,
        text,
        reply_markup=build_confirm_keyboard("sub_confirm", "sub_cancel"),
    )


# ================================================================
#  Save to DynamoDB
# ================================================================

def _do_save(user_id, chat_id, data):
    owner_id = get_owner_id()
    new_ulid = generate_ulid()
    short_id = get_next_short_id(ENTITY_SUB)
    now = get_now()

    amount = Decimal(data.get("amount", "0"))
    cycle = data.get("cycle", "monthly")
    billing_day = int(data.get("billing_day", 1))
    next_billing = data.get("next_billing", "")
    category = data.get("category", "other")

    item = {
        "PK": f"USER#{owner_id}",
        "SK": f"SUB#{new_ulid}",
        "entity_type": ENTITY_SUB,
        "short_id": short_id,
        "name": data["name"],
        "amount": amount,
        "cycle": cycle,
        "billing_day": billing_day,
        "next_billing": next_billing,
        "category": category,
        "notes": data.get("notes", ""),
        "status": SUB_STATUS_ACTIVE,
        "created_at": now.isoformat(),
        # GSI keys
        "GSI1PK": f"USER#{owner_id}#SUB",
        "GSI1SK": f"{next_billing}#{new_ulid}",
        "GSI2PK": f"USER#{owner_id}#SUB#{category}",
        "GSI2SK": f"{next_billing}#{new_ulid}",
        "GSI3PK": ENTITY_SUB,
        "GSI3SK": format_short_id(short_id),
    }

    put_item(item)
    delete_conversation(user_id)

    nb_display = format_date_full(next_billing) if next_billing else "未設定"
    cycle_display = SUB_CYCLES.get(cycle, {}).get("display", cycle)

    send_message(
        chat_id,
        f"✅ 訂閱已新增！\n\n"
        f"📦 {escape_markdown(data['name'])}\n"
        f"💲 {format_currency(amount)} / {cycle_display}\n"
        f"📆 下次扣款：{nb_display}\n"
        f"🔖 ID: `{short_id}`",
    )

    logger.info(json.dumps({
        "event_type": "sub_created",
        "short_id": short_id,
        "amount": str(amount),
        "cycle": cycle,
    }))


# ================================================================
#  /subs — 查看訂閱
# ================================================================

def handle_subs(user_id, chat_id):
    owner_id = get_owner_id()

    items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#SUB",
        filter_expr=Attr("status").ne(SUB_STATUS_CANCELLED),
    )

    if not items:
        send_message(chat_id, "📦 *訂閱列表*\n\n目前沒有訂閱 🎉")
        return

    active = [i for i in items if i.get("status") == SUB_STATUS_ACTIVE]
    paused = [i for i in items if i.get("status") == SUB_STATUS_PAUSED]

    active.sort(key=lambda x: x.get("next_billing", "9999-12-31"))
    paused.sort(key=lambda x: x.get("name", ""))

    total_monthly = _calc_monthly_cost(active)

    lines = [
        f"📦 *訂閱列表*（{len(active)} 個啟用 / {len(paused)} 個暫停）\n"
        f"💲 每月估算：{format_currency(total_monthly)}\n"
    ]

    if active:
        lines.append("✅ *啟用中*")
        for item in active:
            _append_sub_item(lines, item)
        lines.append("")

    if paused:
        lines.append("⏸️ *已暫停*")
        for item in paused:
            _append_sub_item(lines, item, show_next=False)

    send_message(chat_id, "\n".join(lines))


def _append_sub_item(lines, item, show_next=True):
    amount = Decimal(str(item.get("amount", 0)))
    cycle = item.get("cycle", "monthly")
    cycle_display = SUB_CYCLES.get(cycle, {}).get("display", cycle)
    cat_info = SUB_CATEGORIES.get(item.get("category", "other"), {})
    cat_emoji = cat_info.get("emoji", "📦")

    nb = item.get("next_billing", "")
    if show_next and nb:
        nb_rel = days_until_display(nb)
        nb_text = f"📆 {format_date_short(nb)}（{nb_rel}）"
    elif show_next:
        nb_text = "📆 未設定"
    else:
        nb_text = ""

    line = (
        f"  {cat_emoji} *{escape_markdown(item.get('name', ''))}*\n"
        f"    💲 {format_currency(amount)} / {cycle_display}"
    )
    if nb_text:
        line += f"  {nb_text}"
    line += f"  `{item.get('short_id', '')}`"
    lines.append(line)


def _calc_monthly_cost(items):
    """Estimate total monthly cost from active subscriptions."""
    total = Decimal("0")
    for item in items:
        amount = Decimal(str(item.get("amount", 0)))
        cycle = item.get("cycle", "monthly")
        months = SUB_CYCLES.get(cycle, {}).get("months", 1)
        total += amount / months
    return total.quantize(Decimal("0.01"))


# ================================================================
#  /sub_due — 即將到期訂閱（7 天內）
# ================================================================

def handle_sub_due(user_id, chat_id):
    owner_id = get_owner_id()
    today = get_today()
    today_date = get_today_date()
    end_date = today_date + timedelta(days=7)
    end_str = end_date.strftime("%Y-%m-%d")

    items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#SUB",
        sk_condition=Key("GSI1SK").between(f"{today}#", f"{end_str}#~"),
        filter_expr=Attr("status").eq(SUB_STATUS_ACTIVE),
    )

    if not items:
        send_message(
            chat_id,
            "📦 *即將到期訂閱*（7 天內）\n\n沒有即將到期的訂閱 🎉",
        )
        return

    items.sort(key=lambda x: x.get("next_billing", ""))

    total = sum(Decimal(str(i.get("amount", 0))) for i in items)

    lines = [
        f"📦 *即將到期訂閱*（7 天內，共 {len(items)} 筆）\n"
        f"💲 合計：{format_currency(total)}\n"
    ]

    for item in items:
        amount = Decimal(str(item.get("amount", 0)))
        nb = item.get("next_billing", "")
        nb_rel = days_until_display(nb)
        cat_info = SUB_CATEGORIES.get(item.get("category", "other"), {})
        cat_emoji = cat_info.get("emoji", "📦")

        lines.append(
            f"  {cat_emoji} *{escape_markdown(item.get('name', ''))}*\n"
            f"    💲 {format_currency(amount)}  📆 {format_date_short(nb)}（{nb_rel}）\n"
            f"    🔖 `{item.get('short_id', '')}`"
        )

    send_message(chat_id, "\n".join(lines))


# ================================================================
#  /renew_sub ID — 手動續訂
# ================================================================

def handle_renew_sub(user_id, chat_id, args):
    sid = parse_short_id(args)
    if sid is None:
        send_message(chat_id, "❌ 請提供訂閱 ID，例如：`/renew_sub 3`")
        return

    item = query_gsi3(ENTITY_SUB, sid)
    if item is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{sid}` 的訂閱。")
        return

    if item.get("status") != SUB_STATUS_ACTIVE:
        send_message(chat_id, f"⚠️ 訂閱 `{sid}` 目前不是啟用狀態，無法續訂。")
        return

    cycle = item.get("cycle", "monthly")
    billing_day = int(item.get("billing_day", 1))
    current_nb = item.get("next_billing", get_today())

    new_nb = _calc_next_billing(current_nb, cycle, billing_day)

    # Update next_billing + GSI1SK
    new_ulid = item["SK"].split("#", 1)[1]  # keep original ULID
    update_item(
        pk=item["PK"],
        sk=item["SK"],
        update_expr="SET next_billing = :nb, GSI1SK = :g1sk",
        expr_values={
            ":nb": new_nb,
            ":g1sk": f"{new_nb}#{new_ulid}",
        },
    )

    cycle_display = SUB_CYCLES.get(cycle, {}).get("display", cycle)
    send_message(
        chat_id,
        f"🔄 已續訂！\n\n"
        f"📦 {escape_markdown(item.get('name', ''))}\n"
        f"📆 下次扣款：{format_date_full(new_nb)}\n"
        f"🔖 ID: `{sid}`",
    )

    logger.info(json.dumps({
        "event_type": "sub_renewed",
        "short_id": sid,
        "new_next_billing": new_nb,
    }))


# ================================================================
#  /pause_sub ID — 暫停訂閱
# ================================================================

def handle_pause_sub(user_id, chat_id, args):
    sid = parse_short_id(args)
    if sid is None:
        send_message(chat_id, "❌ 請提供訂閱 ID，例如：`/pause_sub 3`")
        return

    item = query_gsi3(ENTITY_SUB, sid)
    if item is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{sid}` 的訂閱。")
        return

    if item.get("status") == SUB_STATUS_PAUSED:
        send_message(chat_id, f"⚠️ 訂閱 `{sid}` 已經是暫停狀態。")
        return
    if item.get("status") == SUB_STATUS_CANCELLED:
        send_message(chat_id, f"⚠️ 訂閱 `{sid}` 已被取消。")
        return

    update_item(
        pk=item["PK"],
        sk=item["SK"],
        update_expr="SET #st = :s",
        expr_values={":s": SUB_STATUS_PAUSED},
        expr_names={"#st": "status"},
    )

    send_message(
        chat_id,
        f"⏸️ 已暫停訂閱：\n\n"
        f"📦 {escape_markdown(item.get('name', ''))}\n"
        f"🔖 ID: `{sid}`\n\n"
        f"恢復訂閱：`/resume_sub {sid}`",
    )

    logger.info(json.dumps({"event_type": "sub_paused", "short_id": sid}))


# ================================================================
#  /resume_sub ID — 恢復訂閱（需輸入新的下次扣款日）
# ================================================================

def handle_resume_sub(user_id, chat_id, args):
    sid = parse_short_id(args)
    if sid is None:
        send_message(chat_id, "❌ 請提供訂閱 ID，例如：`/resume_sub 3`")
        return

    item = query_gsi3(ENTITY_SUB, sid)
    if item is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{sid}` 的訂閱。")
        return

    if item.get("status") != SUB_STATUS_PAUSED:
        send_message(chat_id, f"⚠️ 訂閱 `{sid}` 不是暫停狀態。")
        return

    # Start resume conversation
    conv_data = {
        "_module": CONV_MODULE_RESUME_SUB,
        "pk": item["PK"],
        "sk": item["SK"],
        "short_id": sid,
        "name": item.get("name", ""),
    }
    set_conversation(user_id, CONV_MODULE_RESUME_SUB, "next_billing", conv_data)
    send_message(
        chat_id,
        f"▶️ *恢復訂閱：{escape_markdown(item.get('name', ''))}*\n\n"
        "請輸入新的下次扣款日：",
    )


def _resume_handle_step(user_id, chat_id, text, step, data):
    if step == "next_billing":
        date_str = parse_date(text)
        if date_str is None:
            send_message(chat_id, "❌ 無法辨識日期格式，請重新輸入。")
            return
        if is_past_date(date_str):
            send_message(chat_id, "❌ 不能選擇過去的日期。")
            return

        new_ulid = data["sk"].split("#", 1)[1]
        update_item(
            pk=data["pk"],
            sk=data["sk"],
            update_expr="SET #st = :s, next_billing = :nb, GSI1SK = :g1sk",
            expr_values={
                ":s": SUB_STATUS_ACTIVE,
                ":nb": date_str,
                ":g1sk": f"{date_str}#{new_ulid}",
            },
            expr_names={"#st": "status"},
        )

        delete_conversation(user_id)
        send_message(
            chat_id,
            f"▶️ 已恢復訂閱！\n\n"
            f"📦 {escape_markdown(data.get('name', ''))}\n"
            f"📆 下次扣款：{format_date_full(date_str)}\n"
            f"🔖 ID: `{data.get('short_id', '')}`",
        )

        logger.info(json.dumps({
            "event_type": "sub_resumed",
            "short_id": data.get("short_id"),
        }))
    else:
        send_message(chat_id, "⚠️ 未知的步驟，請輸入 /cancel 重新開始。")


def _resume_handle_callback(user_id, chat_id, message_id, callback_data, step, data):
    # No callbacks in resume flow
    pass


# ================================================================
#  /cancel_sub ID — 取消訂閱（帶確認按鈕）
# ================================================================

def handle_cancel_sub(user_id, chat_id, args):
    sid = parse_short_id(args)
    if sid is None:
        send_message(chat_id, "❌ 請提供訂閱 ID，例如：`/cancel_sub 3`")
        return

    item = query_gsi3(ENTITY_SUB, sid)
    if item is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{sid}` 的訂閱。")
        return

    if item.get("status") == SUB_STATUS_CANCELLED:
        send_message(chat_id, f"⚠️ 訂閱 `{sid}` 已經被取消。")
        return

    amount = Decimal(str(item.get("amount", 0)))
    send_message(
        chat_id,
        f"⚠️ *確認取消訂閱？*\n\n"
        f"📦 {escape_markdown(item.get('name', ''))}\n"
        f"💲 {format_currency(amount)}\n"
        f"🔖 ID: `{sid}`\n\n"
        f"取消後無法恢復。",
        reply_markup=build_inline_keyboard([[
            {"text": "✅ 確認取消", "callback_data": f"cancelsub_yes_{sid}"},
            {"text": "❌ 保留", "callback_data": f"cancelsub_no_{sid}"},
        ]]),
    )


# ================================================================
#  /edit_sub ID — 編輯訂閱（對話式選擇欄位）
# ================================================================

def handle_edit_sub(user_id, chat_id, args):
    sid = parse_short_id(args)
    if sid is None:
        send_message(chat_id, "❌ 請提供訂閱 ID，例如：`/edit_sub 3`")
        return

    item = query_gsi3(ENTITY_SUB, sid)
    if item is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{sid}` 的訂閱。")
        return

    if item.get("status") == SUB_STATUS_CANCELLED:
        send_message(chat_id, f"⚠️ 訂閱 `{sid}` 已被取消，無法編輯。")
        return

    conv_data = {
        "_module": CONV_MODULE_EDIT_SUB,
        "pk": item["PK"],
        "sk": item["SK"],
        "short_id": sid,
        "name": item.get("name", ""),
    }
    set_conversation(user_id, CONV_MODULE_EDIT_SUB, "choose_field", conv_data)
    _ask_edit_field(chat_id, item)


def _ask_edit_field(chat_id, item):
    amount = Decimal(str(item.get("amount", 0)))
    cycle_display = SUB_CYCLES.get(item.get("cycle", "monthly"), {}).get("display", "")
    nb = item.get("next_billing", "")
    nb_display = format_date_full(nb) if nb else "未設定"

    text = (
        f"✏️ *編輯訂閱：{escape_markdown(item.get('name', ''))}*\n\n"
        f"1️⃣ 名稱：{escape_markdown(item.get('name', ''))}\n"
        f"2️⃣ 金額：{format_currency(amount)}\n"
        f"3️⃣ 週期：{cycle_display}\n"
        f"4️⃣ 帳單日：{item.get('billing_day', '')} 號\n"
        f"5️⃣ 下次扣款：{nb_display}\n\n"
        "請選擇要編輯的欄位："
    )
    rows = [
        [
            {"text": "1️⃣ 名稱", "callback_data": "edit_field_name"},
            {"text": "2️⃣ 金額", "callback_data": "edit_field_amount"},
        ],
        [
            {"text": "3️⃣ 週期", "callback_data": "edit_field_cycle"},
            {"text": "4️⃣ 帳單日", "callback_data": "edit_field_billing_day"},
        ],
        [
            {"text": "5️⃣ 下次扣款", "callback_data": "edit_field_next_billing"},
        ],
        [
            {"text": "✅ 完成編輯", "callback_data": "edit_done"},
        ],
    ]
    send_message(chat_id, text, reply_markup=build_inline_keyboard(rows))


def _edit_handle_callback(user_id, chat_id, message_id, callback_data, step, data):
    if step == "choose_field":
        if callback_data == "edit_done":
            delete_conversation(user_id)
            send_message(chat_id, "✅ 編輯完成。")
            return

        field_map = {
            "edit_field_name": ("edit_name", "請輸入新的名稱："),
            "edit_field_amount": ("edit_amount", "請輸入新的金額："),
            "edit_field_cycle": ("edit_cycle", None),
            "edit_field_billing_day": ("edit_billing_day", "請輸入新的帳單日（1-31）："),
            "edit_field_next_billing": ("edit_next_billing", "請輸入新的下次扣款日："),
        }

        if callback_data not in field_map:
            return

        new_step, prompt = field_map[callback_data]
        update_conversation(user_id, new_step, data)

        if callback_data == "edit_field_cycle":
            _ask_cycle(chat_id)
        else:
            send_message(chat_id, f"✏️ {prompt}")

    elif step == "edit_cycle":
        if not callback_data.startswith("sub_cycle_"):
            return
        cycle = callback_data[len("sub_cycle_"):]
        if cycle not in SUB_CYCLES:
            send_message(chat_id, "❌ 無效的週期。")
            return

        update_item(
            pk=data["pk"],
            sk=data["sk"],
            update_expr="SET #c = :c",
            expr_values={":c": cycle},
            expr_names={"#c": "cycle"},
        )

        cycle_display = SUB_CYCLES[cycle]["display"]
        send_message(chat_id, f"✅ 週期已更新為：{cycle_display}")

        # Return to field selection
        update_conversation(user_id, "choose_field", data)
        item = _reload_item(data)
        if item:
            _ask_edit_field(chat_id, item)


def _edit_handle_step(user_id, chat_id, text, step, data):
    if step == "edit_name":
        valid, err = validate_text_length(text, 1, 100)
        if not valid:
            send_message(chat_id, f"❌ {err}")
            return
        new_name = text.strip()
        update_item(
            pk=data["pk"],
            sk=data["sk"],
            update_expr="SET #n = :n",
            expr_values={":n": new_name},
            expr_names={"#n": "name"},
        )
        data["name"] = new_name
        send_message(chat_id, f"✅ 名稱已更新為：{escape_markdown(new_name)}")

    elif step == "edit_amount":
        amount = parse_amount(text)
        if amount is None:
            send_message(chat_id, "❌ 金額格式不正確。")
            return
        update_item(
            pk=data["pk"],
            sk=data["sk"],
            update_expr="SET amount = :a",
            expr_values={":a": amount},
        )
        send_message(chat_id, f"✅ 金額已更新為：{format_currency(amount)}")

    elif step == "edit_billing_day":
        day = parse_day_of_month(text)
        if day is None:
            send_message(chat_id, "❌ 請輸入 1-31 的數字。")
            return
        update_item(
            pk=data["pk"],
            sk=data["sk"],
            update_expr="SET billing_day = :d",
            expr_values={":d": day},
        )
        send_message(chat_id, f"✅ 帳單日已更新為：每月 {day} 號")

    elif step == "edit_next_billing":
        date_str = parse_date(text)
        if date_str is None:
            send_message(chat_id, "❌ 無法辨識日期格式。")
            return
        if is_past_date(date_str):
            send_message(chat_id, "❌ 不能選擇過去的日期。")
            return

        new_ulid = data["sk"].split("#", 1)[1]
        update_item(
            pk=data["pk"],
            sk=data["sk"],
            update_expr="SET next_billing = :nb, GSI1SK = :g1sk",
            expr_values={
                ":nb": date_str,
                ":g1sk": f"{date_str}#{new_ulid}",
            },
        )
        send_message(chat_id, f"✅ 下次扣款日已更新為：{format_date_full(date_str)}")

    else:
        send_message(chat_id, "⚠️ 未知步驟，請輸入 /cancel 取消。")
        return

    # Return to field selection
    update_conversation(user_id, "choose_field", data)
    item = _reload_item(data)
    if item:
        _ask_edit_field(chat_id, item)


def _reload_item(data):
    """Reload the subscription item from DB (after an edit)."""
    from bot_db import get_item
    return get_item(data["pk"], data["sk"])


# ================================================================
#  /sub_cost — 費用統計
# ================================================================

def handle_sub_cost(user_id, chat_id):
    owner_id = get_owner_id()

    items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#SUB",
        filter_expr=Attr("status").eq(SUB_STATUS_ACTIVE),
    )

    if not items:
        send_message(chat_id, "💲 *訂閱費用統計*\n\n目前沒有啟用中的訂閱。")
        return

    # Group by category
    by_cat = {}
    for item in items:
        cat = item.get("category", "other")
        amount = Decimal(str(item.get("amount", 0)))
        cycle = item.get("cycle", "monthly")
        months = SUB_CYCLES.get(cycle, {}).get("months", 1)
        monthly = (amount / months).quantize(Decimal("0.01"))
        by_cat.setdefault(cat, []).append({
            "name": item.get("name", ""),
            "amount": amount,
            "monthly": monthly,
            "cycle": cycle,
            "short_id": item.get("short_id", ""),
        })

    # Calculate totals
    total_monthly = sum(
        s["monthly"] for subs in by_cat.values() for s in subs
    )
    total_yearly = (total_monthly * 12).quantize(Decimal("0.01"))

    lines = [
        f"💲 *訂閱費用統計*（{len(items)} 個啟用中）\n",
        f"📅 每月估算：{format_currency(total_monthly)}",
        f"📅 每年估算：{format_currency(total_yearly)}",
        "",
    ]

    sorted_cats = sorted(by_cat.items(), key=lambda x: sum(s["monthly"] for s in x[1]), reverse=True)

    for cat, subs in sorted_cats:
        cat_info = SUB_CATEGORIES.get(cat, {})
        emoji = cat_info.get("emoji", "📦")
        display = cat_info.get("display", cat)
        cat_monthly = sum(s["monthly"] for s in subs)
        pct = (cat_monthly / total_monthly * 100) if total_monthly > 0 else Decimal("0")

        lines.append(f"{emoji} *{display}*（{format_currency(cat_monthly)}/月，{pct:.0f}%）")

        subs.sort(key=lambda x: x["monthly"], reverse=True)
        for s in subs:
            cycle_display = SUB_CYCLES.get(s["cycle"], {}).get("display", "")
            lines.append(
                f"    {escape_markdown(s['name'])}："
                f"{format_currency(s['amount'])}/{cycle_display}"
                f"  `{s['short_id']}`"
            )

    send_message(chat_id, "\n".join(lines))


# ================================================================
#  Standalone callback handler (cancel_sub confirmation)
# ================================================================

def handle_standalone_callback(user_id, chat_id, message_id, callback_data):
    """
    Handle cancel_sub confirmation callbacks.
    Called from router._handle_standalone_callback.
    Returns True if handled, False otherwise.
    """
    if callback_data.startswith("cancelsub_yes_"):
        sid_str = callback_data[len("cancelsub_yes_"):]
        sid = parse_short_id(sid_str)
        if sid is None:
            return True

        item = query_gsi3(ENTITY_SUB, sid)
        if item is None:
            send_message(chat_id, f"❌ 找不到 ID 為 `{sid}` 的訂閱。")
            return True

        if item.get("status") == SUB_STATUS_CANCELLED:
            send_message(chat_id, f"⚠️ 訂閱 `{sid}` 已經被取消。")
            return True

        now = get_now()
        update_item(
            pk=item["PK"],
            sk=item["SK"],
            update_expr="SET #st = :s, cancelled_at = :c",
            expr_values={
                ":s": SUB_STATUS_CANCELLED,
                ":c": now.isoformat(),
            },
            expr_names={"#st": "status"},
        )

        edit_message_text(
            chat_id,
            message_id,
            f"🗑️ 已取消訂閱：\n\n"
            f"📦 {escape_markdown(item.get('name', ''))}\n"
            f"🔖 ID: `{sid}`",
        )

        logger.info(json.dumps({"event_type": "sub_cancelled", "short_id": sid}))
        return True

    elif callback_data.startswith("cancelsub_no_"):
        edit_message_text(chat_id, message_id, "✅ 已保留訂閱。")
        return True

    return False