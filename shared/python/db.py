"""DynamoDB helpers for the main table and conversation table."""

import time
import logging
import boto3
from boto3.dynamodb.conditions import Key
from config import TABLE_NAME, CONVERSATION_TABLE

logger = logging.getLogger(__name__)

_ddb = boto3.resource("dynamodb")
_main_table = None
_conv_table = None


def _get_main_table():
    global _main_table
    if _main_table is None:
        _main_table = _ddb.Table(TABLE_NAME)
    return _main_table


def _get_conv_table():
    global _conv_table
    if _conv_table is None:
        _conv_table = _ddb.Table(CONVERSATION_TABLE)
    return _conv_table


# ---- Conversation history ----

def save_message(user_id: int, role: str, content: str) -> None:
    table = _get_conv_table()
    table.put_item(Item={
        "PK": f"USER#{user_id}",
        "SK": f"MSG#{int(time.time() * 1000)}",
        "Role": role,
        "Content": content,
    })


def get_recent_messages(user_id: int, limit: int = 20) -> list[dict]:
    table = _get_conv_table()
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}") & Key("SK").begins_with("MSG#"),
        ScanIndexForward=False,
        Limit=limit,
    )
    items = resp.get("Items", [])
    items.reverse()
    return [{"role": item["Role"], "content": item["Content"]} for item in items]


def clear_conversation(user_id: int) -> int:
    table = _get_conv_table()
    resp = table.query(
        KeyConditionExpression=Key("PK").eq(f"USER#{user_id}"),
        ProjectionExpression="PK, SK",
    )
    items = resp.get("Items", [])
    with table.batch_writer() as batch:
        for item in items:
            batch.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
    return len(items)


# ---- Key-value store (main table) ----

def put_item(pk: str, sk: str, **attrs) -> None:
    table = _get_main_table()
    item = {"PK": pk, "SK": sk, **attrs}
    table.put_item(Item=item)


def get_item(pk: str, sk: str) -> dict | None:
    table = _get_main_table()
    resp = table.get_item(Key={"PK": pk, "SK": sk})
    return resp.get("Item")


def query_items(pk: str, sk_prefix: str = None) -> list[dict]:
    table = _get_main_table()
    if sk_prefix:
        resp = table.query(
            KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with(sk_prefix)
        )
    else:
        resp = table.query(KeyConditionExpression=Key("PK").eq(pk))
    return resp.get("Items", [])


def delete_item(pk: str, sk: str) -> None:
    table = _get_main_table()
    table.delete_item(Key={"PK": pk, "SK": sk})