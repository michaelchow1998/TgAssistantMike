# shared/python/bot_telegram.py
# ============================================================
# Telegram Bot API 封裝（httpx 同步客戶端）
# ============================================================

import json
import logging
import httpx
from bot_config import get_bot_token

logger = logging.getLogger(__name__)

# Module-level — reused across warm invocations
_client = None
_base_url = None


def _get_client():
    global _client
    if _client is None:
        _client = httpx.Client(timeout=10.0)
    return _client


def _get_base_url():
    global _base_url
    if _base_url is None:
        _base_url = f"https://api.telegram.org/bot{get_bot_token()}"
    return _base_url


def _call_api(method, payload):
    """Call a Telegram Bot API method. Returns result dict or None on error."""
    url = f"{_get_base_url()}/{method}"
    client = _get_client()
    try:
        response = client.post(url, json=payload)
        if response.status_code != 200:
            logger.error(json.dumps({
                "event_type": "telegram_api_error",
                "method": method,
                "status": response.status_code,
                "body": response.text[:500],
            }, ensure_ascii=False))
            return None
        result = response.json()
        if not result.get("ok"):
            logger.error(json.dumps({
                "event_type": "telegram_api_not_ok",
                "method": method,
                "result": result,
            }, ensure_ascii=False))
            return None
        return result.get("result")
    except Exception as e:
        logger.error(json.dumps({
            "event_type": "telegram_api_exception",
            "method": method,
            "error": str(e),
        }, ensure_ascii=False))
        return None


# ===== Public API =====

def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    """Send a text message. Optionally attach an InlineKeyboard."""
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    logger.info(json.dumps({
        "event_type": "telegram_api_call",
        "method": "sendMessage",
        "chat_id": chat_id,
    }))
    return _call_api("sendMessage", payload)


def answer_callback_query(callback_query_id, text=None):
    """Answer a callback query (dismiss the loading spinner)."""
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    return _call_api("answerCallbackQuery", payload)


def edit_message_text(chat_id, message_id, text, reply_markup=None, parse_mode="Markdown"):
    """Edit an already-sent message."""
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return _call_api("editMessageText", payload)


# ===== Keyboard Builders =====

def build_inline_keyboard(rows):
    """
    Build an InlineKeyboardMarkup dict.

    rows: list of rows, each row is a list of {"text": ..., "callback_data": ...}
    Example:
        [[{"text": "✅ 確認", "callback_data": "yes"},
          {"text": "❌ 取消", "callback_data": "no"}]]
    """
    return {
        "inline_keyboard": [
            [{"text": btn["text"], "callback_data": btn["callback_data"]}
             for btn in row]
            for row in rows
        ]
    }


def build_confirm_keyboard(yes_data, no_data):
    """Shortcut for a confirm / cancel keyboard row."""
    return build_inline_keyboard([[
        {"text": "✅ 確認", "callback_data": yes_data},
        {"text": "❌ 取消", "callback_data": no_data},
    ]])


def build_skip_keyboard(callback_data, label="⏭ 跳過"):
    """Shortcut for a single 'skip' button."""
    return build_inline_keyboard([[
        {"text": label, "callback_data": callback_data},
    ]])