# reminders/db_queries.py
# ============================================================
# DynamoDB 查詢層 — 透過 GSI_Type_Date 查詢 BotMainTable
#
# ╔══════════════╦═════════════════════╦═══════════════════════════╗
# ║ Entity       ║ GSI1PK              ║ GSI1SK                    ║
# ╠══════════════╬═════════════════════╬═══════════════════════════╣
# ║ Schedule     ║ SCHEDULE            ║ {date}#{time}#{ulid}      ║
# ║ Todo         ║ TODO#pending        ║ {due_date}#{ulid}         ║
# ║ Todo         ║ TODO#done           ║ {done_date}#{ulid}        ║
# ║ Payment      ║ PAYMENT#pending     ║ {due_date}#{ulid}         ║
# ║ Payment      ║ PAYMENT#paid        ║ {paid_date}#{ulid}        ║
# ║ Subscription ║ SUB#active          ║ {next_due}#{ulid}         ║
# ║ Subscription ║ SUB#cancelled       ║ {end_date}#{ulid}         ║
# ║ Work         ║ WORK#in_progress    ║ {deadline}#{ulid}         ║
# ║ Work         ║ WORK#done           ║ {done_date}#{ulid}        ║
# ╚══════════════╩═════════════════════╩═══════════════════════════╝
# ============================================================

import logging
from boto3.dynamodb.conditions import Key

from db import main_table          # ← shared layer

logger = logging.getLogger(__name__)

GSI_NAME = "GSI_Type_Date"


# ================================================================
#  Generic GSI1 query（自動分頁）
# ================================================================

def _query_gsi1(pk_val, sk_cond=None):
    """Query GSI_Type_Date with automatic pagination."""
    kce = Key("GSI1PK").eq(pk_val)
    if sk_cond is not None:
        kce = kce & sk_cond

    kwargs = {"IndexName": GSI_NAME, "KeyConditionExpression": kce}
    items = []

    try:
        while True:
            resp = main_table.query(**kwargs)
            items.extend(resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            kwargs["ExclusiveStartKey"] = lek
    except Exception as e:
        logger.error(f"GSI1 query error (PK={pk_val}): {e}")

    logger.debug(f"GSI1 PK={pk_val}: {len(items)} items")
    return items


# ================================================================
#  Schedule
# ================================================================

def get_schedules_for_date(date_str):
    """取得指定日期的所有行程。"""
    return _query_gsi1("SCHEDULE", Key("GSI1SK").begins_with(date_str))


def get_schedules_range(start, end):
    """取得 [start, end] 日期範圍的行程。"""
    return _query_gsi1(
        "SCHEDULE",
        Key("GSI1SK").between(start, end + "\uffff"),
    )


# ================================================================
#  Todo
# ================================================================

def get_pending_todos():
    """取得所有 pending 待辦（含逾期 + 未來）。"""
    return _query_gsi1("TODO#pending")


# ================================================================
#  Payment
# ================================================================

def get_pending_payments():
    """取得所有 pending 付款。"""
    return _query_gsi1("PAYMENT#pending")


# ================================================================
#  Subscription
# ================================================================

def get_active_subscriptions():
    """取得所有 active 訂閱。"""
    return _query_gsi1("SUB#active")


# ================================================================
#  Work
# ================================================================

def get_active_work():
    """取得所有 in_progress 工作項目。"""
    return _query_gsi1("WORK#in_progress")