"""Thin wrapper around the Telegram Bot API (HTTP)."""

import json
import logging
from urllib import request, parse, error

from config import get_bot_token

logger = logging.getLogger()

BASE = "https://api.telegram.org"


def _call(method: str, payload: dict) -> dict:
    url = f"{BASE}/bot{get_bot_token()}/{method}"
    data = json.dumps(payload).encode()
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except error.HTTPError as e:
        body = e.read().decode()
        logger.error("Telegram API error %s: %s", e.code, body)
        return {"ok": False, "description": body}


def send_message(chat_id: int, text: str, **kwargs) -> dict:
    return _call("sendMessage", {"chat_id": chat_id, "text": text, **kwargs})


def send_typing(chat_id: int) -> dict:
    return _call("sendChatAction", {"chat_id": chat_id, "action": "typing"})