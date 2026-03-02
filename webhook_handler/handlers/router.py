# webhook_handler/handlers/router.py
# ============================================================
# 訊息 / Callback / 對話 路由器
# ============================================================

import json
import logging

from bot_config import get_owner_id
from bot_telegram import send_message, answer_callback_query
from bot_db import get_conversation, delete_conversation
from bot_constants import (
    CONVERSATION_STARTER_COMMANDS,
    MODULE_DISPLAY_NAMES,
    CONV_MODULE_SCHEDULE,
    CONV_MODULE_TODO,
)

logger = logging.getLogger(__name__)


# ================================================================
#  Top-level router
# ================================================================

def route_update(update):
    """Dispatch a Telegram Update to the right handler."""

    if "callback_query" in update:
        _handle_callback_query(update["callback_query"])
        return

    if "message" in update:
        message = update["message"]
        user_id = message.get("from", {}).get("id")
        chat_id = message.get("chat", {}).get("id")

        if not _verify_owner(user_id, chat_id):
            return

        text = (message.get("text") or "").strip()
        if not text:
            return

        logger.info(json.dumps({
            "event_type": "message_received",
            "user_id": user_id,
            "text": text[:50],
        }, ensure_ascii=False))

        _handle_text_message(user_id, chat_id, text)


# ================================================================
#  Owner verification
# ================================================================

def _verify_owner(user_id, chat_id):
    if user_id != get_owner_id():
        send_message(chat_id, "⛔ 你無權使用此 Bot。")
        logger.warning(json.dumps({
            "event_type": "unauthorized",
            "user_id": user_id,
        }))
        return False
    return True


# ================================================================
#  Text message handling
# ================================================================

def _handle_text_message(user_id, chat_id, text):
    # /cancel is always honoured, even mid-conversation
    if text.lower() == "/cancel":
        _handle_cancel(user_id, chat_id)
        return

    conv = get_conversation(user_id)

    if conv:
        # If user starts a *new* conversation command → override
        cmd = _extract_command(text)
        if cmd in CONVERSATION_STARTER_COMMANDS:
            _route_command(user_id, chat_id, text)
            return

        # Any other slash-command while in conversation → warn
        if text.startswith("/"):
            module = conv.get("module", "")
            display = MODULE_DISPLAY_NAMES.get(module, module)
            send_message(
                chat_id,
                f"⚠️ 你正在進行「{display}」操作，請先完成或輸入 /cancel 取消。",
            )
            return

        # Regular text → feed into conversation step
        _handle_conversation_step(user_id, chat_id, text, conv)
        return

    # No active conversation
    if text.startswith("/"):
        _route_command(user_id, chat_id, text)
    else:
        send_message(chat_id, "請輸入指令，輸入 /help 查看可用指令。")


def _handle_cancel(user_id, chat_id):
    conv = get_conversation(user_id)
    if conv:
        delete_conversation(user_id)
        send_message(chat_id, "✅ 已取消當前操作。")
    else:
        send_message(chat_id, "目前沒有進行中的操作。")


# ================================================================
#  Command routing
# ================================================================

def _extract_command(text):
    """Return the /command portion, stripped of @botname suffix."""
    cmd = text.split()[0].lower()
    if "@" in cmd:
        cmd = cmd.split("@")[0]
    return cmd


def _route_command(user_id, chat_id, text):
    parts = text.split(maxsplit=1)
    cmd = _extract_command(text)
    args = parts[1].strip() if len(parts) > 1 else ""

    logger.info(json.dumps({
        "event_type": "command_received",
        "command": cmd,
        "args": args[:50],
        "user_id": user_id,
    }, ensure_ascii=False))

    # ----- System -----
    if cmd == "/start":
        from handlers.start import handle_start
        handle_start(chat_id)

    elif cmd == "/help":
        from handlers.start import handle_help
        handle_help(chat_id)

    # ----- Schedule -----
    elif cmd == "/add_schedule":
        from handlers.schedule import handle_add_schedule
        handle_add_schedule(user_id, chat_id)

    elif cmd == "/today":
        from handlers.schedule import handle_today
        handle_today(user_id, chat_id)

    elif cmd == "/week":
        from handlers.schedule import handle_week
        handle_week(user_id, chat_id)

    elif cmd == "/cancel_schedule":
        from handlers.schedule import handle_cancel_schedule
        handle_cancel_schedule(user_id, chat_id, args)

    # ----- Todo -----
    elif cmd == "/add_todo":
        from handlers.todo import handle_add_todo
        handle_add_todo(user_id, chat_id)

    elif cmd == "/todos":
        from handlers.todo import handle_todos
        handle_todos(user_id, chat_id)

    elif cmd == "/done":
        from handlers.todo import handle_done
        handle_done(user_id, chat_id, args)

    elif cmd == "/del_todo":
        from handlers.todo import handle_del_todo
        handle_del_todo(user_id, chat_id, args)

    # ----- Work (placeholders) -----
    elif cmd == "/add_work":
        _placeholder(chat_id, cmd)
    elif cmd == "/work":
        _placeholder(chat_id, cmd)
    elif cmd == "/update_progress":
        _placeholder(chat_id, cmd)
    elif cmd == "/deadlines":
        _placeholder(chat_id, cmd)

    # ----- Finance (placeholders) -----
    elif cmd == "/add_payment":
        _placeholder(chat_id, cmd)
    elif cmd == "/add_income":
        _placeholder(chat_id, cmd)
    elif cmd == "/add_expense":
        _placeholder(chat_id, cmd)
    elif cmd == "/payments":
        _placeholder(chat_id, cmd)
    elif cmd == "/paid":
        _placeholder(chat_id, cmd)
    elif cmd == "/finance_summary":
        _placeholder(chat_id, cmd)

    # ----- Subscription (placeholders) -----
    elif cmd == "/add_sub":
        _placeholder(chat_id, cmd)
    elif cmd == "/subs":
        _placeholder(chat_id, cmd)
    elif cmd == "/sub_due":
        _placeholder(chat_id, cmd)
    elif cmd == "/renew_sub":
        _placeholder(chat_id, cmd)
    elif cmd == "/pause_sub":
        _placeholder(chat_id, cmd)
    elif cmd == "/resume_sub":
        _placeholder(chat_id, cmd)
    elif cmd == "/cancel_sub":
        _placeholder(chat_id, cmd)
    elif cmd == "/edit_sub":
        _placeholder(chat_id, cmd)
    elif cmd == "/sub_cost":
        _placeholder(chat_id, cmd)

    # ----- Query (placeholders) -----
    elif cmd == "/summary":
        _placeholder(chat_id, cmd)
    elif cmd == "/search":
        _placeholder(chat_id, cmd)
    elif cmd == "/monthly_report":
        _placeholder(chat_id, cmd)

    else:
        send_message(
            chat_id,
            f"❌ 未知指令：{cmd}\n\n輸入 /help 查看可用指令。",
        )


def _placeholder(chat_id, cmd):
    """Temporary stub for not-yet-implemented commands."""
    send_message(chat_id, f"🚧 指令 `{cmd}` 尚未實作。")


# ================================================================
#  Callback query handling
# ================================================================

def _handle_callback_query(callback_query):
    user_id = callback_query.get("from", {}).get("id")
    chat_id = callback_query.get("message", {}).get("chat", {}).get("id")
    callback_id = callback_query.get("id")
    data = callback_query.get("data", "")
    message_id = callback_query.get("message", {}).get("message_id")

    if user_id != get_owner_id():
        answer_callback_query(callback_id, "⛔ 無權操作")
        return

    logger.info(json.dumps({
        "event_type": "callback_received",
        "user_id": user_id,
        "callback_data": data,
    }))

    # Always dismiss the loading spinner
    answer_callback_query(callback_id)

    # If there's an active conversation, route callback there
    conv = get_conversation(user_id)
    if conv:
        _handle_conversation_callback(
            user_id, chat_id, message_id, data, conv,
        )
        return

    # Standalone callbacks (e.g. cancelsub_confirm_{id})
    _handle_standalone_callback(user_id, chat_id, message_id, data)


# ================================================================
#  Conversation step dispatcher
# ================================================================

def _handle_conversation_step(user_id, chat_id, text, conv):
    """Dispatch text input to the active conversation's module handler."""
    module = conv.get("module")
    step = conv.get("step")
    data = conv.get("data", {})

    logger.info(json.dumps({
        "event_type": "conversation_step",
        "module": module,
        "step": step,
    }))

    if module == CONV_MODULE_SCHEDULE:
        from handlers.schedule import handle_step
        handle_step(user_id, chat_id, text, step, data)

    elif module == CONV_MODULE_TODO:
        from handlers.todo import handle_step
        handle_step(user_id, chat_id, text, step, data)

    # elif module == CONV_MODULE_WORK:
    #     from handlers.work import handle_step
    #     handle_step(user_id, chat_id, text, step, data)

    # elif module == CONV_MODULE_FINANCE:
    #     from handlers.finance import handle_step
    #     handle_step(user_id, chat_id, text, step, data)

    # elif module == CONV_MODULE_SUBSCRIPTION:
    #     from handlers.subscription import handle_step
    #     handle_step(user_id, chat_id, text, step, data)

    else:
        send_message(
            chat_id,
            f"🚧 對話模組 `{module}` 尚未實作，請輸入 /cancel 取消。",
        )


# ================================================================
#  Conversation callback dispatcher
# ================================================================

def _handle_conversation_callback(user_id, chat_id, message_id, data, conv):
    """Dispatch callback to the active conversation's module handler."""
    module = conv.get("module")
    step = conv.get("step")
    conv_data = conv.get("data", {})

    logger.info(json.dumps({
        "event_type": "conversation_callback",
        "module": module,
        "step": step,
        "callback_data": data,
    }))

    if module == CONV_MODULE_SCHEDULE:
        from handlers.schedule import handle_callback
        handle_callback(user_id, chat_id, message_id, data, step, conv_data)

    elif module == CONV_MODULE_TODO:
        from handlers.todo import handle_callback
        handle_callback(user_id, chat_id, message_id, data, step, conv_data)

    # elif module == CONV_MODULE_WORK:
    #     from handlers.work import handle_callback
    #     handle_callback(user_id, chat_id, message_id, data, step, conv_data)

    # elif module == CONV_MODULE_FINANCE:
    #     from handlers.finance import handle_callback
    #     handle_callback(user_id, chat_id, message_id, data, step, conv_data)

    # elif module == CONV_MODULE_SUBSCRIPTION:
    #     from handlers.subscription import handle_callback
    #     handle_callback(user_id, chat_id, message_id, data, step, conv_data)

    else:
        logger.warning(f"No callback handler for module: {module}")


# ================================================================
#  Standalone callback handler
# ================================================================

def _handle_standalone_callback(user_id, chat_id, message_id, data):
    """Handle callbacks outside any active conversation."""
    # Future: cancelsub_confirm_{id}, cancelsub_keep_{id}, etc.
    logger.info(json.dumps({
        "event_type": "standalone_callback",
        "callback_data": data,
    }))