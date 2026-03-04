# Finance Statement + Recurring Transactions Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `/statement` monthly statement, recurring income/expense templates with auto-generation, and fix `/finance_summary` to show two net lines and deduct subscriptions.

**Architecture:** All finance changes in `webhook_handler/handlers/finance.py` and new `recurring.py`. Recurring templates are a new entity type `FIN_RECURRING` stored in BotMainTable. Auto-generation runs in the morning reminder on the 1st of each month. Tests in new `tests/test_finance_handler.py` and `tests/test_recurring_handler.py`.

**Tech Stack:** Python 3.13, pytest, unittest.mock, boto3 DynamoDB conditions (Key.begins_with, Key.between)

---

## Context

- Mock at caller's namespace: `patch("handlers.finance.query_gsi1")` not `patch("bot_db.query_gsi1")`
- Finance GSI1 pattern: `GSI1PK = "USER#{owner_id}#FIN#{fin_type}"`, `GSI1SK = "{date}#{ULID}"`
- Subscription GSI1: `GSI1PK = "SUB#active"`, `GSI1SK = "{next_due}#{ULID}"`
- Recurring GSI1: `GSI1PK = "USER#{owner_id}#FIN_RECURRING"`, `GSI1SK = "{status}#{ULID}"`
- Run tests: `pytest tests/ -v`
- Deploy: `bash scripts/deploy.sh`

---

### Task 1: bot_constants.py — Recurring constants

**Files:**
- Modify: `shared/python/bot_constants.py`

**Step 1: Add after line 13 (`ENTITY_HEALTH = "HEALTH"`):**

```python
ENTITY_FIN_RECURRING = "FIN_RECURRING"
```

**Step 2: Add after line 74 (`FIN_STATUS_CANCELLED = "cancelled"`):**

```python
FIN_RECURRING_STATUS_ACTIVE = "active"
FIN_RECURRING_STATUS_PAUSED = "paused"
FIN_RECURRING_STATUS_COMPLETED = "completed"
```

**Step 3: Add after line 121 (`CONV_MODULE_SET_HEALTH = "set_health"`):**

```python
CONV_MODULE_ADD_RECURRING = "add_recurring"
CONV_MODULE_EDIT_RECURRING = "edit_recurring"
```

**Step 4: Add to `MODULE_DISPLAY_NAMES` dict (after line 159):**

```python
    CONV_MODULE_ADD_RECURRING:  "新增週期記錄",
    CONV_MODULE_EDIT_RECURRING: "編輯週期記錄",
```

**Step 5: Add to `CONVERSATION_STARTER_COMMANDS` set (line 164):**

```python
"/add_recurring",
```

**Step 6: Run syntax check:**

```bash
python -c "import ast; ast.parse(open('shared/python/bot_constants.py', encoding='utf-8').read()); print('OK')"
```

**Step 7: Commit:**

```bash
git add shared/python/bot_constants.py
git commit -m "feat: add FIN_RECURRING entity and conversation module constants"
```

---

### Task 2: Finance summary fix — two nets + subscription deduction

**Files:**
- Modify: `webhook_handler/handlers/finance.py`
- Create: `tests/test_finance_handler.py`

**Step 1: Write failing tests** — create `tests/test_finance_handler.py`:

```python
# tests/test_finance_handler.py
import pytest
from decimal import Decimal
from unittest.mock import patch

from handlers.finance import handle_finance_summary

OWNER_ID = 111
CHAT_ID = 222
USER_ID = OWNER_ID


def _income(amount, date="2026-03-10"):
    return {"fin_type": "income", "amount": Decimal(str(amount)), "date": date, "title": "薪水", "category": "salary"}

def _expense(amount, date="2026-03-10"):
    return {"fin_type": "expense", "amount": Decimal(str(amount)), "date": date, "title": "支出", "category": "food"}

def _payment(amount, status, date="2026-03-10"):
    return {"fin_type": "payment", "amount": Decimal(str(amount)), "date": date, "title": "帳單", "status": status, "due_date": date}

def _sub(amount, next_due="2026-03-15"):
    return {"name": "Netflix", "amount": Decimal(str(amount)), "next_due": next_due, "cycle": "monthly"}


class TestFinanceSummaryTwoNets:
    def test_net_excludes_pending_payment_from_settled(self):
        # income=10000, expense=1000, paid=2000, pending=500
        # settled = 10000-1000-2000 = 7000; with_pending = 7000-500 = 6500
        with patch("handlers.finance.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.finance.get_today_date", return_value=__import__("datetime").date(2026, 3, 31)), \
             patch("handlers.finance.query_gsi1", side_effect=[
                 [_income(10000)],             # income
                 [_expense(1000)],             # expense
                 [_payment(2000, "paid"), _payment(500, "pending")],  # payments
                 [],                           # subscriptions
             ]), \
             patch("handlers.finance.send_message") as mock_send:
            handle_finance_summary(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "7,000" in msg    # settled net
            assert "6,500" in msg    # with-pending net
            assert "已結清淨額" in msg
            assert "含待付淨額" in msg

    def test_subscription_deducted_from_both_nets(self):
        # income=10000, no expense, no payment, sub=500
        # settled = 10000-500 = 9500; with_pending = 9500-0 = 9500
        with patch("handlers.finance.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.finance.get_today_date", return_value=__import__("datetime").date(2026, 3, 31)), \
             patch("handlers.finance.query_gsi1", side_effect=[
                 [_income(10000)],   # income
                 [],                 # expense
                 [],                 # payments
                 [_sub(500)],        # subscriptions
             ]), \
             patch("handlers.finance.send_message") as mock_send:
            handle_finance_summary(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "9,500" in msg

    def test_no_subscription_no_deduction(self):
        with patch("handlers.finance.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.finance.get_today_date", return_value=__import__("datetime").date(2026, 3, 31)), \
             patch("handlers.finance.query_gsi1", side_effect=[
                 [_income(5000)],
                 [],
                 [],
                 [],  # empty subscriptions
             ]), \
             patch("handlers.finance.send_message") as mock_send:
            handle_finance_summary(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "5,000" in msg
            assert "已結清淨額" in msg
```

**Step 2: Run to verify failure:**

```bash
pytest tests/test_finance_handler.py::TestFinanceSummaryTwoNets -v
```
Expected: ImportError or assertion failures.

**Step 3: Update `handle_finance_summary` in `finance.py`**

After the existing `payment_items` query (around line 549), add a subscription query:

```python
    # --- Fetch subscriptions due this month ---
    sub_items = query_gsi1(
        gsi1pk="SUB#active",
        sk_condition=Key("GSI1SK").begins_with(month_prefix),
    )
    total_sub = sum(Decimal(str(s.get("amount", 0))) for s in sub_items)
```

Replace the net calculation block (lines 559–583) with:

```python
    total_outflow_settled = total_expense + total_paid + total_sub
    net_settled = total_income - total_outflow_settled
    net_with_pending = net_settled - total_pending

    # --- Build message ---
    settled_emoji = "📈" if net_settled >= 0 else "📉"
    pending_emoji = "📈" if net_with_pending >= 0 else "📉"

    lines = [
        f"💰 *{month_label} 財務摘要*\n",
        f"💵 收入：{format_currency(total_income)}（{len(income_items)} 筆）",
        f"💸 支出：{format_currency(total_expense)}（{len(expense_items)} 筆）",
        f"💳 已付款：{format_currency(total_paid)}（{len(paid_payments)} 筆）",
        f"⏳ 待付款：{format_currency(total_pending)}（{len(pending_payments)} 筆）",
    ]
    if total_sub > 0:
        lines.append(f"📦 當月訂閱：{format_currency(total_sub)}（{len(sub_items)} 項）")
    lines += [
        "",
        f"{settled_emoji} 已結清淨額：{format_currency(net_settled)}",
        f"   （收入 − 支出 − 已付款 − 當月訂閱）",
        f"{pending_emoji} 含待付淨額：{format_currency(net_with_pending)}",
        f"   （再扣除待付款項）",
    ]
```

**Step 4: Run tests:**

```bash
pytest tests/test_finance_handler.py::TestFinanceSummaryTwoNets -v
```
Expected: 3 passed.

**Step 5: Commit:**

```bash
git add webhook_handler/handlers/finance.py tests/test_finance_handler.py
git commit -m "feat: finance summary shows two net lines and deducts subscriptions"
```

---

### Task 3: `/statement [YYYY-MM]` command

**Files:**
- Modify: `webhook_handler/handlers/finance.py`
- Modify: `tests/test_finance_handler.py`

**Step 1: Write failing tests** — add to `tests/test_finance_handler.py`:

```python
from handlers.finance import handle_statement


class TestStatementCommand:
    def test_shows_income_section(self):
        with patch("handlers.finance.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.finance.get_today_date", return_value=__import__("datetime").date(2026, 3, 31)), \
             patch("handlers.finance.query_gsi1", side_effect=[
                 [_income(20000)],
                 [],
                 [],
             ]), \
             patch("handlers.finance.send_message") as mock_send:
            handle_statement(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "收入" in msg
            assert "20,000" in msg

    def test_shows_expense_section(self):
        with patch("handlers.finance.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.finance.get_today_date", return_value=__import__("datetime").date(2026, 3, 31)), \
             patch("handlers.finance.query_gsi1", side_effect=[
                 [],
                 [_expense(500)],
                 [],
             ]), \
             patch("handlers.finance.send_message") as mock_send:
            handle_statement(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "支出" in msg
            assert "500" in msg

    def test_splits_paid_and_pending_payments(self):
        with patch("handlers.finance.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.finance.get_today_date", return_value=__import__("datetime").date(2026, 3, 31)), \
             patch("handlers.finance.query_gsi1", side_effect=[
                 [],
                 [],
                 [_payment(8000, "paid"), _payment(3000, "pending")],
             ]), \
             patch("handlers.finance.send_message") as mock_send:
            handle_statement(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "已付" in msg
            assert "待付" in msg
            assert "8,000" in msg
            assert "3,000" in msg

    def test_shows_two_nets(self):
        # income=10000, expense=1000, paid=2000, pending=500
        # settled=7000, with_pending=6500
        with patch("handlers.finance.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.finance.get_today_date", return_value=__import__("datetime").date(2026, 3, 31)), \
             patch("handlers.finance.query_gsi1", side_effect=[
                 [_income(10000)],
                 [_expense(1000)],
                 [_payment(2000, "paid"), _payment(500, "pending")],
             ]), \
             patch("handlers.finance.send_message") as mock_send:
            handle_statement(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "7,000" in msg
            assert "6,500" in msg

    def test_accepts_month_arg(self):
        with patch("handlers.finance.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.finance.get_today_date", return_value=__import__("datetime").date(2026, 3, 31)), \
             patch("handlers.finance.query_gsi1", side_effect=[[], [], []]), \
             patch("handlers.finance.send_message") as mock_send:
            handle_statement(USER_ID, CHAT_ID, "2026-01")
            msg = mock_send.call_args[0][1]
            assert "2026-01" in msg or "01月" in msg

    def test_invalid_month_shows_error(self):
        with patch("handlers.finance.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.finance.send_message") as mock_send:
            handle_statement(USER_ID, CHAT_ID, "bad")
            assert "❌" in mock_send.call_args[0][1]
```

**Step 2: Run to verify failure:**

```bash
pytest tests/test_finance_handler.py::TestStatementCommand -v
```
Expected: ImportError — `handle_statement` not defined.

**Step 3: Add `handle_statement` to `finance.py`** (after `handle_finance_summary`):

```python
def handle_statement(user_id, chat_id, args=""):
    import re
    owner_id = get_owner_id()
    today_date = get_today_date()

    if args and args.strip():
        m = re.match(r"^(\d{4}-(?:0[1-9]|1[0-2]))$", args.strip())
        if not m:
            send_message(chat_id, "❌ 格式錯誤，請使用 `YYYY-MM`，例如：`/statement 2026-02`")
            return
        month_prefix = m.group(1)
    else:
        month_prefix = today_date.strftime("%Y-%m")

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
    total_paid = sum(Decimal(str(p.get("amount", 0))) for p in paid_payments)
    total_pending = sum(Decimal(str(p.get("amount", 0))) for p in pending_payments)

    net_settled = total_income - total_expense - total_paid
    net_with_pending = net_settled - total_pending

    lines = [f"💰 *{month_prefix} 收支明細*", "──────────────────────"]

    if income_items:
        lines.append(f"📈 *收入（{len(income_items)} 筆）*")
        for item in income_items:
            cat_info = FIN_CATEGORIES.get(item.get("category", "other"), {})
            emoji = cat_info.get("emoji", "💵")
            lines.append(f"  {emoji} {item.get('title', '?')}：+{format_currency(Decimal(str(item.get('amount', 0))))}")
        lines.append(f"  小計：+{format_currency(total_income)}")
        lines.append("")

    if expense_items:
        lines.append(f"📉 *支出（{len(expense_items)} 筆）*")
        for item in expense_items:
            cat_info = FIN_CATEGORIES.get(item.get("category", "other"), {})
            emoji = cat_info.get("emoji", "💸")
            lines.append(f"  {emoji} {item.get('title', '?')}：-{format_currency(Decimal(str(item.get('amount', 0))))}")
        lines.append(f"  小計：-{format_currency(total_expense)}")
        lines.append("")

    if paid_payments:
        lines.append(f"💳 *付款 — 已付（{len(paid_payments)} 筆）*")
        for item in paid_payments:
            lines.append(f"  • {item.get('title', '?')}：-{format_currency(Decimal(str(item.get('amount', 0))))}")

    if pending_payments:
        lines.append(f"⏳ *付款 — 待付（{len(pending_payments)} 筆）*")
        for item in pending_payments:
            due = item.get("due_date", "")
            due_s = f"（到期 {due[5:]}）" if due else ""
            lines.append(f"  • {item.get('title', '?')}：-{format_currency(Decimal(str(item.get('amount', 0))))}{due_s}")

    lines.append("──────────────────────")
    settled_emoji = "📈" if net_settled >= 0 else "📉"
    pending_emoji = "📈" if net_with_pending >= 0 else "📉"
    lines.append(f"{settled_emoji} 已結清淨額：{format_currency(net_settled)}")
    lines.append(f"{pending_emoji} 含待付淨額：{format_currency(net_with_pending)}")

    if not income_items and not expense_items and not payment_items:
        send_message(chat_id, f"💰 *{month_prefix} 收支明細*\n\n本月尚無任何財務記錄。")
        return

    send_message(chat_id, "\n".join(lines))
```

**Step 4: Run tests:**

```bash
pytest tests/test_finance_handler.py::TestStatementCommand -v
```
Expected: 6 passed.

**Step 5: Commit:**

```bash
git add webhook_handler/handlers/finance.py tests/test_finance_handler.py
git commit -m "feat: add /statement monthly finance statement command"
```

---

### Task 4: Recurring handler — simple commands

**Files:**
- Create: `webhook_handler/handlers/recurring.py`
- Create: `tests/test_recurring_handler.py`

**Step 1: Write failing tests** — create `tests/test_recurring_handler.py`:

```python
# tests/test_recurring_handler.py
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from handlers.recurring import (
    handle_recurring,
    handle_del_recurring,
    handle_pause_recurring,
    handle_resume_recurring,
)

OWNER_ID = 111
CHAT_ID = 222
USER_ID = OWNER_ID


def _template(title="薪水", amount=20000, fin_type="income", day=1,
              status="active", end_month=None, short_id=1):
    return {
        "PK": f"USER#{OWNER_ID}",
        "SK": f"FIN_RECURRING#01ABC",
        "title": title,
        "amount": Decimal(str(amount)),
        "fin_type": fin_type,
        "day_of_month": day,
        "category": "salary",
        "status": status,
        "end_month": end_month,
        "short_id": short_id,
    }


class TestHandleRecurring:
    def test_shows_active_templates(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.query_gsi1", return_value=[_template()]), \
             patch("handlers.recurring.send_message") as mock_send:
            handle_recurring(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "薪水" in msg
            assert "20,000" in msg

    def test_empty_list_shows_hint(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.query_gsi1", return_value=[]), \
             patch("handlers.recurring.send_message") as mock_send:
            handle_recurring(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "尚無" in msg or "add_recurring" in msg.lower()


class TestHandleDelRecurring:
    def test_not_found_shows_error(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.query_gsi3", return_value=None), \
             patch("handlers.recurring.send_message") as mock_send:
            handle_del_recurring(USER_ID, CHAT_ID, "99")
            assert "❌" in mock_send.call_args[0][1]

    def test_missing_id_shows_error(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.send_message") as mock_send:
            handle_del_recurring(USER_ID, CHAT_ID, "")
            assert "❌" in mock_send.call_args[0][1]


class TestHandlePauseRecurring:
    def test_not_found_shows_error(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.query_gsi3", return_value=None), \
             patch("handlers.recurring.send_message") as mock_send:
            handle_pause_recurring(USER_ID, CHAT_ID, "99")
            assert "❌" in mock_send.call_args[0][1]
```

**Step 2: Run to verify failure:**

```bash
pytest tests/test_recurring_handler.py -v
```
Expected: ImportError.

**Step 3: Create `webhook_handler/handlers/recurring.py`:**

```python
# webhook_handler/handlers/recurring.py
# ============================================================
# 週期財務記錄 — /add_recurring, /recurring, /edit_recurring,
#                /del_recurring, /pause_recurring, /resume_recurring
# ============================================================

import logging
from decimal import Decimal

from boto3.dynamodb.conditions import Key

from bot_constants import (
    ENTITY_FIN_RECURRING,
    FIN_TYPE_INCOME,
    FIN_TYPE_EXPENSE,
    FIN_CATEGORIES,
    FIN_RECURRING_STATUS_ACTIVE,
    FIN_RECURRING_STATUS_PAUSED,
    FIN_RECURRING_STATUS_COMPLETED,
    CONV_MODULE_ADD_RECURRING,
    CONV_MODULE_EDIT_RECURRING,
)
from bot_config import get_owner_id
from bot_db import (
    query_gsi1,
    query_gsi3,
    put_item,
    update_item,
    delete_item,
    set_conversation,
    get_conversation,
    delete_conversation,
)
from bot_telegram import send_message, edit_message_text, build_inline_keyboard, build_confirm_keyboard
from bot_utils import get_today, generate_ulid, next_short_id

logger = logging.getLogger(__name__)

_FIN_TYPE_DISPLAY = {
    FIN_TYPE_INCOME:  ("📈", "收入"),
    FIN_TYPE_EXPENSE: ("📉", "支出"),
}


# ================================================================
#  /recurring — List all templates
# ================================================================

def handle_recurring(user_id, chat_id):
    owner_id = get_owner_id()
    items = query_gsi1(
        gsi1pk=f"USER#{owner_id}#FIN_RECURRING",
        sk_condition=Key("GSI1SK").begins_with(FIN_RECURRING_STATUS_ACTIVE),
    )
    paused = query_gsi1(
        gsi1pk=f"USER#{owner_id}#FIN_RECURRING",
        sk_condition=Key("GSI1SK").begins_with(FIN_RECURRING_STATUS_PAUSED),
    )
    all_items = items + paused

    if not all_items:
        send_message(chat_id, "📋 尚無週期記錄。\n\n使用 /add\\_recurring 新增週期收入或支出。")
        return

    lines = ["🔄 *週期財務記錄*", ""]
    for t in sorted(all_items, key=lambda x: x.get("short_id", 0)):
        emoji, type_label = _FIN_TYPE_DISPLAY.get(t.get("fin_type", ""), ("💰", ""))
        amt = Decimal(str(t.get("amount", 0)))
        status = t.get("status", "")
        status_s = " ⏸ 已暫停" if status == FIN_RECURRING_STATUS_PAUSED else ""
        end_s = f" 至 {t['end_month']}" if t.get("end_month") else ""
        day = t.get("day_of_month", 1)
        lines.append(
            f"`#{t.get('short_id', '?'):05d}` {emoji} {t.get('title', '?')} "
            f"{amt:,.0f}（每月{day}日）{end_s}{status_s}"
        )

    send_message(chat_id, "\n".join(lines))


# ================================================================
#  /del_recurring ID
# ================================================================

def handle_del_recurring(user_id, chat_id, args):
    owner_id = get_owner_id()
    if not args.strip():
        send_message(chat_id, "❌ 請提供 ID，例如：`/del_recurring 1`")
        return
    template = _find_template(owner_id, args.strip())
    if not template:
        send_message(chat_id, "❌ 找不到此週期記錄。")
        return
    delete_item(template["PK"], template["SK"])
    send_message(chat_id, f"🗑️ 已刪除週期記錄「{template.get('title', '')}」。\n過去已生成的記錄不受影響。")


# ================================================================
#  /pause_recurring ID / /resume_recurring ID
# ================================================================

def handle_pause_recurring(user_id, chat_id, args):
    owner_id = get_owner_id()
    if not args.strip():
        send_message(chat_id, "❌ 請提供 ID，例如：`/pause_recurring 1`")
        return
    template = _find_template(owner_id, args.strip())
    if not template:
        send_message(chat_id, "❌ 找不到此週期記錄。")
        return
    _update_template_status(template, FIN_RECURRING_STATUS_PAUSED)
    send_message(chat_id, f"⏸ 已暫停「{template.get('title', '')}」，下月不會自動新增。")


def handle_resume_recurring(user_id, chat_id, args):
    owner_id = get_owner_id()
    if not args.strip():
        send_message(chat_id, "❌ 請提供 ID，例如：`/resume_recurring 1`")
        return
    template = _find_template(owner_id, args.strip())
    if not template:
        send_message(chat_id, "❌ 找不到此週期記錄。")
        return
    _update_template_status(template, FIN_RECURRING_STATUS_ACTIVE)
    send_message(chat_id, f"▶️ 已恢復「{template.get('title', '')}」，下月起自動新增。")


# ================================================================
#  Helpers
# ================================================================

def _find_template(owner_id, short_id_str):
    try:
        sid = int(short_id_str)
    except ValueError:
        return None
    return query_gsi3(ENTITY_FIN_RECURRING, sid)


def _update_template_status(template, new_status):
    ulid = template["SK"].split("#", 1)[1]
    old_gsi1sk = f"{template['status']}#{ulid}"
    new_gsi1sk = f"{new_status}#{ulid}"
    update_item(
        template["PK"], template["SK"],
        updates={"status": new_status, "GSI1SK": new_gsi1sk},
    )
```

**Step 4: Run tests:**

```bash
pytest tests/test_recurring_handler.py -v
```
Expected: all pass (some may need small adjustments if imports differ — check actual bot_db exports and fix).

**Step 5: Commit:**

```bash
git add webhook_handler/handlers/recurring.py tests/test_recurring_handler.py
git commit -m "feat: add recurring handler with list, delete, pause, resume commands"
```

---

### Task 5: Recurring — /add_recurring conversation

**Files:**
- Modify: `webhook_handler/handlers/recurring.py`
- Modify: `tests/test_recurring_handler.py`

**Step 1: Write failing tests** — add to `tests/test_recurring_handler.py`:

```python
from handlers.recurring import handle_add_recurring, handle_step as recurring_handle_step


class TestAddRecurringConversation:
    def test_start_asks_for_title(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.set_conversation"), \
             patch("handlers.recurring.send_message") as mock_send:
            handle_add_recurring(USER_ID, CHAT_ID)
            assert "標題" in mock_send.call_args[0][1]

    def test_step1_title_saves_and_asks_amount(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.set_conversation") as mock_conv, \
             patch("handlers.recurring.send_message") as mock_send:
            recurring_handle_step(USER_ID, CHAT_ID, "薪水", 1, {})
            assert mock_conv.called
            assert "金額" in mock_send.call_args[0][1]

    def test_step2_invalid_amount_shows_error(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.set_conversation"), \
             patch("handlers.recurring.send_message") as mock_send:
            recurring_handle_step(USER_ID, CHAT_ID, "abc", 2, {"title": "薪水"})
            assert "❌" in mock_send.call_args[0][1]

    def test_step2_valid_amount_asks_type(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.set_conversation"), \
             patch("handlers.recurring.send_message") as mock_send:
            recurring_handle_step(USER_ID, CHAT_ID, "20000", 2, {"title": "薪水"})
            msg = mock_send.call_args[0][1]
            assert "收入" in msg or "支出" in msg
```

**Step 2: Run to verify failure:**

```bash
pytest tests/test_recurring_handler.py::TestAddRecurringConversation -v
```

**Step 3: Add conversation to `recurring.py`:**

```python
# ================================================================
#  /add_recurring — Multi-step conversation
# ================================================================

def handle_add_recurring(user_id, chat_id):
    owner_id = get_owner_id()
    set_conversation(user_id, {
        "module": CONV_MODULE_ADD_RECURRING,
        "step": 1,
        "data": {},
    })
    send_message(chat_id, "🔄 *新增週期記錄*\n\n第 1 步：請輸入標題（例如：薪水、租金）")


def handle_step(user_id, chat_id, text, step, data):
    if data.get("_module") == CONV_MODULE_EDIT_RECURRING or \
       data.get("module") == CONV_MODULE_EDIT_RECURRING:
        _edit_recurring_step(user_id, chat_id, text, step, data)
        return
    _add_recurring_step(user_id, chat_id, text, step, data)


def _add_recurring_step(user_id, chat_id, text, step, data):
    owner_id = get_owner_id()

    if step == 1:
        # Title
        title = text.strip()
        if not title:
            send_message(chat_id, "❌ 標題不能為空，請重新輸入：")
            return
        data["title"] = title
        set_conversation(user_id, {"module": CONV_MODULE_ADD_RECURRING, "step": 2, "data": data})
        send_message(chat_id, f"✅ 標題：{title}\n\n第 2 步：請輸入金額（正整數，例如：20000）")

    elif step == 2:
        # Amount
        try:
            amt = int(text.strip().replace(",", ""))
            if amt <= 0:
                raise ValueError
        except ValueError:
            send_message(chat_id, "❌ 請輸入正整數金額：")
            return
        data["amount"] = amt
        set_conversation(user_id, {"module": CONV_MODULE_ADD_RECURRING, "step": 3, "data": data})
        keyboard = build_inline_keyboard([[
            {"text": "📈 收入", "callback_data": "rec_type_income"},
            {"text": "📉 支出", "callback_data": "rec_type_expense"},
        ]])
        send_message(chat_id, f"✅ 金額：{amt:,}\n\n第 3 步：請選擇類型", reply_markup=keyboard)

    elif step == 4:
        # Day of month
        try:
            day = int(text.strip())
            if not 1 <= day <= 28:
                raise ValueError
        except ValueError:
            send_message(chat_id, "❌ 請輸入 1–28 的整數（每月幾號）：")
            return
        data["day_of_month"] = day
        set_conversation(user_id, {"module": CONV_MODULE_ADD_RECURRING, "step": 5, "data": data})
        cat_buttons = [
            [{"text": f"{v['emoji']} {v['display']}", "callback_data": f"rec_cat_{k}"}]
            for k, v in list(FIN_CATEGORIES.items())[:5]
        ] + [
            [{"text": f"{v['emoji']} {v['display']}", "callback_data": f"rec_cat_{k}"}]
            for k, v in list(FIN_CATEGORIES.items())[5:]
        ]
        send_message(chat_id, f"✅ 每月 {day} 日\n\n第 5 步：請選擇分類", reply_markup=build_inline_keyboard(cat_buttons))

    elif step == 6:
        # End month (optional)
        import re
        txt = text.strip()
        if txt.lower() in ("skip", "跳過", "-"):
            data["end_month"] = None
        else:
            if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", txt):
                send_message(chat_id, "❌ 格式錯誤，請輸入 YYYY-MM 或輸入「跳過」：")
                return
            data["end_month"] = txt
        set_conversation(user_id, {"module": CONV_MODULE_ADD_RECURRING, "step": 7, "data": data})
        send_message(chat_id, "第 7 步：備註（可輸入「跳過」略過）")

    elif step == 7:
        # Notes (optional)
        txt = text.strip()
        data["notes"] = None if txt.lower() in ("skip", "跳過", "-") else txt
        set_conversation(user_id, {"module": CONV_MODULE_ADD_RECURRING, "step": 8, "data": data})
        _show_add_confirm(chat_id, data)

    elif step == 8:
        send_message(chat_id, "請點選下方按鈕確認或取消。")


def _show_add_confirm(chat_id, data):
    fin_type = data.get("fin_type", "income")
    emoji, type_label = _FIN_TYPE_DISPLAY.get(fin_type, ("💰", ""))
    end_s = data.get("end_month") or "無"
    notes_s = data.get("notes") or "無"
    cat_info = FIN_CATEGORIES.get(data.get("category", "other"), {})
    cat_s = f"{cat_info.get('emoji','')} {cat_info.get('display','')}"
    lines = [
        "🔄 *確認新增週期記錄*",
        f"標題：{data.get('title')}",
        f"類型：{emoji} {type_label}",
        f"金額：{data.get('amount', 0):,}",
        f"每月：{data.get('day_of_month')} 日",
        f"分類：{cat_s}",
        f"結束月份：{end_s}",
        f"備註：{notes_s}",
    ]
    send_message(chat_id, "\n".join(lines), reply_markup=build_confirm_keyboard("rec_confirm", "rec_cancel"))


def handle_callback(user_id, chat_id, message_id, callback_data, step, data):
    owner_id = get_owner_id()

    if callback_data.startswith("rec_type_"):
        fin_type = callback_data.replace("rec_type_", "")
        data["fin_type"] = fin_type
        set_conversation(user_id, {"module": CONV_MODULE_ADD_RECURRING, "step": 4, "data": data})
        emoji, label = _FIN_TYPE_DISPLAY.get(fin_type, ("💰", ""))
        edit_message_text(chat_id, message_id, f"✅ 類型：{emoji} {label}\n\n第 4 步：請輸入每月幾號（1–28）")

    elif callback_data.startswith("rec_cat_"):
        category = callback_data.replace("rec_cat_", "")
        data["category"] = category
        set_conversation(user_id, {"module": CONV_MODULE_ADD_RECURRING, "step": 6, "data": data})
        cat_info = FIN_CATEGORIES.get(category, {})
        edit_message_text(
            chat_id, message_id,
            f"✅ 分類：{cat_info.get('emoji','')} {cat_info.get('display','')}\n\n"
            "第 6 步：結束月份（格式 YYYY-MM，無結束日期請輸入「跳過」）"
        )

    elif callback_data == "rec_confirm":
        _save_recurring_template(owner_id, data)
        delete_conversation(user_id)
        fin_type = data.get("fin_type", "income")
        emoji, label = _FIN_TYPE_DISPLAY.get(fin_type, ("💰", ""))
        edit_message_text(chat_id, message_id,
            f"✅ 已新增週期{label}「{data.get('title')}」，"
            f"每月 {data.get('day_of_month')} 日自動生成記錄。")

    elif callback_data == "rec_cancel":
        delete_conversation(user_id)
        edit_message_text(chat_id, message_id, "❌ 已取消。")


def _save_recurring_template(owner_id, data):
    from bot_utils import generate_ulid, next_short_id
    ulid = generate_ulid()
    sid = next_short_id(ENTITY_FIN_RECURRING)
    status = FIN_RECURRING_STATUS_ACTIVE
    item = {
        "PK": f"USER#{owner_id}",
        "SK": f"FIN_RECURRING#{ulid}",
        "GSI1PK": f"USER#{owner_id}#FIN_RECURRING",
        "GSI1SK": f"{status}#{ulid}",
        "GSI3PK": ENTITY_FIN_RECURRING,
        "GSI3SK": f"{sid:05d}",
        "entity_type": ENTITY_FIN_RECURRING,
        "title": data["title"],
        "amount": Decimal(str(data["amount"])),
        "fin_type": data["fin_type"],
        "day_of_month": data["day_of_month"],
        "category": data.get("category", "other"),
        "end_month": data.get("end_month"),
        "notes": data.get("notes"),
        "status": status,
        "short_id": sid,
    }
    put_item(item)
```

**Step 4: Run tests:**

```bash
pytest tests/test_recurring_handler.py::TestAddRecurringConversation -v
```

**Step 5: Commit:**

```bash
git add webhook_handler/handlers/recurring.py tests/test_recurring_handler.py
git commit -m "feat: add /add_recurring conversation flow"
```

---

### Task 6: Recurring — /edit_recurring conversation

**Files:**
- Modify: `webhook_handler/handlers/recurring.py`
- Modify: `tests/test_recurring_handler.py`

**Step 1: Write failing tests** — add to `tests/test_recurring_handler.py`:

```python
from handlers.recurring import handle_edit_recurring


class TestEditRecurring:
    def test_not_found_shows_error(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.query_gsi3", return_value=None), \
             patch("handlers.recurring.send_message") as mock_send:
            handle_edit_recurring(USER_ID, CHAT_ID, "99")
            assert "❌" in mock_send.call_args[0][1]

    def test_found_starts_conversation(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.query_gsi3", return_value=_template()), \
             patch("handlers.recurring.set_conversation") as mock_conv, \
             patch("handlers.recurring.send_message") as mock_send:
            handle_edit_recurring(USER_ID, CHAT_ID, "1")
            assert mock_conv.called
            assert "標題" in mock_send.call_args[0][1]
```

**Step 2: Run to verify failure:**

```bash
pytest tests/test_recurring_handler.py::TestEditRecurring -v
```

**Step 3: Add to `recurring.py`:**

```python
# ================================================================
#  /edit_recurring ID
# ================================================================

def handle_edit_recurring(user_id, chat_id, args):
    owner_id = get_owner_id()
    if not args.strip():
        send_message(chat_id, "❌ 請提供 ID，例如：`/edit_recurring 1`")
        return
    template = _find_template(owner_id, args.strip())
    if not template:
        send_message(chat_id, "❌ 找不到此週期記錄。")
        return
    # Pre-populate data with existing values
    data = {
        "_module": CONV_MODULE_EDIT_RECURRING,
        "_sk": template["SK"],
        "title": template.get("title", ""),
        "amount": int(template.get("amount", 0)),
        "fin_type": template.get("fin_type", "income"),
        "day_of_month": template.get("day_of_month", 1),
        "category": template.get("category", "other"),
        "end_month": template.get("end_month"),
        "notes": template.get("notes"),
        "status": template.get("status", FIN_RECURRING_STATUS_ACTIVE),
    }
    set_conversation(user_id, {"module": CONV_MODULE_EDIT_RECURRING, "step": 1, "data": data})
    current = data["title"]
    send_message(chat_id, f"✏️ *編輯週期記錄*\n\n第 1 步：標題（目前：{current}）\n輸入新標題或「跳過」保留原值：")


def _edit_recurring_step(user_id, chat_id, text, step, data):
    # Reuse add flow but with pre-populated defaults
    # Steps mirror add flow; "跳過" keeps existing value
    owner_id = get_owner_id()

    def keep_or_update(key, new_val):
        if text.strip().lower() in ("skip", "跳過", "-"):
            pass  # keep existing
        else:
            data[key] = new_val

    if step == 1:
        if text.strip().lower() not in ("skip", "跳過", "-"):
            data["title"] = text.strip()
        set_conversation(user_id, {"module": CONV_MODULE_EDIT_RECURRING, "step": 2, "data": data})
        send_message(chat_id, f"第 2 步：金額（目前：{data.get('amount', 0):,}）\n輸入新金額或「跳過」：")

    elif step == 2:
        if text.strip().lower() not in ("skip", "跳過", "-"):
            try:
                amt = int(text.strip().replace(",", ""))
                if amt <= 0:
                    raise ValueError
                data["amount"] = amt
            except ValueError:
                send_message(chat_id, "❌ 請輸入正整數金額或「跳過」：")
                return
        set_conversation(user_id, {"module": CONV_MODULE_EDIT_RECURRING, "step": 4, "data": data})
        send_message(chat_id, f"第 4 步：每月幾號（目前：{data.get('day_of_month', 1)}）\n輸入新日期（1–28）或「跳過」：")

    elif step == 4:
        if text.strip().lower() not in ("skip", "跳過", "-"):
            try:
                day = int(text.strip())
                if not 1 <= day <= 28:
                    raise ValueError
                data["day_of_month"] = day
            except ValueError:
                send_message(chat_id, "❌ 請輸入 1–28 的整數或「跳過」：")
                return
        set_conversation(user_id, {"module": CONV_MODULE_EDIT_RECURRING, "step": 6, "data": data})
        end_cur = data.get("end_month") or "無"
        send_message(chat_id, f"第 6 步：結束月份（目前：{end_cur}）\n輸入 YYYY-MM 或「跳過」：")

    elif step == 6:
        import re
        txt = text.strip()
        if txt.lower() not in ("skip", "跳過", "-"):
            if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", txt):
                send_message(chat_id, "❌ 格式錯誤，請輸入 YYYY-MM 或「跳過」：")
                return
            data["end_month"] = txt
        set_conversation(user_id, {"module": CONV_MODULE_EDIT_RECURRING, "step": 7, "data": data})
        send_message(chat_id, "第 7 步：備註（目前：{}）\n輸入新備註或「跳過」：".format(data.get("notes") or "無"))

    elif step == 7:
        if text.strip().lower() not in ("skip", "跳過", "-"):
            data["notes"] = text.strip()
        set_conversation(user_id, {"module": CONV_MODULE_EDIT_RECURRING, "step": 8, "data": data})
        _show_add_confirm(chat_id, data)

    elif step == 8:
        send_message(chat_id, "請點選下方按鈕確認或取消。")
```

Also add to `handle_callback` — after `rec_confirm` branch, add an edit-confirm handler:

```python
    elif callback_data == "rec_edit_confirm":
        _apply_edit_recurring(owner_id, user_id, data)
        delete_conversation(user_id)
        edit_message_text(chat_id, message_id,
            f"✅ 已更新週期記錄「{data.get('title')}」。\n當月已生成的記錄已同步更新。")
```

And the `_apply_edit_recurring` helper:

```python
def _apply_edit_recurring(owner_id, user_id, data):
    sk = data["_sk"]
    ulid = sk.split("#", 1)[1]
    status = data.get("status", FIN_RECURRING_STATUS_ACTIVE)
    updates = {
        "title": data["title"],
        "amount": Decimal(str(data["amount"])),
        "fin_type": data["fin_type"],
        "day_of_month": data["day_of_month"],
        "category": data.get("category", "other"),
        "end_month": data.get("end_month"),
        "notes": data.get("notes"),
        "GSI1SK": f"{status}#{ulid}",
    }
    update_item(f"USER#{owner_id}", sk, updates=updates)

    # Overwrite this month's generated FIN record if it exists
    from bot_utils import get_today
    month_prefix = get_today()[:7]
    from bot_db import query_gsi1 as _q
    from bot_constants import FIN_TYPE_INCOME, FIN_TYPE_EXPENSE
    fin_items = _q(
        gsi1pk=f"USER#{owner_id}#FIN#{data['fin_type']}",
        sk_condition=__import__("boto3").dynamodb.conditions.Key("GSI1SK").begins_with(month_prefix),
    )
    for item in fin_items:
        if item.get("recurring_id") == ulid:
            update_item(item["PK"], item["SK"], updates={
                "title": data["title"],
                "amount": Decimal(str(data["amount"])),
                "category": data.get("category", "other"),
                "notes": data.get("notes"),
            })
            break
```

**Step 4: Run tests:**

```bash
pytest tests/test_recurring_handler.py -v
```

**Step 5: Commit:**

```bash
git add webhook_handler/handlers/recurring.py tests/test_recurring_handler.py
git commit -m "feat: add /edit_recurring conversation with current-month propagation"
```

---

### Task 7: Router — Wire new commands

**Files:**
- Modify: `webhook_handler/handlers/router.py`

**Step 1: Add imports to router.py** — in the `from bot_constants import (...)` block add:

```python
    CONV_MODULE_ADD_RECURRING,
    CONV_MODULE_EDIT_RECURRING,
```

**Step 2: Add finance routes in `_route_command`** after `/edit_fin` route (around line 200):

```python
    elif cmd == "/statement":
        from handlers.finance import handle_statement
        handle_statement(user_id, chat_id, args)

    elif cmd == "/add_recurring":
        from handlers.recurring import handle_add_recurring
        handle_add_recurring(user_id, chat_id)

    elif cmd == "/recurring":
        from handlers.recurring import handle_recurring
        handle_recurring(user_id, chat_id)

    elif cmd == "/edit_recurring":
        from handlers.recurring import handle_edit_recurring
        handle_edit_recurring(user_id, chat_id, args)

    elif cmd == "/del_recurring":
        from handlers.recurring import handle_del_recurring
        handle_del_recurring(user_id, chat_id, args)

    elif cmd == "/pause_recurring":
        from handlers.recurring import handle_pause_recurring
        handle_pause_recurring(user_id, chat_id, args)

    elif cmd == "/resume_recurring":
        from handlers.recurring import handle_resume_recurring
        handle_resume_recurring(user_id, chat_id, args)
```

**Step 3: Add to conversation dispatch** — in the `_dispatch_conversation_step` function, add:

```python
    elif module == CONV_MODULE_ADD_RECURRING or module == CONV_MODULE_EDIT_RECURRING:
        from handlers.recurring import handle_step as recurring_step
        recurring_step(user_id, chat_id, text, step, data)
```

**Step 4: Add to callback dispatch** — in `_handle_callback_query`, add:

```python
    elif callback_data.startswith("rec_"):
        from handlers.recurring import handle_callback as recurring_cb
        recurring_cb(user_id, chat_id, message_id, callback_data, step, data)
```

**Step 5: Run full test suite:**

```bash
pytest tests/ -v
```

**Step 6: Commit:**

```bash
git add webhook_handler/handlers/router.py
git commit -m "feat: wire recurring and statement routes in router"
```

---

### Task 8: Morning reminder — 1st-of-month auto-generation

**Files:**
- Modify: `reminder_handler/reminders/db_queries.py`
- Modify: `reminder_handler/reminders/reminder_service.py`
- Modify: `tests/test_reminder_service.py`

**Step 1: Add DB query to `db_queries.py`** (after `get_health_settings`):

```python
def get_active_recurring_templates(owner_id):
    """All active recurring finance templates for the given owner."""
    return _db_query_gsi1(
        gsi1pk=f"USER#{owner_id}#FIN_RECURRING",
        sk_condition=Key("GSI1SK").begins_with("active#"),
    )


def get_fin_records_for_month(owner_id, fin_type, month_prefix):
    """FIN records of a given type for a month (for dedup check)."""
    return _db_query_gsi1(
        gsi1pk=f"USER#{owner_id}#FIN#{fin_type}",
        sk_condition=Key("GSI1SK").begins_with(month_prefix),
    )
```

**Step 2: Write failing tests** — add to `tests/test_reminder_service.py`:

```python
class TestFirstOfMonthGeneration:
    def _make_svc(self, day=1):
        import datetime
        svc = object.__new__(ReminderService)
        today = datetime.date(2026, 4, day)
        svc.today = today
        svc.today_s = today.isoformat()
        svc.wd = WEEKDAYS[today.weekday()]
        svc.end_s = (today + timedelta(days=3)).isoformat()
        return svc

    def test_generates_record_on_first_of_month(self):
        from decimal import Decimal
        template = {
            "SK": "FIN_RECURRING#ULID001",
            "title": "薪水",
            "amount": Decimal("20000"),
            "fin_type": "income",
            "day_of_month": 1,
            "category": "salary",
            "end_month": None,
            "status": "active",
        }
        svc = self._make_svc(day=1)
        with patch("reminders.reminder_service.get_owner_id", return_value=111), \
             patch("reminders.reminder_service.get_active_recurring_templates", return_value=[template]), \
             patch("reminders.reminder_service.get_fin_records_for_month", return_value=[]), \
             patch("reminders.reminder_service.put_item") as mock_put:
            result = svc._generate_recurring_records()
            assert mock_put.called
            assert result == 1  # 1 record generated

    def test_skips_if_record_already_exists(self):
        from decimal import Decimal
        template = {
            "SK": "FIN_RECURRING#ULID001",
            "title": "薪水",
            "amount": Decimal("20000"),
            "fin_type": "income",
            "day_of_month": 1,
            "category": "salary",
            "end_month": None,
            "status": "active",
        }
        existing_fin = {"recurring_id": "ULID001", "title": "薪水"}
        svc = self._make_svc(day=1)
        with patch("reminders.reminder_service.get_owner_id", return_value=111), \
             patch("reminders.reminder_service.get_active_recurring_templates", return_value=[template]), \
             patch("reminders.reminder_service.get_fin_records_for_month", return_value=[existing_fin]), \
             patch("reminders.reminder_service.put_item") as mock_put:
            result = svc._generate_recurring_records()
            assert not mock_put.called
            assert result == 0

    def test_not_first_of_month_skips(self):
        svc = self._make_svc(day=5)
        with patch("reminders.reminder_service.get_owner_id", return_value=111), \
             patch("reminders.reminder_service.get_active_recurring_templates") as mock_q:
            result = svc._generate_recurring_records()
            assert not mock_q.called
            assert result == 0
```

**Step 3: Run to verify failure:**

```bash
pytest tests/test_reminder_service.py::TestFirstOfMonthGeneration -v
```

**Step 4: Update `reminder_service.py`:**

Add imports at top:

```python
from bot_db import put_item
from bot_utils import generate_ulid
from .db_queries import (
    ...existing...,
    get_active_recurring_templates,
    get_fin_records_for_month,
)
```

Add `_generate_recurring_records` method to `ReminderService`:

```python
def _generate_recurring_records(self):
    """Auto-generate FIN records from recurring templates on the 1st of the month."""
    if self.today.day != 1:
        return 0

    owner_id = get_owner_id()
    templates = get_active_recurring_templates(owner_id)
    month_prefix = self.today_s[:7]
    generated = 0

    for t in templates:
        # Check if end_month passed
        end_month = t.get("end_month")
        if end_month and end_month < month_prefix:
            # Mark completed (best-effort; skip if update fails)
            continue

        fin_type = t.get("fin_type", "income")
        ulid = t["SK"].split("#", 1)[1]

        # Check for existing generated record this month
        existing = get_fin_records_for_month(owner_id, fin_type, month_prefix)
        if any(r.get("recurring_id") == ulid for r in existing):
            continue

        # Create FIN record
        day = t.get("day_of_month", 1)
        record_date = f"{month_prefix}-{day:02d}"
        new_ulid = generate_ulid()
        item = {
            "PK": f"USER#{owner_id}",
            "SK": f"FIN#{new_ulid}",
            "GSI1PK": f"USER#{owner_id}#FIN#{fin_type}",
            "GSI1SK": f"{record_date}#{new_ulid}",
            "GSI3PK": "FIN",
            "GSI3SK": f"{_next_fin_short_id(owner_id):05d}",
            "entity_type": "FIN",
            "fin_type": fin_type,
            "title": t.get("title", ""),
            "amount": t.get("amount"),
            "date": record_date,
            "category": t.get("category", "other"),
            "notes": t.get("notes"),
            "status": "paid",
            "recurring_id": ulid,
        }
        put_item(item)
        generated += 1

    return generated
```

Note: `_next_fin_short_id` is a helper — use `next_short_id("FIN")` from `bot_utils` if it exists, or use a counter pattern.

In `morning_briefing`, after `secs = [...]` header block, add:

```python
        # Auto-generate recurring records on the 1st
        generated = self._generate_recurring_records()
        if generated > 0:
            secs.append(f"🔄 已自動新增 {generated} 筆週期財務記錄")
```

**Step 5: Run tests:**

```bash
pytest tests/test_reminder_service.py -v
```

**Step 6: Commit:**

```bash
git add reminder_handler/reminders/db_queries.py reminder_handler/reminders/reminder_service.py tests/test_reminder_service.py
git commit -m "feat: auto-generate recurring finance records on 1st of month in morning reminder"
```

---

### Task 9: Help module update

**Files:**
- Modify: `webhook_handler/handlers/help_module.py`

**Step 1: Add recurring commands to overview** — in the `*💰 財務管理*` section, add after the existing finance lines:

```python
"/add\\_recurring — 新增週期收入/支出\n"
"/recurring — 查看週期記錄\n"
"/statement `[YYYY-MM]` — 月度收支明細\n\n"
```

**Step 2: Update finance module detail** — in `_HELP_MODULES["finance"]["content"]`, add a new section before `*💡 小提示*`:

```python
"*週期記錄*\n"
"• /add\\_recurring — 新增每月自動記錄（薪水、租金等）\n"
"• /recurring — 查看所有週期記錄\n"
"• `/edit_recurring ID` — 編輯（更新當月及未來記錄）\n"
"• `/del_recurring ID` — 刪除（過去記錄不受影響）\n"
"• `/pause_recurring ID` — 暫停 / `/resume_recurring ID` — 恢復\n\n"
"*月度收支明細*\n"
"• /statement — 本月所有收入、支出、付款明細\n"
"• `/statement 2026-03` — 指定月份明細\n\n"
```

**Step 3: Update finance summary description** — in the `*月度統計*` section, add:

```python
"• 淨額分為「已結清」和「含待付」兩行\n"
"• 自動扣除當月訂閱費用\n"
```

**Step 4: Add aliases** — in `_HELP_ALIASES`:

```python
"recurring":  "finance",
"週期":       "finance",
```

**Step 5: Run full tests:**

```bash
pytest tests/ -v
```

**Step 6: Commit:**

```bash
git add webhook_handler/handlers/help_module.py
git commit -m "docs: update help module with recurring and statement commands"
```

---

### Task 10: Final verification and deploy

**Step 1: Syntax check all changed files:**

```bash
python -c "import ast; [ast.parse(open(f, encoding='utf-8').read()) or print(f, 'OK') for f in [
  'shared/python/bot_constants.py',
  'webhook_handler/handlers/finance.py',
  'webhook_handler/handlers/recurring.py',
  'webhook_handler/handlers/router.py',
  'webhook_handler/handlers/help_module.py',
  'reminder_handler/reminders/db_queries.py',
  'reminder_handler/reminders/reminder_service.py',
]]"
```

**Step 2: Full test suite:**

```bash
pytest tests/ -v
```
Expected: all tests pass.

**Step 3: Show git log:**

```bash
git log --oneline -12
```

**Step 4: Deploy:**

```bash
bash scripts/deploy.sh
```

**Step 5: Push:**

```bash
git push
```