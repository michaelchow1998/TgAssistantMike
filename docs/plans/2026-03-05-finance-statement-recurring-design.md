# Finance: Statement + Recurring Transactions + Summary Fix — Design

**Date:** 2026-03-05

## Goals

1. `/statement [YYYY-MM]` — monthly income/expense/payment statement
2. Recurring income/expense templates — auto-generate records each month
3. `/finance_summary` fix — two net lines (已結清 / 含待付) + subscription deduction

---

## Feature 1: `/statement [YYYY-MM]`

### Command

- `/statement` → current month
- `/statement 2026-03` → specific month

### Output format

```
💰 *2026-03 收支明細*
──────────────────────
📈 *收入（N 筆）*
  • 薪水：+20,000
  • 兼職：+5,000
  小計：+25,000

📉 *支出（N 筆）*
  • 超市：-500
  • 交通：-200
  小計：-700

💳 *付款 — 已付（N 筆）*
  • 租金：-8,000
💳 *付款 — 待付（N 筆）*
  • 信用卡：-3,000（到期 03-15）
──────────────────────
✅ 已結清淨額：+16,300
📊 含待付淨額：+13,300
```

### Implementation notes

- Query GSI1 for each fin_type (income, expense, payment) with `begins_with(month_prefix)`
- Income and expense records always show (status is always `paid` after creation)
- Payments split into paid vs pending by `status` field
- No subscription deduction in statement (statement is raw records only)

---

## Feature 2: Recurring Templates

### New entity: `ENTITY_FIN_RECURRING = "FIN_RECURRING"`

**DynamoDB schema:**

| Key | Value |
|-----|-------|
| PK | `USER#{owner_id}` |
| SK | `FIN_RECURRING#{ULID}` |
| GSI1PK | `USER#{owner_id}#FIN_RECURRING` |
| GSI1SK | `{fin_type}#{ULID}` |
| GSI3PK | `FIN_RECURRING` |
| GSI3SK | `{short_id}` (zero-padded 5 digits) |

**Fields:**

| Field | Type | Notes |
|-------|------|-------|
| `title` | str | e.g. "薪水" |
| `amount` | Decimal | positive value |
| `fin_type` | str | `income` or `expense` only (not payment) |
| `day_of_month` | int | 1–28 (day to "date" the generated record) |
| `category` | str | same categories as regular finance |
| `end_month` | str? | optional YYYY-MM; `None` = indefinite |
| `status` | str | `active` / `paused` / `completed` |
| `notes` | str? | optional |
| `short_id` | int | human-facing ID |

### New commands

| Command | Purpose |
|---------|---------|
| `/add_recurring` | Multi-step conversation: title → amount → fin_type → day_of_month → category → end_month (optional) → notes (optional) → confirm |
| `/recurring` | List all active + paused templates |
| `/edit_recurring ID` | Edit template fields; overwrites this month's already-generated record if it exists |
| `/del_recurring ID` | Delete template (stops future generation; past FIN records untouched) |
| `/pause_recurring ID` | Pause without deleting |
| `/resume_recurring ID` | Resume a paused template |

### Auto-generation logic (morning reminder, 1st of month)

1. Query all `active` recurring templates for the owner
2. For each template:
   a. Check if `end_month` is set and has passed → mark template `completed`, skip
   b. Compute `record_date = f"{current_year}-{current_month:02d}-{day_of_month:02d}"`
   c. Check if a FIN record with `recurring_id = template_id` already exists for this month → skip if yes
   d. Create FIN record with `recurring_id` field linking back to the template
3. Append to morning briefing: `"🔄 已自動新增 N 筆週期記錄：薪水、租金"`

### Edit propagation

When `/edit_recurring ID` updates the template:
- Find the FIN record for the current month with matching `recurring_id` → overwrite its fields
- All future months will use updated template on next generation

### Link field on generated FIN records

Generated FIN records get an extra attribute: `recurring_id = template ULID`
This is only used for edit propagation; it does not change any existing GSI patterns.

---

## Feature 3: Finance Summary Fix

### Two net lines (replaces single net line)

```
✅ 已結清淨額：+16,000
   （收入 − 支出 − 已付款 − 當月訂閱）
📊 含待付淨額：+13,000
   （再扣除待付款項）
```

### Subscription deduction

- Query all **active** subscriptions where `next_due` starts with `YYYY-MM` (the month being summarised)
- Sum their `amount` fields
- Deduct from **both** net lines (subscription charges are definite outflows regardless of pending/paid distinction)

### Updated formula

```
subscription_total = sum(amount for sub where next_due starts with month_prefix and status == active)
已結清淨額 = total_income - total_expense - total_paid_payments - subscription_total
含待付淨額 = 已結清淨額 - total_pending_payments
```

---

## Files to modify/create

| File | Change |
|------|--------|
| `shared/python/bot_constants.py` | Add `ENTITY_FIN_RECURRING`, `CONV_MODULE_ADD_RECURRING`, `CONV_MODULE_EDIT_RECURRING`, status constants, display names |
| `webhook_handler/handlers/finance.py` | Add `/statement`, update `finance_summary` two-net logic |
| `webhook_handler/handlers/recurring.py` | New handler: all recurring template commands |
| `webhook_handler/handlers/router.py` | Route new commands + conversations |
| `webhook_handler/handlers/help_module.py` | Add recurring commands to finance + overview sections |
| `reminder_handler/reminders/reminder_service.py` | Add 1st-of-month recurring generation in `morning_briefing` |
| `reminder_handler/reminders/db_queries.py` | Add queries for recurring templates and active subscriptions |
| `tests/test_finance_handler.py` | New tests for statement and summary fix |
| `tests/test_recurring_handler.py` | New tests for recurring handler |
| `tests/test_notifier.py` | Update morning briefing tests for 1st-of-month generation |
