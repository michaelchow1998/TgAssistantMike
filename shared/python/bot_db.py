# shared/python/bot_db.py
# ============================================================
# DynamoDB CRUD 封裝 — 主表 + 對話狀態表
# ============================================================

import json
import time
import logging
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key, Attr

from bot_config import get_main_table_name, get_conv_table_name
from bot_constants import ENTITY_COUNTER, CONV_TTL_SECONDS
from bot_utils import generate_ulid, format_short_id, get_now

logger = logging.getLogger(__name__)

# Module-level — reused across warm invocations
_dynamodb = None
_main_table = None
_conv_table = None


def _get_dynamodb():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    return _dynamodb


def _get_main_table():
    global _main_table
    if _main_table is None:
        _main_table = _get_dynamodb().Table(get_main_table_name())
    return _main_table


def _get_conv_table():
    global _conv_table
    if _conv_table is None:
        _conv_table = _get_dynamodb().Table(get_conv_table_name())
    return _conv_table


# ================================================================
#  Atomic Short-ID Counter
# ================================================================

def get_next_short_id(entity_type):
    """
    Atomically increment and return the next short_id for *entity_type*.
    Uses DynamoDB ADD to guarantee uniqueness under concurrency.
    """
    table = _get_main_table()
    resp = table.update_item(
        Key={"PK": ENTITY_COUNTER, "SK": entity_type},
        UpdateExpression="ADD current_value :inc",
        ExpressionAttributeValues={":inc": 1},
        ReturnValues="UPDATED_NEW",
    )
    new_val = int(resp["Attributes"]["current_value"])
    logger.info(json.dumps({
        "event_type": "db_write",
        "op": "get_next_short_id",
        "entity_type": entity_type,
        "new_value": new_val,
    }))
    return new_val


# ================================================================
#  Main Table — basic CRUD
# ================================================================

def put_item(item):
    """Write (or overwrite) an item in the main table."""
    table = _get_main_table()
    logger.info(json.dumps({
        "event_type": "db_write", "op": "put_item",
        "pk": item.get("PK"), "sk": item.get("SK"),
    }))
    table.put_item(Item=item)


def get_item(pk, sk):
    """Get a single item by primary key."""
    table = _get_main_table()
    resp = table.get_item(Key={"PK": pk, "SK": sk})
    item = resp.get("Item")
    logger.info(json.dumps({
        "event_type": "db_read", "op": "get_item",
        "pk": pk, "sk": sk, "found": item is not None,
    }))
    return item


def update_item(pk, sk, update_expr, expr_values, expr_names=None):
    """
    Update an item and return the new version (ALL_NEW).

    expr_values : dict for ExpressionAttributeValues
    expr_names  : dict for ExpressionAttributeNames (optional)
    """
    table = _get_main_table()
    kwargs = {
        "Key": {"PK": pk, "SK": sk},
        "UpdateExpression": update_expr,
        "ExpressionAttributeValues": expr_values,
        "ReturnValues": "ALL_NEW",
    }
    if expr_names:
        kwargs["ExpressionAttributeNames"] = expr_names
    logger.info(json.dumps({
        "event_type": "db_write", "op": "update_item",
        "pk": pk, "sk": sk,
    }))
    resp = table.update_item(**kwargs)
    return resp.get("Attributes")


def delete_item(pk, sk):
    """Delete an item from the main table."""
    table = _get_main_table()
    logger.info(json.dumps({
        "event_type": "db_write", "op": "delete_item",
        "pk": pk, "sk": sk,
    }))
    table.delete_item(Key={"PK": pk, "SK": sk})


# ================================================================
#  GSI Queries
# ================================================================

def query_gsi1(gsi1pk, sk_condition=None, scan_forward=True,
               filter_expr=None, limit=None):
    """
    Query GSI_Type_Date (GSI-1).

    sk_condition: optional boto3 Key condition on GSI1SK
        e.g.  Key("GSI1SK").begins_with("2026-03-02")
        e.g.  Key("GSI1SK").between("2026-03-02#", "2026-03-08#~")
    """
    table = _get_main_table()
    kce = Key("GSI1PK").eq(gsi1pk)
    if sk_condition is not None:
        kce = kce & sk_condition

    kwargs = {
        "IndexName": "GSI_Type_Date",
        "KeyConditionExpression": kce,
        "ScanIndexForward": scan_forward,
    }
    if filter_expr is not None:
        kwargs["FilterExpression"] = filter_expr
    if limit is not None:
        kwargs["Limit"] = limit

    logger.info(json.dumps({
        "event_type": "db_read", "op": "query_gsi1",
        "gsi1pk": gsi1pk,
    }))
    resp = table.query(**kwargs)
    return resp.get("Items", [])


def query_gsi2(gsi2pk, sk_condition=None, scan_forward=True,
               filter_expr=None):
    """Query GSI_Category (GSI-2)."""
    table = _get_main_table()
    kce = Key("GSI2PK").eq(gsi2pk)
    if sk_condition is not None:
        kce = kce & sk_condition

    kwargs = {
        "IndexName": "GSI_Category",
        "KeyConditionExpression": kce,
        "ScanIndexForward": scan_forward,
    }
    if filter_expr is not None:
        kwargs["FilterExpression"] = filter_expr

    logger.info(json.dumps({
        "event_type": "db_read", "op": "query_gsi2",
        "gsi2pk": gsi2pk,
    }))
    resp = table.query(**kwargs)
    return resp.get("Items", [])


def query_gsi3(entity_type, short_id):
    """
    Look up a single item by entity type + short_id via GSI_ShortID (GSI-3).
    Returns the item dict or None.
    """
    table = _get_main_table()
    gsi3sk = format_short_id(short_id)

    logger.info(json.dumps({
        "event_type": "db_read", "op": "query_gsi3",
        "gsi3pk": entity_type, "gsi3sk": gsi3sk,
    }))
    resp = table.query(
        IndexName="GSI_ShortID",
        KeyConditionExpression=(
            Key("GSI3PK").eq(entity_type) & Key("GSI3SK").eq(gsi3sk)
        ),
    )
    items = resp.get("Items", [])
    return items[0] if items else None


# Alias for readability
get_item_by_short_id = query_gsi3


# ================================================================
#  Conversation State (BotConversationTable)
# ================================================================

def get_conversation(user_id):
    """
    Get the active conversation state.
    Returns item dict or None (also None if TTL-expired).
    """
    table = _get_conv_table()
    resp = table.get_item(Key={
        "PK": f"USER#{user_id}",
        "SK": "CONV#active",
    })
    item = resp.get("Item")
    if item is None:
        return None
    # Guard against TTL deletion delay (up to 48 h)
    if int(time.time()) > int(item.get("expire_at", 0)):
        return None
    return item


def set_conversation(user_id, module, step, data=None):
    """Create or overwrite the active conversation state (resets TTL)."""
    table = _get_conv_table()
    now = get_now()
    table.put_item(Item={
        "PK": f"USER#{user_id}",
        "SK": "CONV#active",
        "module": module,
        "step": step,
        "data": data or {},
        "started_at": now.isoformat(),
        "expire_at": int(time.time()) + CONV_TTL_SECONDS,
    })


def update_conversation(user_id, step, data):
    """Update step + data and reset TTL."""
    table = _get_conv_table()
    table.update_item(
        Key={
            "PK": f"USER#{user_id}",
            "SK": "CONV#active",
        },
        UpdateExpression="SET step = :s, #d = :d, expire_at = :t",
        ExpressionAttributeValues={
            ":s": step,
            ":d": data,
            ":t": int(time.time()) + CONV_TTL_SECONDS,
        },
        ExpressionAttributeNames={
            "#d": "data",  # reserved word
        },
    )


def delete_conversation(user_id):
    """Delete the active conversation state."""
    table = _get_conv_table()
    table.delete_item(Key={
        "PK": f"USER#{user_id}",
        "SK": "CONV#active",
    })