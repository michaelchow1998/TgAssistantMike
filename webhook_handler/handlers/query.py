# webhook_handler/handlers/query.py
# ============================================================
# 綜合查詢 — /summary, /search, /monthly_report
# ============================================================

import json
import logging
from decimal import Decimal
from datetime import timedelta

from boto3.dynamodb.conditions import Key, Attr

from bot_constants import (
    ENTITY_SCH,
    ENTITY_TODO,
    ENTITY_WORK,
    ENTITY_FIN,
    ENTITY_SUB,
    SCH_STATUS_ACTIVE,
    TODO_STATUS_PENDING,
    WORK_STATUS_IN_PROGRESS,
    FIN_TYPE_PAYMENT,
    FIN_TYPE_INCOME,
    FIN_TYPE_EXPENSE,
    FIN_STATUS_PENDING,
    FIN_STATUS_PAID,
    SUB_STATUS_ACTIVE,
    SCH_CATEGORIES,
    TODO_CATEGORIES,
    TODO_PRIORITIES,
    WORK_CATEGORIES,
    FIN_CATEGORIES,
    SUB_CATEGORIES,
    SUB_CYCLES,
    NO_DUE_DATE_SENTINEL,
)
from bot_config import get_owner_id
from bot_telegram import send_message
from bot_db import query_gsi1
from bot_utils import (
    get_now,
    get_today,
    get_today_date,
    get_weekday_name,
    format_date_full,
    format_date_short,
    format_currency,
    format_progress_bar,
    days_until_display,
    escape_markdown,
)

logger = logging.getLogger(__name__)


# ================================================================
#  /summary — 每日摘要
# ================================================================

def handle_summary(user_id, chat_id):
    owner_id = get_owner_id()
    today = get_today()
    today_date = get_today_date()
    weekday = get_weekday_name(today)
    now = get_now()
    greeting = _get_greeting(now.hour)

    lines = [
        f"{greeting}\n",
        f"📋 *{today}（{weekday}）每日摘要*\n",
    ]

    # ----- Today's schedule -----
    schedules = query_gsi1(
        gsi1pk=f"USER#{owner_id}#SCH",
        sk_condition=Key("GSI1SK").begins_with(f"{today}#"),
        filter_expr=Attr("status").eq(SCH_STATUS_ACTIVE),
    )

    lines.append(f"📅 *今日行程*（{len(schedules)} 筆）")
    if schedules:
        for item in schedules:
            time_str = item.get("time", "")
            time_display = time_str if time_str else "全天"
            cat_info = SCH_CATEGORIES.get(item.get("category", "other"), {})
            emoji = cat_info.get("emoji", "📦")
            lines.append(
                f"  {emoji} {escape_markdown(item.get('title', ''))}"
                f"  \\[{time_display}\\]"
            )
    else:
        lines.append("  今天沒有行程 🎉")
    lines.append("")

    # ----- Pending todos -----
    todos = query_gsi1(
        gsi1pk=f"USER#{owner_id}#TODO",
        filter_expr=Attr("status").eq(TODO_STATUS_PENDING),
    )

    overdue_todos = [
        t for t in todos
        if t.get("due_date") and t["due_date"] != NO_DUE_DATE_SENTINEL and t["due_date"] < today
    ]
    today_todos = [
        t for t in todos
        if t.get("due_date") == today
    ]

    lines.append(f"📝 *待辦事項*（{len(todos)} 筆待完成）")
    if overdue_todos:
        lines.append(f"  ⚠️ {len(overdue_todos)} 筆已逾期")
    if today_todos:
        for t in today_todos:
            pri = int(t.get("priority", 3))
            pri_emoji = TODO_PRIORITIES.get(pri, {}).get("emoji", "⚪")
            lines.append(f"  {pri_emoji} {escape_markdown(t.get('title', ''))}")
    elif not overdue_todos:
        lines.append("  今天沒有到期待辦 ✅")
    lines.append("")

    # ----- Work in progress -----
    works = query_gsi1(
        gsi1pk=f"USER#{owner_id}#WORK",
        filter_expr=Attr("status").eq(WORK_STATUS_IN_PROGRESS),
    )

    deadline_soon = []
    for w in works:
        dl = w.get("deadline", "")
        if dl and dl != NO_DUE_DATE_SENTINEL:
            end_check = (today_date + timedelta(days=3)).strftime("%Y-%m-%d")
            if dl <= end_check:
                deadline_soon.append(w)

    lines.append(f"🔨 *進行中工作*（{len(works)} 筆）")
    if deadline_soon:
        for w in deadline_soon:
            progress = int(w.get("progress", 0))
            dl_rel = days_until_display(w.get("deadline", ""))
            lines.append(
                f"  ⏰ {escape_markdown(w.get('title', ''))}"
                f"  {progress}%  {dl_rel}"
            )
    elif works:
        lines.append("  近期沒有到期工作 👍")
    else:
        lines.append("  目前沒有進行中工作 🎉")
    lines.append("")

    # ----- Pending payments -----
    payments = query_gsi1(
        gsi1pk=f"USER#{owner_id}#FIN#{FIN_TYPE_PAYMENT}",
        filter_expr=Attr("status").eq(FIN_STATUS_PENDING),
    )

    overdue_payments = [
        p for p in payments
        if p.get("date") and p["date"] < today
    ]
    upcoming_payments = [
        p for p in payments
        if p.get("date") and today <= p["date"] <= (today_date + timedelta(days=7)).strftime("%Y-%m-%d")
    ]

    total_pending = sum(Decimal(str(p.get("amount", 0))) for p in payments)

    lines.append(f"💳 *待付款項*（{len(payments)} 筆，{format_currency(total_pending)}）")
    if overdue_payments:
        lines.append(f"  ⚠️ {len(overdue_payments)} 筆已逾期！")
    if upcoming_payments:
        for p in upcoming_payments:
            amount = Decimal(str(p.get("amount", 0)))
            dl_rel = days_until_display(p.get("date", ""))
            lines.append(
                f"  💲 {escape_markdown(p.get('title', ''))}"
                f"  {format_currency(amount)}  {dl_rel}"
            )
    elif not overdue_payments:
        lines.append("  近期沒有到期款項 ✅")
    lines.append("")

    # ----- Upcoming subscriptions -----
    subs = query_gsi1(
        gsi1pk=f"USER#{owner_id}#SUB",
        sk_condition=Key("GSI1SK").between(
            f"{today}#",
            f"{(today_date + timedelta(days=7)).strftime('%Y-%m-%d')}#~",
        ),
        filter_expr=Attr("status").eq(SUB_STATUS_ACTIVE),
    )

    if subs:
        total_sub = sum(Decimal(str(s.get("amount", 0))) for s in subs)
        lines.append(f"📦 *即將扣款訂閱*（{len(subs)} 筆，{format_currency(total_sub)}）")
        for s in subs:
            amount = Decimal(str(s.get("amount", 0)))
            nb = s.get("next_billing", "")
            nb_rel = days_until_display(nb) if nb else ""
            lines.append(
                f"  📦 {escape_markdown(s.get('name', ''))}"
                f"  {format_currency(amount)}  {nb_rel}"
            )
    else:
        lines.append("📦 *即將扣款訂閱*\n  7 天內沒有到期訂閱 ✅")

    send_message(chat_id, "\n".join(lines))


def _get_greeting(hour):
    if 5 <= hour < 12:
        return "🌅 *早安！*"
    elif 12 <= hour < 18:
        return "☀️ *午安！*"
    else:
        return "🌙 *晚安！*"


# ================================================================
#  /search <keyword> — 全域搜尋
# ================================================================

def handle_search(user_id, chat_id, keyword):
    if not keyword or len(keyword.strip()) < 1:
        send_message(chat_id, "❌ 請提供搜尋關鍵字，例如：`/search 會議`")
        return

    keyword = keyword.strip()
    if len(keyword) > 50:
        send_message(chat_id, "❌ 關鍵字過長，最多 50 個字元。")
        return

    owner_id = get_owner_id()
    kw_lower = keyword.lower()
    results = []

    # ----- Search schedules -----
    sch_items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#SCH",
        filter_expr=Attr("status").eq(SCH_STATUS_ACTIVE),
    )
    for item in sch_items:
        if _match(item, kw_lower, ["title", "notes"]):
            results.append(("📅", ENTITY_SCH, item))

    # ----- Search todos -----
    todo_items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#TODO",
        filter_expr=Attr("status").eq(TODO_STATUS_PENDING),
    )
    for item in todo_items:
        if _match(item, kw_lower, ["title", "notes"]):
            results.append(("📝", ENTITY_TODO, item))

    # ----- Search work -----
    work_items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#WORK",
        filter_expr=Attr("status").eq(WORK_STATUS_IN_PROGRESS),
    )
    for item in work_items:
        if _match(item, kw_lower, ["title", "description"]):
            results.append(("🔨", ENTITY_WORK, item))

    # ----- Search finance (all types) -----
    for fin_type in (FIN_TYPE_PAYMENT, FIN_TYPE_INCOME, FIN_TYPE_EXPENSE):
        fin_items = query_gsi1(
            gsi1pk=f"USER#{owner_id}#FIN#{fin_type}",
        )
        for item in fin_items:
            if _match(item, kw_lower, ["title", "notes"]):
                results.append(("💰", ENTITY_FIN, item))

    # ----- Search subscriptions -----
    sub_items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#SUB",
        filter_expr=Attr("status").ne("cancelled"),
    )
    for item in sub_items:
        if _match(item, kw_lower, ["name", "notes"]):
            results.append(("📦", ENTITY_SUB, item))

    # ----- Format results -----
    if not results:
        send_message(
            chat_id,
            f"🔍 搜尋「{escape_markdown(keyword)}」\n\n找不到相關結果。",
        )
        return

    # Limit display
    MAX_RESULTS = 20
    total = len(results)
    display = results[:MAX_RESULTS]

    lines = [
        f"🔍 搜尋「{escape_markdown(keyword)}」（共 {total} 筆）\n"
    ]

    for emoji, entity_type, item in display:
        if entity_type == ENTITY_SCH:
            date_str = item.get("date", "")
            time_str = item.get("time", "")
            time_part = f" {time_str}" if time_str else ""
            lines.append(
                f"{emoji} *{escape_markdown(item.get('title', ''))}*\n"
                f"  📆 {format_date_full(date_str)}{time_part}"
                f"  `{item.get('short_id', '')}`"
            )

        elif entity_type == ENTITY_TODO:
            due = item.get("due_date", "")
            due_display = format_date_short(due) if due and due != NO_DUE_DATE_SENTINEL else "無截止日"
            pri = int(item.get("priority", 3))
            pri_emoji = TODO_PRIORITIES.get(pri, {}).get("emoji", "⚪")
            lines.append(
                f"{emoji} {pri_emoji} *{escape_markdown(item.get('title', ''))}*\n"
                f"  📆 {due_display}"
                f"  `{item.get('short_id', '')}`"
            )

        elif entity_type == ENTITY_WORK:
            progress = int(item.get("progress", 0))
            dl = item.get("deadline", "")
            dl_display = format_date_short(dl) if dl and dl != NO_DUE_DATE_SENTINEL else "無截止日"
            lines.append(
                f"{emoji} *{escape_markdown(item.get('title', ''))}*\n"
                f"  📊 {progress}%  📆 {dl_display}"
                f"  `{item.get('short_id', '')}`"
            )

        elif entity_type == ENTITY_FIN:
            amount = Decimal(str(item.get("amount", 0)))
            fin_type = item.get("fin_type", "")
            type_emoji = {"payment": "💳", "income": "💵", "expense": "💸"}.get(fin_type, "💰")
            lines.append(
                f"{type_emoji} *{escape_markdown(item.get('title', ''))}*\n"
                f"  💲 {format_currency(amount)}"
                f"  `{item.get('short_id', '')}`"
            )

        elif entity_type == ENTITY_SUB:
            amount = Decimal(str(item.get("amount", 0)))
            cycle = item.get("cycle", "monthly")
            cycle_display = SUB_CYCLES.get(cycle, {}).get("display", cycle)
            lines.append(
                f"{emoji} *{escape_markdown(item.get('name', ''))}*\n"
                f"  💲 {format_currency(amount)}/{cycle_display}"
                f"  `{item.get('short_id', '')}`"
            )

    if total > MAX_RESULTS:
        lines.append(f"\n⚠️ 僅顯示前 {MAX_RESULTS} 筆，共 {total} 筆結果。")

    send_message(chat_id, "\n".join(lines))


def _match(item, kw_lower, fields):
    """Check if keyword matches any of the given fields (case-insensitive)."""
    for field in fields:
        value = item.get(field, "")
        if value and kw_lower in value.lower():
            return True
    return False


# ================================================================
#  /monthly_report — 月度報表
# ================================================================

def handle_monthly_report(user_id, chat_id):
    owner_id = get_owner_id()
    today_date = get_today_date()
    month_prefix = today_date.strftime("%Y-%m")
    month_label = today_date.strftime("%Y年%m月")

    lines = [f"📊 *{month_label} 月度報表*\n"]

    # ===== Schedule stats =====
    sch_items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#SCH",
        sk_condition=Key("GSI1SK").begins_with(f"{month_prefix}"),
    )
    sch_active = [s for s in sch_items if s.get("status") == SCH_STATUS_ACTIVE]
    sch_cancelled = [s for s in sch_items if s.get("status") != SCH_STATUS_ACTIVE]

    lines.append(
        f"📅 *行程*：{len(sch_active)} 筆"
        f"（已取消 {len(sch_cancelled)} 筆）"
    )

    # Category breakdown for schedules
    sch_by_cat = {}
    for s in sch_active:
        cat = s.get("category", "other")
        sch_by_cat[cat] = sch_by_cat.get(cat, 0) + 1
    if sch_by_cat:
        parts = []
        for cat, count in sorted(sch_by_cat.items(), key=lambda x: x[1], reverse=True):
            cat_info = SCH_CATEGORIES.get(cat, {})
            emoji = cat_info.get("emoji", "📦")
            display = cat_info.get("display", cat)
            parts.append(f"{emoji}{display} {count}")
        lines.append(f"  {' / '.join(parts)}")
    lines.append("")

    # ===== Todo stats =====
    todo_items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#TODO",
    )
    # Filter by created_at month
    todo_this_month = [
        t for t in todo_items
        if t.get("created_at", "").startswith(month_prefix)
    ]
    todo_completed = [t for t in todo_this_month if t.get("status") == "completed"]
    todo_pending = [t for t in todo_this_month if t.get("status") == TODO_STATUS_PENDING]
    todo_deleted = [t for t in todo_this_month if t.get("status") == "deleted"]

    total_todo = len(todo_this_month)
    completion_rate = (len(todo_completed) / total_todo * 100) if total_todo > 0 else 0

    lines.append(
        f"📝 *待辦*：本月新增 {total_todo} 筆"
    )
    lines.append(
        f"  ✅ 已完成 {len(todo_completed)} / "
        f"⏳ 待完成 {len(todo_pending)} / "
        f"🗑️ 已刪除 {len(todo_deleted)}"
    )
    lines.append(f"  📈 完成率：{completion_rate:.0f}%")
    lines.append("")

    # ===== Work stats =====
    work_items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#WORK",
    )
    work_this_month = [
        w for w in work_items
        if w.get("created_at", "").startswith(month_prefix)
    ]
    work_completed = [w for w in work_this_month if w.get("status") == "completed"]
    work_in_progress = [w for w in work_items if w.get("status") == WORK_STATUS_IN_PROGRESS]

    avg_progress = 0
    if work_in_progress:
        avg_progress = sum(int(w.get("progress", 0)) for w in work_in_progress) / len(work_in_progress)

    lines.append(
        f"🔨 *工作*：本月新增 {len(work_this_month)} 筆"
        f"，完成 {len(work_completed)} 筆"
    )
    lines.append(
        f"  📊 進行中 {len(work_in_progress)} 筆"
        f"，平均進度 {avg_progress:.0f}%"
    )

    # Category breakdown for work
    work_by_cat = {}
    for w in work_this_month:
        cat = w.get("category", "other")
        work_by_cat[cat] = work_by_cat.get(cat, 0) + 1
    if work_by_cat:
        parts = []
        for cat, count in sorted(work_by_cat.items(), key=lambda x: x[1], reverse=True):
            cat_info = WORK_CATEGORIES.get(cat, {})
            emoji = cat_info.get("emoji", "📦")
            display = cat_info.get("display", cat)
            parts.append(f"{emoji}{display} {count}")
        lines.append(f"  {' / '.join(parts)}")
    lines.append("")

    # ===== Finance stats =====
    income_items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#FIN#{FIN_TYPE_INCOME}",
        sk_condition=Key("GSI1SK").begins_with(month_prefix),
    )
    expense_items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#FIN#{FIN_TYPE_EXPENSE}",
        sk_condition=Key("GSI1SK").begins_with(month_prefix),
    )
    payment_items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#FIN#{FIN_TYPE_PAYMENT}",
        sk_condition=Key("GSI1SK").begins_with(month_prefix),
    )
    paid_payments = [p for p in payment_items if p.get("status") == FIN_STATUS_PAID]
    pending_payments = [p for p in payment_items if p.get("status") == FIN_STATUS_PENDING]

    total_income = sum(Decimal(str(i.get("amount", 0))) for i in income_items)
    total_expense = sum(Decimal(str(i.get("amount", 0))) for i in expense_items)
    total_paid = sum(Decimal(str(i.get("amount", 0))) for i in paid_payments)
    total_pending = sum(Decimal(str(i.get("amount", 0))) for i in pending_payments)
    total_outflow = total_expense + total_paid
    net = total_income - total_outflow
    net_emoji = "📈" if net >= 0 else "📉"

    lines.append("💰 *財務*")
    lines.append(f"  💵 收入：{format_currency(total_income)}（{len(income_items)} 筆）")
    lines.append(f"  💸 支出：{format_currency(total_expense)}（{len(expense_items)} 筆）")
    lines.append(f"  💳 已付款：{format_currency(total_paid)}（{len(paid_payments)} 筆）")
    lines.append(f"  ⏳ 待付款：{format_currency(total_pending)}（{len(pending_payments)} 筆）")
    lines.append(f"  {net_emoji} 淨額：{format_currency(net)}")

    # Top 3 expense categories
    expense_by_cat = {}
    for item in expense_items:
        cat = item.get("category", "other")
        amt = Decimal(str(item.get("amount", 0)))
        expense_by_cat[cat] = expense_by_cat.get(cat, Decimal("0")) + amt

    sorted_expense_cats = sorted(expense_by_cat.items(), key=lambda x: x[1], reverse=True)[:3]
    if sorted_expense_cats:
        lines.append("  📊 支出 Top 3：")
        for cat, amt in sorted_expense_cats:
            cat_info = FIN_CATEGORIES.get(cat, {})
            emoji = cat_info.get("emoji", "📦")
            display = cat_info.get("display", cat)
            pct = (amt / total_expense * 100) if total_expense > 0 else Decimal("0")
            lines.append(f"    {emoji} {display}：{format_currency(amt)}（{pct:.0f}%）")
    lines.append("")

    # ===== Subscription stats =====
    sub_items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#SUB",
        filter_expr=Attr("status").eq(SUB_STATUS_ACTIVE),
    )

    total_monthly_sub = Decimal("0")
    for s in sub_items:
        amount = Decimal(str(s.get("amount", 0)))
        cycle = s.get("cycle", "monthly")
        months = SUB_CYCLES.get(cycle, {}).get("months", 1)
        total_monthly_sub += (amount / months).quantize(Decimal("0.01"))

    lines.append(
        f"📦 *訂閱*：{len(sub_items)} 個啟用中"
        f"，每月 {format_currency(total_monthly_sub)}"
    )

    # ----- Overall summary line -----
    lines.append("")
    total_monthly_out = total_outflow + total_monthly_sub
    lines.append(
        f"💡 *本月總支出估算*"
        f"（支出 + 已付款 + 訂閱）：{format_currency(total_monthly_out)}"
    )

    send_message(chat_id, "\n".join(lines))