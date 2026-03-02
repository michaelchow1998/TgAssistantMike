# shared/python/bot_config.py
# ============================================================
# 設定讀取：SSM Parameter Store（快取）+ 環境變數
# ============================================================

import os
import logging
import boto3

logger = logging.getLogger(__name__)

# Module-level cache — survives Lambda container reuse
_cache = {}
_ssm_client = None


def _get_ssm_client():
    global _ssm_client
    if _ssm_client is None:
        _ssm_client = boto3.client("ssm")
    return _ssm_client


def _get_ssm_parameter(name, with_decryption=True):
    """Read a single SSM parameter with module-level caching."""
    if name in _cache:
        return _cache[name]

    client = _get_ssm_client()
    try:
        response = client.get_parameter(
            Name=name,
            WithDecryption=with_decryption,
        )
        value = response["Parameter"]["Value"]
        _cache[name] = value
        logger.info(f"SSM parameter loaded: {name}")
        return value
    except Exception as e:
        logger.error(f"Failed to read SSM parameter {name}: {e}")
        raise


# ----- SSM-backed settings -----

def get_bot_token():
    return _get_ssm_parameter("/bot/token")


def get_owner_id():
    return int(_get_ssm_parameter("/bot/owner_id", with_decryption=False))


def get_webhook_secret():
    return _get_ssm_parameter("/bot/webhook_secret")


def get_webhook_path():
    return _get_ssm_parameter("/bot/webhook_path")


# ----- Environment variable settings -----

def get_main_table_name():
    return os.environ.get("MAIN_TABLE_NAME", "BotMainTable")


def get_conv_table_name():
    return os.environ.get("CONV_TABLE_NAME", "BotConversationTable")


def get_timezone():
    return os.environ.get("TIMEZONE", "Asia/Hong_Kong")


def get_log_level():
    return os.environ.get("LOG_LEVEL", "INFO")