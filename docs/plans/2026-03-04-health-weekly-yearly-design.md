# Health Module — Weekly & Yearly Review + TDEE-Fill Design

**Date:** 2026-03-04
**Status:** Approved

---

## Overview

Extend the existing `/health` command with two new report modes (weekly and yearly) and add a TDEE-fill rule that substitutes a day's missing-meal calories with TDEE across all report views.

---

## Command Parsing

`handle_health(user_id, chat_id, args)` gains two new patterns:

| Input | Behaviour |
|---|---|
| `/health` | Today summary (existing) |
| `/health week` | Current week Mon → today |
| `/health 2026-03` | Monthly report (existing) |
| `/health 2026` | Yearly report (new) |

Error message updated to list all four valid formats.

---

## TDEE-Fill Rule

**Helper:** `_effective_daily_calories(meal_map, tdee) -> (int, bool)`

- `meal_map`: `{meal_type: calories}` for a single day
- If `tdee` is not `None` AND any of `breakfast`, `lunch`, `dinner` is absent → return `(tdee, True)`
- Otherwise → return `(sum(meal_map.values()), False)`

Returns a `(calories, was_filled)` tuple so callers can count filled days and show indicators.

**Applied in:**
- Today summary: show `⚠️ 缺少主食記錄，以 TDEE 計算：X,XXX kcal` and use TDEE for goal-progress
- Weekly report: per-day display and averages
- Monthly report: averages and goal-hit counts
- Yearly report: averages, goal-hit counts, and per-month breakdown

**Not filled:** Days with zero meal records at all (no data = excluded from averages, shown as `（無記錄）`).

---

## Weekly Report (`/health week`)

**Range:** Monday of current week → today (no future days).

**Data fetch:** Single GSI1 query with `begins_with("YYYY-Wxx-start")` → actually query each day individually or query the whole week prefix. Implementation fetches all meals where `GSI1SK` begins with the week's Monday date prefix and groups by date.

**Format:**
```
📊 *本週飲食記錄*
📆 2026-03-02（週一）~ 2026-03-08（週日）
──────────────────────
週一 2026-03-02：1,800 kcal ✅
週二 2026-03-03：2,200 kcal ⚠️
週三 2026-03-04：⚠️ 缺主食，以 TDEE 計 2,500 kcal
週四 2026-03-05：（無記錄）
──────────────────────
平均日攝取：2,029 kcal（含 TDEE 填補：1 天）
🎯 每日目標：2,000 kcal
✅ 達標天數：3 天 / ⚠️ 超標天數：2 天
```

**Rules:**
- Days with any records but missing B/L/D → TDEE-fill, show `⚠️ 缺主食，以 TDEE 計`
- Days with zero records → `（無記錄）`, excluded from average
- Averages include TDEE-filled days, exclude empty days

---

## Yearly Report (`/health 2026`)

**Data fetch:** 12 separate month-prefix GSI1 queries (one per month), or a single query with `begins_with("2026-")`.

**Format:**
```
📊 *2026 年健康年報*
──────────────────────
📅 有記錄天數：45 天（含 TDEE 填補：5 天）
🔥 平均日攝取：1,950 kcal
🎯 每日目標：2,000 kcal
✅ 達標天數：32 天 / ⚠️ 超標天數：13 天
──────────────────────
*月份摘要*
01月：平均 1,900 kcal — ✅ 20天 ⚠️ 5天
02月：平均 2,050 kcal — ✅ 10天 ⚠️ 15天
03月：平均 1,950 kcal — ✅ 2天 ⚠️ 3天
──────────────────────
全年總攝取：87,750 kcal
目標合計：730,000 kcal（365天 × 2,000）
```

**Rules:**
- Month rows only shown for months with at least one record
- Target total = `daily_goal × days_in_year`

---

## Today Summary Changes

Add TDEE-fill warning below the meal list when any main meal is missing and settings exist:

```
⚠️ 缺少主食記錄，以 TDEE 計算：2,500 kcal

📊 *目標進度*
...
```

Goal-progress section uses effective calories (TDEE) instead of actual sum.

---

## Monthly Report Changes

`_render_monthly_report` updated to apply `_effective_daily_calories` per day when computing:
- `avg_intake`
- `days_ok` / `days_over`
- `total_intake`

Adds `（含 TDEE 填補：N 天）` note in the header if any days were filled.

---

## Files Changed

| File | Change |
|---|---|
| `webhook_handler/handlers/health.py` | Add `_effective_daily_calories`, `_get_week_range`, `_render_weekly_report`, `_render_yearly_report`; update `handle_health`, `_render_today_summary`, `_render_monthly_report` |
| `webhook_handler/handlers/help_module.py` | Update health command examples to show `/health week` and `/health 2026` |
| `tests/test_health_handler.py` | Tests for new helpers, TDEE-fill logic, weekly and yearly renderers |

---

## Out of Scope

- Editing past meal entries
- Daily calorie breakdown chart
- Notifications when daily goal is exceeded
