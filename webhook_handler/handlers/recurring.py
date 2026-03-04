# webhook_handler/handlers/recurring.py
# ============================================================
# 週期財務模板管理 — /add_recurring, /recurring, /edit_recurring,
#                   /del_recurring, /pause_recurring, /resume_recurring
# ============================================================

import json
import logging
from decimal import Decimal

from boto3.dynamodb.conditions import Key

from bot_constants import (
    ENTITY_FIN_RECURRING,
    ENTITY_FIN,
    FIN_RECURRING_STATUS_ACTIVE,
    FIN_RECURRING_STATUS_PAUSED,
    FIN_RECURRING_STATUS_COMPLETED,
    FIN_CATEGORIES,
    FIN_TYPE_INCOME,
    FIN_TYPE_EXPENSE,
    CONV_MODULE_ADD_RECURRING,
    CONV_MODULE_EDIT_RECURRING,
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
    delete_item,
)
from bot_utils import (
    generate_ulid,
    format_short_id,
    parse_amount,
    parse_short_id,
    validate_text_length,
    get_today,
    format_currency,
    escape_markdown,
)

logger = logging.getLogger(__name__)

_FIN_TYPE_DISPLAY = {
    FIN_TYPE_INCOME:  {"label": "收入", "emoji": "💵"},
    FIN_TYPE_EXPENSE: {"label": "支出", "emoji": "💸"},
}


# ================================================================
#  /recurring — list templates
# ================================================================

def handle_recurring(user_id, chat_id):
    owner_id = get_owner_id()
    gsi1pk = f"USER#{owner_id}#FIN_RECURRING"

    active_items = query_gsi1(
        gsi1pk=gsi1pk,
        sk_condition=Key("GSI1SK").begins_with(f"{FIN_RECURRING_STATUS_ACTIVE}#"),
    )
    paused_items = query_gsi1(
        gsi1pk=gsi1pk,
        sk_condition=Key("GSI1SK").begins_with(f"{FIN_RECURRING_STATUS_PAUSED}#"),
    )

    all_items = active_items + paused_items

    if not all_items:
        send_message(
            chat_id,
            "🔄 *週期財務模板*\n\n尚無任何週期模板。\n\n使用 /add\\_recurring 新增。",
        )
        return

    lines = [f"🔄 *週期財務模板*（共 {len(all_items)} 個）\n"]

    if active_items:
        lines.append(f"✅ *啟用中（{len(active_items)}）*")
        for item in active_items:
            lines.append(_format_template_line(item))

    if paused_items:
        lines.append(f"\n⏸ *已暫停（{len(paused_items)}）*")
        for item in paused_items:
            lines.append(_format_template_line(item))

    lines.append(
        "\n管理：`/edit_recurring ID` ∣ `/del_recurring ID`\n"
        "`/pause_recurring ID` ∣ `/resume_recurring ID`"
    )
    send_message(chat_id, "\n".join(lines))


def _format_template_line(item):
    fin_type = item.get("fin_type", "")
    type_info = _FIN_TYPE_DISPLAY.get(fin_type, {})
    emoji = type_info.get("emoji", "💰")
    amount = Decimal(str(item.get("amount", 0)))
    day = item.get("day_of_month", "?")
    cat_info = FIN_CATEGORIES.get(item.get("category", "other"), {})
    cat_display = cat_info.get("display", "")
    end_month = item.get("end_month")
    end_s = f" 至 {end_month}" if end_month else ""
    return (
        f"  {emoji} *{escape_markdown(item.get('title', ''))}*\n"
        f"    {format_currency(amount)} 每月 {day} 日  {cat_display}{end_s}\n"
        f"    🔖 `{item.get('short_id', '')}`"
    )


# ================================================================
#  Helper — find template by short_id
# ================================================================

def _find_template(owner_id, short_id_str):
    sid = parse_short_id(short_id_str)
    if sid is None:
        return None
    return query_gsi3(ENTITY_FIN_RECURRING, sid)


# ================================================================
#  Helper — update template status (also updates GSI1SK)
# ================================================================

def _update_template_status(template, new_status):
    pk = template["PK"]
    sk = template["SK"]
    ulid = sk.split("#", 1)[1]
    new_gsi1sk = f"{new_status}#{ulid}"
    update_item(
        pk=pk,
        sk=sk,
        update_expr="SET #st = :s, GSI1SK = :g1sk",
        expr_values={
            ":s": new_status,
            ":g1sk": new_gsi1sk,
        },
        expr_names={"#st": "status"},
    )


# ================================================================
#  /del_recurring ID
# ================================================================

def handle_del_recurring(user_id, chat_id, args):
    if not args or not args.strip():
        send_message(chat_id, "❌ 請提供模板 ID，例如：`/del_recurring 3`")
        return

    owner_id = get_owner_id()
    template = _find_template(owner_id, args.strip())
    if template is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{args.strip()}` 的週期模板。")
        return

    delete_item(template["PK"], template["SK"])
    send_message(
        chat_id,
        f"🗑️ 已刪除週期模板：*{escape_markdown(template.get('title', ''))}*\n"
        f"🔖 ID: `{template.get('short_id', '')}`",
    )
    logger.info(json.dumps({
        "event_type": "recurring_deleted",
        "short_id": template.get("short_id"),
    }))


# ================================================================
#  /pause_recurring ID
# ================================================================

def handle_pause_recurring(user_id, chat_id, args):
    if not args or not args.strip():
        send_message(chat_id, "❌ 請提供模板 ID，例如：`/pause_recurring 3`")
        return

    owner_id = get_owner_id()
    template = _find_template(owner_id, args.strip())
    if template is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{args.strip()}` 的週期模板。")
        return

    if template.get("status") == FIN_RECURRING_STATUS_PAUSED:
        send_message(chat_id, f"⚠️ 模板 `{template.get('short_id')}` 已經是暫停狀態。")
        return

    _update_template_status(template, FIN_RECURRING_STATUS_PAUSED)
    send_message(
        chat_id,
        f"⏸ 已暫停週期模板：*{escape_markdown(template.get('title', ''))}*\n"
        f"🔖 ID: `{template.get('short_id', '')}`",
    )


# ================================================================
#  /resume_recurring ID
# ================================================================

def handle_resume_recurring(user_id, chat_id, args):
    if not args or not args.strip():
        send_message(chat_id, "❌ 請提供模板 ID，例如：`/resume_recurring 3`")
        return

    owner_id = get_owner_id()
    template = _find_template(owner_id, args.strip())
    if template is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{args.strip()}` 的週期模板。")
        return

    if template.get("status") == FIN_RECURRING_STATUS_ACTIVE:
        send_message(chat_id, f"⚠️ 模板 `{template.get('short_id')}` 已經是啟用狀態。")
        return

    _update_template_status(template, FIN_RECURRING_STATUS_ACTIVE)
    send_message(
        chat_id,
        f"✅ 已恢復週期模板：*{escape_markdown(template.get('title', ''))}*\n"
        f"🔖 ID: `{template.get('short_id', '')}`",
    )


# ================================================================
#  /add_recurring — starts conversation
# ================================================================

def handle_add_recurring(user_id, chat_id):
    owner_id = get_owner_id()
    set_conversation(user_id, CONV_MODULE_ADD_RECURRING, 1, {})
    send_message(
        chat_id,
        "🔄 *新增週期財務模板*\n\n"
        "1️⃣ 請輸入模板標題：",
    )


# ================================================================
#  Conversation dispatcher
# ================================================================

def handle_step(user_id, chat_id, text, step, data):
    if data.get("_module") == CONV_MODULE_EDIT_RECURRING:
        _edit_recurring_step(user_id, chat_id, text, step, data)
    else:
        _add_recurring_step(user_id, chat_id, text, step, data)


# ================================================================
#  Add recurring — steps
# ================================================================

def _add_recurring_step(user_id, chat_id, text, step, data):
    if step == 1:
        # Title
        valid, err = validate_text_length(text, 1, 100)
        if not valid:
            send_message(chat_id, f"❌ {err}")
            return
        data["title"] = text.strip()
        update_conversation(user_id, 2, data)
        send_message(chat_id, "2️⃣ 請輸入每月金額（例如 `20000` 或 `299.50`）：")

    elif step == 2:
        # Amount
        amount = parse_amount(text)
        if amount is None:
            send_message(
                chat_id,
                "❌ 金額格式不正確。\n請輸入正數，最多兩位小數，例如 `20000`。",
            )
            return
        data["amount"] = str(amount)
        update_conversation(user_id, 3, data)
        _ask_fin_type(chat_id)

    elif step == 3:
        send_message(chat_id, "請點選上方按鈕選擇類型。")

    elif step == 4:
        # Day of month
        try:
            day = int(text.strip())
            if not (1 <= day <= 28):
                raise ValueError
        except ValueError:
            send_message(chat_id, "❌ 請輸入 1–28 的整數（每月幾號自動生成記錄）。")
            return
        data["day_of_month"] = day
        update_conversation(user_id, 5, data)
        _ask_category(chat_id)

    elif step == 5:
        send_message(chat_id, "請點選上方按鈕選擇分類。")

    elif step == 6:
        # End month (optional)
        t = text.strip()
        if t in ("跳過", "skip", ""):
            data["end_month"] = None
        else:
            import re
            m = re.match(r"^(\d{4}-(?:0[1-9]|1[0-2]))$", t)
            if not m:
                send_message(chat_id, "❌ 格式錯誤，請使用 `YYYY-MM`，或輸入「跳過」略過。")
                return
            data["end_month"] = t
        update_conversation(user_id, 7, data)
        send_message(
            chat_id,
            "7️⃣ 請輸入備註（選填），或輸入「跳過」略過：",
            reply_markup=build_skip_keyboard("rec_skip_notes"),
        )

    elif step == 7:
        # Notes (optional)
        t = text.strip()
        if t in ("跳過", "skip", ""):
            data["notes"] = None
        else:
            valid, err = validate_text_length(t, 1, 200)
            if not valid:
                send_message(chat_id, f"❌ {err}")
                return
            data["notes"] = t
        update_conversation(user_id, 8, data)
        _show_add_confirm(chat_id, data)

    elif step == 8:
        send_message(chat_id, "請點選上方按鈕確認或取消。")

    else:
        logger.warning(f"Unknown add_recurring step: {step}")
        send_message(chat_id, "⚠️ 未知的步驟，請輸入 /cancel 重新開始。")


# ================================================================
#  Callback dispatcher
# ================================================================

def handle_callback(user_id, chat_id, message_id, callback_data, step, data):
    # fin type selection
    if callback_data.startswith("rec_type_"):
        if step != 3:
            return
        fin_type = callback_data[len("rec_type_"):]
        if fin_type not in (FIN_TYPE_INCOME, FIN_TYPE_EXPENSE):
            send_message(chat_id, "❌ 無效的類型，請重新選擇。")
            return
        data["fin_type"] = fin_type
        update_conversation(user_id, 4, data)
        send_message(chat_id, "4️⃣ 請輸入每月幾號自動生成記錄（1–28）：")

    # category selection
    elif callback_data.startswith("rec_cat_"):
        if step != 5:
            return
        category = callback_data[len("rec_cat_"):]
        if category not in FIN_CATEGORIES:
            send_message(chat_id, "❌ 無效的分類，請重新選擇。")
            return
        data["category"] = category
        update_conversation(user_id, 6, data)
        send_message(
            chat_id,
            "6️⃣ 請輸入結束月份（YYYY-MM），到期後不再生成記錄；或輸入「跳過」設為永久：",
            reply_markup=build_skip_keyboard("rec_skip_end_month", "⏭ 永久"),
        )

    # skip title (edit mode)
    elif callback_data == "rec_skip_title":
        if step != 1:
            return
        update_conversation(user_id, 2, data)
        current_amount = format_currency(Decimal(str(data.get("amount", "0"))))
        send_message(
            chat_id,
            f"2️⃣ 請輸入新金額，或輸入「跳過」保留現有值（{current_amount}）：",
            reply_markup=build_skip_keyboard("rec_skip_amount", f"⏭ 保留：{current_amount}"),
        )

    # skip amount (edit mode)
    elif callback_data == "rec_skip_amount":
        if step != 2:
            return
        update_conversation(user_id, 3, data)
        if data.get("_module") == CONV_MODULE_EDIT_RECURRING:
            _ask_fin_type_skip(chat_id, data.get("fin_type", ""))
        else:
            _ask_fin_type(chat_id)

    # skip type (edit mode)
    elif callback_data == "rec_skip_type":
        if step != 3:
            return
        update_conversation(user_id, 4, data)
        send_message(chat_id, "4️⃣ 請輸入每月幾號自動生成記錄（1–28），或輸入「跳過」保留現有值：")

    # skip category (edit mode)
    elif callback_data == "rec_skip_cat":
        if step != 5:
            return
        update_conversation(user_id, 6, data)
        current_end = data.get("end_month") or "永久"
        send_message(
            chat_id,
            f"6️⃣ 請輸入結束月份（YYYY-MM），或輸入「跳過」保留現有值（{current_end}）：",
            reply_markup=build_skip_keyboard("rec_skip_end_month", f"⏭ 保留：{current_end}"),
        )

    # skip end month
    elif callback_data == "rec_skip_end_month":
        if step != 6:
            return
        update_conversation(user_id, 7, data)
        current_notes = data.get("notes") or "無"
        send_message(
            chat_id,
            f"7️⃣ 請輸入備註（選填），或點選跳過：",
            reply_markup=build_skip_keyboard("rec_skip_notes"),
        )

    # skip notes
    elif callback_data == "rec_skip_notes":
        if step != 7:
            return
        data["notes"] = None
        update_conversation(user_id, 8, data)
        _show_add_confirm(chat_id, data)

    # confirm
    elif callback_data == "rec_confirm":
        if step != 8:
            return
        owner_id = get_owner_id()
        if data.get("_module") == CONV_MODULE_EDIT_RECURRING:
            _apply_edit_recurring(owner_id, user_id, data)
            delete_conversation(user_id)
            send_message(chat_id, "✅ 週期模板已更新！")
        else:
            _save_recurring_template(owner_id, data)
            delete_conversation(user_id)
            send_message(chat_id, "✅ 週期財務模板已新增！每月將自動生成對應記錄。")

    # cancel
    elif callback_data == "rec_cancel":
        delete_conversation(user_id)
        send_message(chat_id, "✅ 已取消操作。")


# ================================================================
#  Prompt helpers
# ================================================================

def _ask_fin_type(chat_id):
    rows = [
        [
            {"text": "💵 收入", "callback_data": "rec_type_income"},
            {"text": "💸 支出", "callback_data": "rec_type_expense"},
        ],
    ]
    send_message(
        chat_id,
        "3️⃣ 請選擇類型：\n💵 收入 / 💸 支出",
        reply_markup=build_inline_keyboard(rows),
    )


def _ask_category(chat_id):
    rows = []
    row = []
    for key, info in FIN_CATEGORIES.items():
        row.append({
            "text": f"{info['emoji']} {info['display']}",
            "callback_data": f"rec_cat_{key}",
        })
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    send_message(
        chat_id,
        "5️⃣ 請選擇分類：",
        reply_markup=build_inline_keyboard(rows),
    )


def _show_add_confirm(chat_id, data):
    fin_type = data.get("fin_type", "")
    type_info = _FIN_TYPE_DISPLAY.get(fin_type, {})
    type_label = type_info.get("label", "")
    type_emoji = type_info.get("emoji", "💰")

    amount = Decimal(data.get("amount", "0"))
    cat_info = FIN_CATEGORIES.get(data.get("category", "other"), {})
    cat_display = f"{cat_info.get('emoji', '')} {cat_info.get('display', '')}"
    day = data.get("day_of_month", "?")
    end_month = data.get("end_month") or "永久"
    notes = data.get("notes") or "無"

    text = (
        f"📋 *確認新增週期模板*\n\n"
        f"{type_emoji} 類型：{type_label}\n"
        f"📌 標題：{escape_markdown(data.get('title', ''))}\n"
        f"💲 金額：{format_currency(amount)}\n"
        f"📅 每月幾號：{day} 日\n"
        f"📁 分類：{cat_display}\n"
        f"🏁 結束月份：{end_month}\n"
        f"📝 備註：{escape_markdown(str(notes))}\n\n"
        "確認新增？"
    )
    send_message(
        chat_id,
        text,
        reply_markup=build_confirm_keyboard("rec_confirm", "rec_cancel"),
    )


# ================================================================
#  Save to DynamoDB
# ================================================================

def _save_recurring_template(owner_id, data):
    ulid = generate_ulid()
    sid = get_next_short_id(ENTITY_FIN_RECURRING)

    item = {
        "PK": f"USER#{owner_id}",
        "SK": f"FIN_RECURRING#{ulid}",
        "GSI1PK": f"USER#{owner_id}#FIN_RECURRING",
        "GSI1SK": f"active#{ulid}",
        "GSI3PK": ENTITY_FIN_RECURRING,
        "GSI3SK": format_short_id(sid),
        "entity_type": ENTITY_FIN_RECURRING,
        "title": data["title"],
        "amount": Decimal(str(data["amount"])),
        "fin_type": data.get("fin_type", FIN_TYPE_EXPENSE),
        "day_of_month": data.get("day_of_month", 1),
        "category": data.get("category", "other"),
        "end_month": data.get("end_month"),
        "notes": data.get("notes"),
        "status": FIN_RECURRING_STATUS_ACTIVE,
        "short_id": sid,
    }
    put_item(item)
    logger.info(json.dumps({
        "event_type": "recurring_created",
        "short_id": sid,
        "title": data.get("title"),
    }))


# ================================================================
#  /edit_recurring ID — starts conversation
# ================================================================

def handle_edit_recurring(user_id, chat_id, args):
    if not args or not args.strip():
        send_message(chat_id, "❌ 請提供模板 ID，例如：`/edit_recurring 3`")
        return

    owner_id = get_owner_id()
    template = _find_template(owner_id, args.strip())
    if template is None:
        send_message(chat_id, f"❌ 找不到 ID 為 `{args.strip()}` 的週期模板。")
        return

    ulid = template["SK"].split("#", 1)[1]

    # Pre-populate data from existing template
    conv_data = {
        "_module": CONV_MODULE_EDIT_RECURRING,
        "_pk": template["PK"],
        "_sk": template["SK"],
        "_ulid": ulid,
        "_short_id": template.get("short_id"),
        "title": template.get("title", ""),
        "amount": str(template.get("amount", "0")),
        "fin_type": template.get("fin_type", FIN_TYPE_EXPENSE),
        "day_of_month": template.get("day_of_month", 1),
        "category": template.get("category", "other"),
        "end_month": template.get("end_month"),
        "notes": template.get("notes"),
    }
    set_conversation(user_id, CONV_MODULE_EDIT_RECURRING, 1, conv_data)

    current_title = escape_markdown(template.get("title", ""))
    send_message(
        chat_id,
        f"✏️ *編輯週期模板：{current_title}*\n\n"
        f"1️⃣ 請輸入新標題，或輸入「跳過」保留現有值（{current_title}）：",
        reply_markup=build_skip_keyboard("rec_skip_title", f"⏭ 保留：{current_title}"),
    )


# ================================================================
#  Edit recurring — steps (same flow, "跳過" keeps existing)
# ================================================================

def _edit_recurring_step(user_id, chat_id, text, step, data):
    if step == 1:
        t = text.strip()
        if t not in ("跳過", "skip"):
            valid, err = validate_text_length(t, 1, 100)
            if not valid:
                send_message(chat_id, f"❌ {err}")
                return
            data["title"] = t
        update_conversation(user_id, 2, data)
        current_amount = format_currency(Decimal(str(data.get("amount", "0"))))
        send_message(
            chat_id,
            f"2️⃣ 請輸入新金額，或輸入「跳過」保留現有值（{current_amount}）：",
            reply_markup=build_skip_keyboard("rec_skip_amount", f"⏭ 保留：{current_amount}"),
        )

    elif step == 2:
        t = text.strip()
        if t not in ("跳過", "skip"):
            amount = parse_amount(t)
            if amount is None:
                send_message(chat_id, "❌ 金額格式不正確，請重新輸入。")
                return
            data["amount"] = str(amount)
        update_conversation(user_id, 3, data)
        _ask_fin_type_skip(chat_id, data.get("fin_type", ""))

    elif step == 3:
        send_message(chat_id, "請點選上方按鈕選擇類型，或點選保留現有值。")

    elif step == 4:
        t = text.strip()
        if t not in ("跳過", "skip"):
            try:
                day = int(t)
                if not (1 <= day <= 28):
                    raise ValueError
            except ValueError:
                send_message(chat_id, "❌ 請輸入 1–28 的整數，或輸入「跳過」保留。")
                return
            data["day_of_month"] = day
        update_conversation(user_id, 5, data)
        _ask_category_skip(chat_id, data.get("category", "other"))

    elif step == 5:
        send_message(chat_id, "請點選上方按鈕選擇分類，或點選保留現有值。")

    elif step == 6:
        t = text.strip()
        if t not in ("跳過", "skip"):
            import re
            m = re.match(r"^(\d{4}-(?:0[1-9]|1[0-2]))$", t)
            if not m:
                send_message(chat_id, "❌ 格式錯誤，請使用 `YYYY-MM`，或輸入「跳過」保留。")
                return
            data["end_month"] = t
        update_conversation(user_id, 7, data)
        current_notes = data.get("notes") or "無"
        send_message(
            chat_id,
            f"7️⃣ 請輸入新備註，或輸入「跳過」保留現有值（{escape_markdown(str(current_notes))}）：",
            reply_markup=build_skip_keyboard("rec_skip_notes"),
        )

    elif step == 7:
        t = text.strip()
        if t not in ("跳過", "skip"):
            if t == "無":
                data["notes"] = None
            else:
                valid, err = validate_text_length(t, 1, 200)
                if not valid:
                    send_message(chat_id, f"❌ {err}")
                    return
                data["notes"] = t
        update_conversation(user_id, 8, data)
        _show_add_confirm(chat_id, data)

    elif step == 8:
        send_message(chat_id, "請點選上方按鈕確認或取消。")

    else:
        logger.warning(f"Unknown edit_recurring step: {step}")
        send_message(chat_id, "⚠️ 未知的步驟，請輸入 /cancel 重新開始。")


def _ask_fin_type_skip(chat_id, current_type):
    current_label = _FIN_TYPE_DISPLAY.get(current_type, {}).get("label", current_type)
    rows = [
        [
            {"text": "💵 收入", "callback_data": "rec_type_income"},
            {"text": "💸 支出", "callback_data": "rec_type_expense"},
        ],
        [
            {"text": f"⏭ 保留：{current_label}", "callback_data": "rec_skip_type"},
        ],
    ]
    send_message(
        chat_id,
        "3️⃣ 請選擇新類型，或點選保留現有值：",
        reply_markup=build_inline_keyboard(rows),
    )


def _ask_category_skip(chat_id, current_category):
    current_info = FIN_CATEGORIES.get(current_category, {})
    current_label = f"{current_info.get('emoji', '')} {current_info.get('display', current_category)}"
    rows = []
    row = []
    for key, info in FIN_CATEGORIES.items():
        row.append({
            "text": f"{info['emoji']} {info['display']}",
            "callback_data": f"rec_cat_{key}",
        })
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([{"text": f"⏭ 保留：{current_label}", "callback_data": "rec_skip_cat"}])
    send_message(
        chat_id,
        "5️⃣ 請選擇新分類，或點選保留現有值：",
        reply_markup=build_inline_keyboard(rows),
    )


# ================================================================
#  Apply edit to DynamoDB
# ================================================================

def _apply_edit_recurring(owner_id, user_id, data):
    pk = data["_pk"]
    sk = data["_sk"]
    ulid = data["_ulid"]
    current_status = FIN_RECURRING_STATUS_ACTIVE  # keep status unchanged; re-read not needed

    update_item(
        pk=pk,
        sk=sk,
        update_expr=(
            "SET title = :t, amount = :a, fin_type = :ft, "
            "day_of_month = :d, category = :c, end_month = :em, notes = :n"
        ),
        expr_values={
            ":t": data["title"],
            ":a": Decimal(str(data["amount"])),
            ":ft": data["fin_type"],
            ":d": data["day_of_month"],
            ":c": data.get("category", "other"),
            ":em": data.get("end_month"),
            ":n": data.get("notes"),
        },
    )

    # Propagate changes to current-month FIN record if it exists
    today = get_today()
    month_prefix = today[:7]
    fin_type = data.get("fin_type", FIN_TYPE_EXPENSE)

    existing_records = query_gsi1(
        gsi1pk=f"USER#{owner_id}#FIN#{fin_type}",
        sk_condition=Key("GSI1SK").begins_with(month_prefix),
    )

    for record in existing_records:
        if record.get("recurring_id") == ulid:
            update_item(
                pk=record["PK"],
                sk=record["SK"],
                update_expr="SET title = :t, amount = :a, category = :c, notes = :n",
                expr_values={
                    ":t": data["title"],
                    ":a": Decimal(str(data["amount"])),
                    ":c": data.get("category", "other"),
                    ":n": data.get("notes"),
                },
            )
            break

    logger.info(json.dumps({
        "event_type": "recurring_updated",
        "short_id": data.get("_short_id"),
        "title": data.get("title"),
    }))
