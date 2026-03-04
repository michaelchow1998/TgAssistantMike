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
from boto3.dynamodb.conditions import Key, Attr

from bot_db import query_gsi1 as _db_query_gsi1, get_item as _db_get_item
from bot_config import get_owner_id
from bot_constants import SCH_STATUS_ACTIVE, SCH_TYPE_PERIOD, SCH_TYPE_REPEAT
from bot_utils import is_repeat_occurrence

logger = logging.getLogger(__name__)


# ================================================================
#  Generic GSI1 query
# ================================================================

def _query_gsi1(pk_val, sk_cond=None):
    """Query GSI_Type_Date."""
    return _db_query_gsi1(gsi1pk=pk_val, sk_condition=sk_cond)


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


def _query_gsi1_schedules(sk_cond, extra_filter=None):
    """Query SCH items via GSI_Type_Date with owner + active status filter."""
    owner_id = get_owner_id()
    gsi1pk = f"USER#{owner_id}#SCH"
    filter_expr = Attr("status").eq(SCH_STATUS_ACTIVE)
    if extra_filter is not None:
        filter_expr = filter_expr & extra_filter
    return _db_query_gsi1(
        gsi1pk=gsi1pk,
        sk_condition=sk_cond,
        filter_expr=filter_expr,
    )


def get_schedules_effective_on(date_str):
    """All active schedules effective on date_str: single + period + repeat."""
    # 1. Items starting on this date (any type)
    same_day = _query_gsi1_schedules(
        sk_cond=Key("GSI1SK").begins_with(f"{date_str}#"),
    )

    # 2. Period items that started before date_str but end on/after date_str
    period_items = _query_gsi1_schedules(
        sk_cond=Key("GSI1SK").between("0000-01-01#", f"{date_str}#"),
        extra_filter=(
            Attr("schedule_type").eq(SCH_TYPE_PERIOD)
            & Attr("end_date").gte(date_str)
        ),
    )

    # 3. Repeat items that started before date_str — filter by occurrence
    repeat_candidates = _query_gsi1_schedules(
        sk_cond=Key("GSI1SK").between("0000-01-01#", f"{date_str}#"),
        extra_filter=Attr("schedule_type").eq(SCH_TYPE_REPEAT),
    )
    earlier_repeats = [r for r in repeat_candidates if is_repeat_occurrence(r, date_str)]

    # Merge, dedup by SK; apply occurrence check to repeat items in same_day
    seen, results = set(), []
    for item in same_day:
        sk = item["SK"]
        if sk in seen:
            continue
        seen.add(sk)
        if (item.get("schedule_type") == SCH_TYPE_REPEAT
                and not is_repeat_occurrence(item, date_str)):
            continue
        results.append(item)

    for item in period_items + earlier_repeats:
        sk = item["SK"]
        if sk not in seen:
            seen.add(sk)
            results.append(item)

    return results


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


# ================================================================
#  Health
# ================================================================

def get_today_meals(owner_id, date_str):
    """Today's health meal records for the reminder health section."""
    return _db_query_gsi1(
        gsi1pk=f"USER#{owner_id}#HEALTH",
        sk_condition=Key("GSI1SK").begins_with(date_str),
    )


def get_health_settings(owner_id):
    """Health settings (TDEE + deficit target)."""
    return _db_get_item(f"USER#{owner_id}", "HEALTH_SETTINGS#active")