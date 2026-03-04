# Reminder Handler — Evening Health Report + Morning Todo Count Design

**Date:** 2026-03-04
**Status:** Approved

---

## Overview

Two additions to the scheduled reminder handler:

1. **Morning briefing (08:00):** Always show total pending todo count, even when no todos fall within the 3-day urgency window.
2. **Evening preview (21:00):** Append a today's health summary section showing meals recorded, total kcal, and goal progress.

---

## Change 1 — Morning: Always Show Todo Count

**Current behaviour:** `_sec_todos` returns `None` (section omitted) when no todos are overdue, due today, or due within 3 days — even if many pending todos exist.

**New behaviour:** If any pending todos exist, always emit the section with the total count in the header. When nothing is urgently due, show a "no urgent items" line instead of the detailed breakdown.

**Format — urgently due items exist:**
```
📝 *待辦事項（共 8 項）*
⚠️ *逾期 1 項*
  🔴 Buy groceries（逾期 2 天）
📌 *3 天內 1 項*
  • Update docs（明天）
```

**Format — todos exist but none urgently due:**
```
📝 *待辦事項（共 8 項）*
無近期到期項目。
```

**Format — zero todos:** section omitted entirely (no change from current).

---

## Change 2 — Evening: Today's Health Section

A new `_sec_health()` section builder added to `ReminderService` and called at the end of `evening_preview` (after the existing sections, before the sign-off footer).

**Data sources:**
- `get_today_meals(owner_id, date_str)` — new function in `db_queries.py`; queries GSI1 with `USER#{owner_id}#HEALTH` and `begins_with(date_str)`
- `get_health_settings(owner_id)` — new function in `db_queries.py`; calls `get_item(f"USER#{owner_id}", "HEALTH_SETTINGS#active")`

**TDEE-fill rule:** same as health module — if any of breakfast/lunch/dinner is missing and TDEE is configured, treat that day as TDEE calories and show warning.

**Format — meals recorded, settings configured:**
```
🥗 *今日健康*
🌅 早餐：650 kcal
☀️ 午餐：（未記錄）
🌙 晚餐：800 kcal
🍎 其他：（未記錄）
──────────────────────
總攝取：1,450 kcal
⚠️ 缺少主食記錄，以 TDEE 計算：2,200 kcal
每日目標：1,700 kcal  超出：500 kcal ⚠️
```

**Format — meals recorded, no settings:**
```
🥗 *今日健康*
🌅 早餐：650 kcal
...
總攝取：1,450 kcal
```

**Section omitted entirely when:** no meals recorded for today.

---

## Files Changed

| File | Change |
|---|---|
| `reminder_handler/reminders/db_queries.py` | Add `get_today_meals(owner_id, date_str)` and `get_health_settings(owner_id)`; add `get_item` import from `bot_db` |
| `reminder_handler/reminders/reminder_service.py` | Update `_sec_todos` to show count always; add `_sec_health` method; call it in `evening_preview` |
| `tests/test_reminder_service.py` | New test file covering both changes |

---

## Out of Scope

- Morning health summary
- Weekly/monthly health stats in reminders
- Editing todos or meals from reminders