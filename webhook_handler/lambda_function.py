# webhook_handler/lambda_function.py
# ============================================================
# Lambda 進入點 — bot-webhook-handler
# ============================================================

import json
import logging
from bot_config import get_webhook_secret, get_log_level
from bot_telegram import send_message

logger = logging.getLogger()


def lambda_handler(event, context):
    logger.setLevel(get_log_level())

    try:
        # --- Step 1: verify Telegram secret token ---
        headers = event.get("headers", {})
        token = headers.get("x-telegram-bot-api-secret-token", "")
        if token != get_webhook_secret():
            logger.warning(json.dumps({
                "event_type": "webhook_auth_fail",
                "reason": "invalid secret token",
            }))
            return {"statusCode": 403, "body": "Forbidden"}

        # --- Step 2: parse Update JSON ---
        body = json.loads(event.get("body", "{}"))

        # --- Step 3: route ---
        from handlers.router import route_update
        route_update(body)

    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        # Best-effort error message to user
        try:
            chat_id = _extract_chat_id(event)
            if chat_id:
                send_message(chat_id, "❌ 系統發生錯誤，請稍後再試。")
        except Exception:
            pass

    # Always 200 to prevent Telegram retries
    return {"statusCode": 200, "body": "OK"}


def _extract_chat_id(event):
    """Try to extract chat_id from the raw event for error reporting."""
    try:
        body = json.loads(event.get("body", "{}"))
        if "message" in body:
            return body["message"]["chat"]["id"]
        if "callback_query" in body:
            return body["callback_query"]["message"]["chat"]["id"]
    except Exception:
        pass
    return None