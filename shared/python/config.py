"""Centralised configuration loaded once per Lambda cold start."""

import os
import boto3

_ssm = boto3.client("ssm")


def _get_param(name: str, decrypt: bool = True) -> str:
    resp = _ssm.get_parameter(Name=name, WithDecryption=decrypt)
    return resp["Parameter"]["Value"]


# Environment variables set by SAM template
TABLE_NAME = os.environ.get("TABLE_NAME", "BotMainTable")
CONVERSATION_TABLE = os.environ.get("CONVERSATION_TABLE", "BotConversationTable")

# Load from SSM
_bot_token: str | None = None
_owner_id: int | None = None
_webhook_secret: str | None = None


def get_bot_token() -> str:
    global _bot_token
    if _bot_token is None:
        _bot_token = _get_param("/bot/telegram-token")
    return _bot_token


def get_owner_id() -> int:
    global _owner_id
    if _owner_id is None:
        _owner_id = int(_get_param("/bot/owner-id", decrypt=False))
    return _owner_id


def get_webhook_secret() -> str:
    global _webhook_secret
    if _webhook_secret is None:
        _webhook_secret = _get_param("/bot/webhook-secret")
    return _webhook_secret


# Keep backward compatibility
@property
def _lazy_owner():
    return get_owner_id()


OWNER_ID = None  # Will use get_owner_id() instead
WEBHOOK_SECRET = None  # Will use get_webhook_secret() instead