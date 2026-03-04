# Health Weekly/Yearly Review + TDEE-Fill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `/health week` (weekly review), `/health 2026` (yearly review), and a TDEE-fill rule that substitutes missing-main-meal days with TDEE calories across all report contexts.

**Architecture:** All changes are confined to `webhook_handler/handlers/health.py` (new helpers + updated renderers + updated command parser) and `help_module.py` (updated examples). A single `_effective_daily_calories(meal_map, tdee)` helper drives the TDEE-fill logic uniformly. Tests live in `tests/test_health_handler.py`.

**Tech Stack:** Python 3.13, pytest, unittest.mock, boto3 DynamoDB conditions (Key.between / begins_with)

---

## Context

- `query_gsi1(gsi1pk, sk_condition)` accepts `Key("GSI1SK").between(start, end)` — confirmed in `shared/python/bot_db.py:144`
- Mock pattern: patch at `handlers.health.<name>` not source module
- All messages Traditional Chinese
- Run tests with: `pytest tests/test_health_handler.py -v`

---

### Task 1: `_effective_daily_calories` helper

**Files:**
- Modify: `webhook_handler/handlers/health.py` (add after `_parse_non_negative_int`)
- Test: `tests/test_health_handler.py` (add `TestEffectiveDailyCalories` class)

**Step 1: Write the failing tests**

Add to `tests/test_health_handler.py` (after existing imports, add `_effective_daily_calories` to the import block):

```python
from handlers.health import (
    handle_set_health,
    handle_add_meal,
    handle_health,
    handle_step,
    handle_callback,
    _parse_calories,
    _parse_positive_int,
    _parse_non_negative_int,
    _effective_daily_calories,   # ADD THIS
)
```

Then add the test class:

```python
class TestEffectiveDailyCalories:
    def test_all_three_main_meals_present_returns_actual_sum(self):
        meal_map = {"breakfast": 500, "lunch": 700, "dinner": 600}
        calories, filled = _effective_daily_calories(meal_map, tdee=2000)
        assert calories == 1800
        assert filled is False

    def test_with_other_meal_also_all_main_present(self):
        meal_map = {"breakfast": 500, "lunch": 700, "dinner": 600, "other": 200}
        calories, filled = _effective_daily_calories(meal_map, tdee=2000)
        assert calories == 2000
        assert filled is False

    def test_missing_breakfast_returns_tdee(self):
        meal_map = {"lunch": 700, "dinner": 600}
        calories, filled = _effective_daily_calories(meal_map, tdee=2200)
        assert calories == 2200
        assert filled is True

    def test_missing_lunch_returns_tdee(self):
        meal_map = {"breakfast": 500, "dinner": 600}
        calories, filled = _effective_daily_calories(meal_map, tdee=2200)
        assert calories == 2200
        assert filled is True

    def test_missing_dinner_returns_tdee(self):
        meal_map = {"breakfast": 500, "lunch": 700}
        calories, filled = _effective_daily_calories(meal_map, tdee=2200)
        assert calories == 2200
        assert filled is True

    def test_empty_meal_map_with_tdee_returns_tdee(self):
        meal_map = {}
        calories, filled = _effective_daily_calories(meal_map, tdee=2200)
        assert calories == 2200
        assert filled is True

    def test_no_tdee_returns_actual_sum_regardless_of_missing(self):
        meal_map = {"breakfast": 500}   # missing lunch + dinner
        calories, filled = _effective_daily_calories(meal_map, tdee=None)
        assert calories == 500
        assert filled is False

    def test_only_other_meal_with_tdee_returns_tdee(self):
        meal_map = {"other": 300}   # no main meals
        calories, filled = _effective_daily_calories(meal_map, tdee=2000)
        assert calories == 2000
        assert filled is True
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_health_handler.py::TestEffectiveDailyCalories -v
```
Expected: ImportError or NameError — `_effective_daily_calories` not defined yet.

**Step 3: Add implementation** at the end of `webhook_handler/handlers/health.py`:

```python
def _effective_daily_calories(meal_map, tdee):
    """
    Returns (effective_calories: int, was_filled: bool).
    If tdee is set and any of breakfast/lunch/dinner is missing from meal_map,
    return tdee as a conservative estimate for that day.
    """
    if tdee is not None:
        main_meals = {"breakfast", "lunch", "dinner"}
        if not main_meals.issubset(meal_map.keys()):
            return tdee, True
    return sum(meal_map.values()), False
```

**Step 4: Run to verify pass**

```bash
pytest tests/test_health_handler.py::TestEffectiveDailyCalories -v
```
Expected: 8 passed.

**Step 5: Commit**

```bash
git add webhook_handler/handlers/health.py tests/test_health_handler.py
git commit -m "feat: add _effective_daily_calories helper with TDEE-fill logic"
```

---

### Task 2: `_get_week_range` helper

**Files:**
- Modify: `webhook_handler/handlers/health.py` (add after `_get_meals_for_month`)
- Test: `tests/test_health_handler.py` (add `TestGetWeekRange` class)

**Step 1: Write the failing tests**

Add to `tests/test_health_handler.py` imports:

```python
from handlers.health import (
    ...
    _effective_daily_calories,
    _get_week_range,   # ADD THIS
)
```

Add test class:

```python
class TestGetWeekRange:
    def test_monday_returns_same_day_as_start(self):
        monday, end = _get_week_range("2026-03-02")   # Monday
        assert monday == "2026-03-02"
        assert end == "2026-03-02"

    def test_wednesday_returns_monday_as_start(self):
        monday, end = _get_week_range("2026-03-04")   # Wednesday
        assert monday == "2026-03-02"
        assert end == "2026-03-04"

    def test_sunday_returns_monday_as_start(self):
        monday, end = _get_week_range("2026-03-08")   # Sunday
        assert monday == "2026-03-02"
        assert end == "2026-03-08"

    def test_week_spanning_month_boundary(self):
        # 2026-03-02 (Mon) ~ 2026-03-01 is Sunday of previous week
        # Test a Thursday in a week that started in Feb
        monday, end = _get_week_range("2026-03-05")   # Thursday
        assert monday == "2026-03-02"
        assert end == "2026-03-05"
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_health_handler.py::TestGetWeekRange -v
```
Expected: ImportError — `_get_week_range` not defined.

**Step 3: Add implementation** in `webhook_handler/handlers/health.py`, after the existing imports (add `timedelta` to the datetime import) and add the function after `_get_meals_for_month`:

```python
# Add timedelta to existing datetime usage — add this import at top of file:
from datetime import datetime, timedelta
```

```python
def _get_week_range(today_str):
    """Return (monday_str, today_str) for the week containing today_str."""
    dt = datetime.strptime(today_str, "%Y-%m-%d")
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%Y-%m-%d"), today_str
```

**Step 4: Run to verify pass**

```bash
pytest tests/test_health_handler.py::TestGetWeekRange -v
```
Expected: 4 passed.

**Step 5: Commit**

```bash
git add webhook_handler/handlers/health.py tests/test_health_handler.py
git commit -m "feat: add _get_week_range helper"
```

---

### Task 3: Weekly report renderer + routing

**Files:**
- Modify: `webhook_handler/handlers/health.py`
  - Add `_get_meals_for_week` (after `_get_meals_for_month`)
  - Add `_render_weekly_report` (after `_render_monthly_report`)
  - Update `handle_health` to handle `args == "week"`
- Test: `tests/test_health_handler.py` (add `TestWeeklyReportContent` class)

**Step 1: Write the failing tests**

```python
class TestWeeklyReportContent:
    """Tests for /health week."""

    def _patch_week(self, meals, settings, today=TODAY, monday="2026-03-02"):
        """Helper context manager stack for weekly report tests."""
        return [
            patch("handlers.health.get_owner_id", return_value=OWNER_ID),
            patch("handlers.health.get_today", return_value=today),
            patch("handlers.health.query_gsi1", return_value=meals),
            patch("handlers.health.get_item", return_value=settings),
            patch("handlers.health.send_message"),
        ]

    def test_week_arg_triggers_weekly_report(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.query_gsi1", return_value=[]) as mock_query, \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "week")
            mock_send.assert_called_once()
            assert "本週" in mock_send.call_args[0][1]

    def test_days_with_no_records_shown_as_no_record(self):
        # TODAY = "2026-03-03" (Tuesday), so Mon=2026-03-02 is in range
        # No meals → both Mon and Tue show no-record
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.query_gsi1", return_value=[]), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "week")
            msg = mock_send.call_args[0][1]
            assert "無記錄" in msg

    def test_complete_day_shows_actual_calories(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("500"), "date": TODAY},
            {"meal_type": "lunch",     "calories": Decimal("700"), "date": TODAY},
            {"meal_type": "dinner",    "calories": Decimal("600"), "date": TODAY},
        ]
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "week")
            msg = mock_send.call_args[0][1]
            assert "1,800" in msg   # 500+700+600

    def test_incomplete_day_with_settings_shows_tdee_fill(self):
        # Only breakfast recorded → TDEE fill
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("500"), "date": TODAY},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "week")
            msg = mock_send.call_args[0][1]
            assert "缺主食" in msg
            assert "TDEE" in msg
            assert "2,200" in msg

    def test_average_excludes_empty_days(self):
        # TODAY=2026-03-03 (Tue). Only Tuesday has data, Monday has none.
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("600"), "date": TODAY},
            {"meal_type": "lunch",     "calories": Decimal("600"), "date": TODAY},
            {"meal_type": "dinner",    "calories": Decimal("600"), "date": TODAY},
        ]
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "week")
            msg = mock_send.call_args[0][1]
            # avg = 1800 / 1 recorded day (Monday has no records, excluded)
            assert "1,800" in msg

    def test_goal_stats_shown_when_settings_present(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("500"), "date": TODAY},
            {"meal_type": "lunch",     "calories": Decimal("600"), "date": TODAY},
            {"meal_type": "dinner",    "calories": Decimal("500"), "date": TODAY},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "week")
            msg = mock_send.call_args[0][1]
            assert "達標天數" in msg
            assert "超標天數" in msg

    def test_fill_count_shown_in_average_note(self):
        # Partial day → TDEE fill → note appears
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("500"), "date": TODAY},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "week")
            msg = mock_send.call_args[0][1]
            assert "TDEE 填補" in msg
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_health_handler.py::TestWeeklyReportContent -v
```
Expected: FAIL — `_render_weekly_report` not defined.

**Step 3: Add `_get_meals_for_week`** in `health.py` after `_get_meals_for_month`:

```python
def _get_meals_for_week(owner_id, monday_str, today_str):
    """Fetch all meal records between monday_str and today_str (inclusive)."""
    return query_gsi1(
        gsi1pk=f"USER#{owner_id}#HEALTH",
        sk_condition=Key("GSI1SK").between(monday_str, today_str + "#~"),
    )
```

**Step 4: Add `_render_weekly_report`** in `health.py` after `_render_monthly_report`:

```python
def _render_weekly_report(chat_id, owner_id, monday_str, today_str):
    meals = _get_meals_for_week(owner_id, monday_str, today_str)
    settings = _get_settings(owner_id)
    tdee = int(settings["tdee"]) if settings else None
    daily_goal = (int(settings["tdee"]) - int(settings["deficit"])) if settings else None

    # Group by date → {meal_type: calories}
    day_meal_maps = {}
    for meal in meals:
        d = meal["date"]
        if d not in day_meal_maps:
            day_meal_maps[d] = {}
        day_meal_maps[d][meal["meal_type"]] = int(meal["calories"])

    # Build ordered list of days Mon → today
    monday_dt = datetime.strptime(monday_str, "%Y-%m-%d")
    today_dt = datetime.strptime(today_str, "%Y-%m-%d")
    days = []
    cur = monday_dt
    while cur <= today_dt:
        days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    _WD = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
    lines = [
        "📊 *本週飲食記錄*",
        f"📆 {monday_str}（週一）~ {today_str}（{_WD[today_dt.weekday()]}）",
        "──────────────────────",
    ]

    counted_days = 0
    total_for_avg = 0
    fill_count = 0
    days_ok = 0
    days_over = 0

    for d in days:
        wd = _WD[datetime.strptime(d, "%Y-%m-%d").weekday()]
        meal_map = day_meal_maps.get(d)
        if not meal_map:
            lines.append(f"{wd} {d}：（無記錄）")
            continue
        effective, was_filled = _effective_daily_calories(meal_map, tdee)
        counted_days += 1
        total_for_avg += effective
        if was_filled:
            fill_count += 1
            lines.append(f"{wd} {d}：⚠️ 缺主食，以 TDEE 計 {effective:,} kcal")
        else:
            status = ""
            if daily_goal is not None:
                status = " ✅" if effective <= daily_goal else " ⚠️"
            lines.append(f"{wd} {d}：{effective:,} kcal{status}")
        if daily_goal is not None:
            if effective <= daily_goal:
                days_ok += 1
            else:
                days_over += 1

    lines.append("──────────────────────")
    avg = round(total_for_avg / counted_days) if counted_days > 0 else 0
    fill_note = f"（含 TDEE 填補：{fill_count} 天）" if fill_count > 0 else ""
    lines.append(f"平均日攝取：{avg:,} kcal{fill_note}")

    if daily_goal is not None:
        lines += [
            f"🎯 每日目標：{daily_goal:,} kcal",
            f"✅ 達標天數：{days_ok} 天 / ⚠️ 超標天數：{days_over} 天",
        ]

    send_message(chat_id, "\n".join(lines))
```

**Step 5: Update `handle_health`** — add `week` branch between the `if not args` block and the monthly regex:

```python
def handle_health(user_id, chat_id, args=""):
    owner_id = get_owner_id()
    args = (args or "").strip()

    if not args:
        _render_today_summary(chat_id, owner_id, get_today())
        return

    if args == "week":
        monday, today_end = _get_week_range(get_today())
        _render_weekly_report(chat_id, owner_id, monday, today_end)
        return

    m = re.match(r"^(\d{4})-(\d{2})$", args)
    if m and 1 <= int(m.group(2)) <= 12:
        _render_monthly_report(chat_id, owner_id, args)
        return

    m = re.match(r"^(\d{4})$", args)
    if m and 2000 <= int(m.group(1)) <= 2099:
        _render_yearly_report(chat_id, owner_id, args)
        return

    send_message(
        chat_id,
        "❌ 格式錯誤。\n\n用法：\n"
        "• `/health` — 今日飲食記錄\n"
        "• `/health week` — 本週記錄\n"
        "• `/health 2026-03` — 月報\n"
        "• `/health 2026` — 年報",
    )
```

**Step 6: Run to verify pass**

```bash
pytest tests/test_health_handler.py::TestWeeklyReportContent -v
```
Expected: 7 passed.

**Step 7: Commit**

```bash
git add webhook_handler/handlers/health.py tests/test_health_handler.py
git commit -m "feat: add weekly health report (/health week)"
```

---

### Task 4: Yearly report renderer + routing

**Files:**
- Modify: `webhook_handler/handlers/health.py` (add `_render_yearly_report`)
- Test: `tests/test_health_handler.py` (add `TestYearlyReportContent` class)

Note: `handle_health` already has the yearly routing from Task 3 (the `^\d{4}$` block). If `_render_yearly_report` doesn't exist yet when running tests, tests will fail as expected.

**Step 1: Write the failing tests**

```python
class TestYearlyReportContent:
    """Tests for /health 2026."""

    def test_year_arg_triggers_yearly_report(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.query_gsi1", return_value=[]), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2026")
            mock_send.assert_called_once()
            assert "2026" in mock_send.call_args[0][1]
            assert "年報" in mock_send.call_args[0][1]

    def test_no_meals_shows_zero_days(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.query_gsi1", return_value=[]), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2026")
            msg = mock_send.call_args[0][1]
            assert "0 天" in msg

    def test_complete_days_counted_correctly(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("500"), "date": "2026-01-01"},
            {"meal_type": "lunch",     "calories": Decimal("600"), "date": "2026-01-01"},
            {"meal_type": "dinner",    "calories": Decimal("700"), "date": "2026-01-01"},
            {"meal_type": "breakfast", "calories": Decimal("400"), "date": "2026-02-01"},
            {"meal_type": "lunch",     "calories": Decimal("500"), "date": "2026-02-01"},
            {"meal_type": "dinner",    "calories": Decimal("600"), "date": "2026-02-01"},
        ]
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2026")
            msg = mock_send.call_args[0][1]
            assert "2 天" in msg

    def test_monthly_breakdown_shown(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("500"), "date": "2026-01-01"},
            {"meal_type": "lunch",     "calories": Decimal("600"), "date": "2026-01-01"},
            {"meal_type": "dinner",    "calories": Decimal("700"), "date": "2026-01-01"},
        ]
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2026")
            msg = mock_send.call_args[0][1]
            assert "01月" in msg
            assert "月份摘要" in msg

    def test_tdee_fill_counted_in_year_stats(self):
        # Partial day → TDEE fill
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("500"), "date": "2026-01-01"},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2026")
            msg = mock_send.call_args[0][1]
            assert "TDEE 填補：1 天" in msg

    def test_target_total_uses_full_year_days(self):
        # 2026 is not a leap year → 365 days; daily_goal=1700 → 620,500
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.query_gsi1", return_value=[]), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2026")
            msg = mock_send.call_args[0][1]
            assert "620,500" in msg   # 1700 * 365

    def test_invalid_year_below_range_shows_error(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "1999")
            assert "❌" in mock_send.call_args[0][1]

    def test_invalid_year_above_range_shows_error(self):
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2100")
            assert "❌" in mock_send.call_args[0][1]
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_health_handler.py::TestYearlyReportContent -v
```
Expected: FAIL — `_render_yearly_report` not defined.

**Step 3: Add `_render_yearly_report`** in `health.py` after `_render_weekly_report`:

```python
def _render_yearly_report(chat_id, owner_id, year_str):
    from calendar import isleap
    meals = query_gsi1(
        gsi1pk=f"USER#{owner_id}#HEALTH",
        sk_condition=Key("GSI1SK").begins_with(f"{year_str}-"),
    )
    settings = _get_settings(owner_id)
    tdee = int(settings["tdee"]) if settings else None
    daily_goal = (int(settings["tdee"]) - int(settings["deficit"])) if settings else None

    # Group by date → {meal_type: calories}
    day_meal_maps = {}
    for meal in meals:
        d = meal["date"]
        if d not in day_meal_maps:
            day_meal_maps[d] = {}
        day_meal_maps[d][meal["meal_type"]] = int(meal["calories"])

    num_days = 0
    total_intake = 0
    fill_count = 0
    days_ok = 0
    days_over = 0
    month_stats = {}  # "YYYY-MM" → {days, total, days_ok, days_over}

    for d, meal_map in day_meal_maps.items():
        effective, was_filled = _effective_daily_calories(meal_map, tdee)
        num_days += 1
        total_intake += effective
        if was_filled:
            fill_count += 1
        if daily_goal is not None:
            if effective <= daily_goal:
                days_ok += 1
            else:
                days_over += 1
        month_key = d[:7]
        if month_key not in month_stats:
            month_stats[month_key] = {"days": 0, "total": 0, "days_ok": 0, "days_over": 0}
        month_stats[month_key]["days"] += 1
        month_stats[month_key]["total"] += effective
        if daily_goal is not None:
            if effective <= daily_goal:
                month_stats[month_key]["days_ok"] += 1
            else:
                month_stats[month_key]["days_over"] += 1

    avg_intake = round(total_intake / num_days) if num_days > 0 else 0
    fill_note = f"（含 TDEE 填補：{fill_count} 天）" if fill_count > 0 else ""

    lines = [
        f"📊 *{year_str} 年健康年報*",
        "──────────────────────",
        f"📅 有記錄天數：{num_days} 天{fill_note}",
        f"🔥 平均日攝取：{avg_intake:,} kcal",
    ]

    if daily_goal is not None:
        lines += [
            f"🎯 每日目標：{daily_goal:,} kcal",
            f"✅ 達標天數：{days_ok} 天 / ⚠️ 超標天數：{days_over} 天",
        ]

    if month_stats:
        lines += ["──────────────────────", "*月份摘要*"]
        for month_key in sorted(month_stats.keys()):
            ms = month_stats[month_key]
            month_avg = round(ms["total"] / ms["days"]) if ms["days"] > 0 else 0
            month_label = f"{int(month_key[5:7]):02d}月"
            if daily_goal is not None:
                lines.append(
                    f"{month_label}：平均 {month_avg:,} kcal — ✅ {ms['days_ok']}天 ⚠️ {ms['days_over']}天"
                )
            else:
                lines.append(f"{month_label}：平均 {month_avg:,} kcal — {ms['days']}天有記錄")

    year_int = int(year_str)
    days_in_year = 366 if isleap(year_int) else 365
    lines.append("──────────────────────")
    lines.append(f"全年總攝取：{total_intake:,} kcal")
    if daily_goal is not None:
        target_total = daily_goal * days_in_year
        lines.append(f"目標合計：{target_total:,} kcal（{days_in_year}天 × {daily_goal:,}）")

    send_message(chat_id, "\n".join(lines))
```

**Step 4: Run to verify pass**

```bash
pytest tests/test_health_handler.py::TestYearlyReportContent -v
```
Expected: 8 passed.

**Step 5: Commit**

```bash
git add webhook_handler/handlers/health.py tests/test_health_handler.py
git commit -m "feat: add yearly health report (/health 2026)"
```

---

### Task 5: Today summary TDEE-fill warning

**Files:**
- Modify: `webhook_handler/handlers/health.py` (`_render_today_summary`)
- Test: `tests/test_health_handler.py` (add tests to `TestTodaySummaryContent`)

**Step 1: Write the failing tests**

Add to the existing `TestTodaySummaryContent` class:

```python
    def test_missing_main_meal_shows_tdee_fill_warning(self):
        # Only breakfast recorded → lunch + dinner missing → TDEE fill warning
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("600"), "date": TODAY},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.get_weekday_name", return_value=WEEKDAY), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "缺少主食記錄" in msg
            assert "TDEE" in msg
            assert "2,200" in msg   # TDEE value shown

    def test_missing_main_meal_uses_tdee_for_goal_progress(self):
        # breakfast only → TDEE=2200 used → goal=1700 → over by 500
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("600"), "date": TODAY},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.get_weekday_name", return_value=WEEKDAY), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            # TDEE(2200) > goal(1700) → surplus = 500
            assert "500" in msg
            assert "超出" in msg

    def test_all_main_meals_present_no_tdee_warning(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("600"), "date": TODAY},
            {"meal_type": "lunch",     "calories": Decimal("700"), "date": TODAY},
            {"meal_type": "dinner",    "calories": Decimal("500"), "date": TODAY},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.get_weekday_name", return_value=WEEKDAY), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "缺少主食記錄" not in msg

    def test_missing_meal_no_settings_no_warning(self):
        # No settings → TDEE fill is inactive → no warning
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("600"), "date": TODAY},
        ]
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.get_today", return_value=TODAY), \
             patch("handlers.health.get_weekday_name", return_value=WEEKDAY), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "缺少主食記錄" not in msg
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_health_handler.py::TestTodaySummaryContent -v
```
Expected: 4 new tests FAIL (existing 4 still pass).

**Step 3: Update `_render_today_summary`** in `health.py`:

Replace the entire `_render_today_summary` function with:

```python
def _render_today_summary(chat_id, owner_id, date_str):
    weekday = get_weekday_name(date_str)
    meals = _get_meals_for_date(owner_id, date_str)
    meal_map = {m["meal_type"]: int(m["calories"]) for m in meals}

    lines = [
        "🥗 *今日飲食記錄*",
        f"📆 {date_str}（{weekday}）",
        "──────────────────────",
    ]

    actual_total = 0
    for meal_type in ("breakfast", "lunch", "dinner", "other"):
        info = HEALTH_MEAL_DISPLAY[meal_type]
        if meal_type in meal_map:
            cal = meal_map[meal_type]
            actual_total += cal
            lines.append(f"{info['emoji']} {info['label']}：{cal:,} kcal")
        else:
            lines.append(f"{info['emoji']} {info['label']}：（未記錄）")

    lines.append("──────────────────────")
    lines.append(f"總攝取：{actual_total:,} kcal")

    settings = _get_settings(owner_id)
    if settings:
        tdee = int(settings["tdee"])
        deficit = int(settings["deficit"])
        daily_goal = tdee - deficit
        effective, was_filled = _effective_daily_calories(meal_map, tdee)

        if was_filled:
            lines.append(f"⚠️ 缺少主食記錄，以 TDEE 計算：{effective:,} kcal")

        remaining = daily_goal - effective
        lines += [
            "",
            "📊 *目標進度*",
            f"TDEE：{tdee:,} kcal  目標赤字：{deficit:,} kcal",
            f"每日目標：{daily_goal:,} kcal",
            f"剩餘：{remaining:,} kcal ✅" if remaining >= 0
            else f"超出：{abs(remaining):,} kcal ⚠️",
        ]

    send_message(chat_id, "\n".join(lines))
```

**Step 4: Run to verify pass**

```bash
pytest tests/test_health_handler.py::TestTodaySummaryContent -v
```
Expected: all 8 tests pass (4 existing + 4 new).

**Step 5: Commit**

```bash
git add webhook_handler/handlers/health.py tests/test_health_handler.py
git commit -m "feat: show TDEE-fill warning in today summary when main meal missing"
```

---

### Task 6: Monthly report TDEE-fill

**Files:**
- Modify: `webhook_handler/handlers/health.py` (`_render_monthly_report`)
- Test: `tests/test_health_handler.py` (add tests to `TestMonthlyReportContent`)

**Step 1: Write the failing tests**

Add to the existing `TestMonthlyReportContent` class:

```python
    def test_incomplete_day_uses_tdee_for_average(self):
        # Day 1: only breakfast (500) → TDEE-fill → 2200 used
        # Day 2: full meals (500+700+600=1800) → actual used
        # avg = (2200 + 1800) / 2 = 2000
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("500"),  "date": "2026-03-01"},
            {"meal_type": "breakfast", "calories": Decimal("500"),  "date": "2026-03-02"},
            {"meal_type": "lunch",     "calories": Decimal("700"),  "date": "2026-03-02"},
            {"meal_type": "dinner",    "calories": Decimal("600"),  "date": "2026-03-02"},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2026-03")
            msg = mock_send.call_args[0][1]
            assert "2,000" in msg   # avg = 2000

    def test_incomplete_day_over_goal_counted_in_over_days(self):
        # TDEE=2200 > goal=1700 → day is "over"
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("500"),  "date": "2026-03-01"},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2026-03")
            msg = mock_send.call_args[0][1]
            assert "超標天數：1" in msg

    def test_fill_count_shown_in_monthly_header(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("500"),  "date": "2026-03-01"},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.query_gsi1", return_value=meals), \
             patch("handlers.health.get_item", return_value=settings), \
             patch("handlers.health.send_message") as mock_send:
            handle_health(USER_ID, CHAT_ID, "2026-03")
            msg = mock_send.call_args[0][1]
            assert "TDEE 填補：1 天" in msg
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_health_handler.py::TestMonthlyReportContent -v
```
Expected: 3 new tests FAIL (the existing 4 may now fail too since we're changing the monthly renderer logic — that's fine, we'll fix them together).

**Step 3: Replace `_render_monthly_report`** in `health.py`:

```python
def _render_monthly_report(chat_id, owner_id, month_str):
    meals = _get_meals_for_month(owner_id, month_str)
    settings = _get_settings(owner_id)
    tdee = int(settings["tdee"]) if settings else None
    daily_goal = (int(settings["tdee"]) - int(settings["deficit"])) if settings else None

    # Group by date → {meal_type: calories}
    day_meal_maps = {}
    for meal in meals:
        d = meal["date"]
        if d not in day_meal_maps:
            day_meal_maps[d] = {}
        day_meal_maps[d][meal["meal_type"]] = int(meal["calories"])

    num_days = len(day_meal_maps)
    total_intake = 0
    fill_count = 0
    days_ok = 0
    days_over = 0

    for d, meal_map in day_meal_maps.items():
        effective, was_filled = _effective_daily_calories(meal_map, tdee)
        total_intake += effective
        if was_filled:
            fill_count += 1
        if daily_goal is not None:
            if effective <= daily_goal:
                days_ok += 1
            else:
                days_over += 1

    avg_intake = round(total_intake / num_days) if num_days > 0 else 0
    fill_note = f"（含 TDEE 填補：{fill_count} 天）" if fill_count > 0 else ""

    lines = [
        f"📊 *{month_str} 健康月報*",
        "──────────────────────",
        f"📅 有記錄天數：{num_days} 天{fill_note}",
        f"🔥 平均日攝取：{avg_intake:,} kcal",
    ]

    if daily_goal is not None:
        lines += [
            f"🎯 每日目標：{daily_goal:,} kcal",
            f"✅ 達標天數：{days_ok} 天 / ⚠️ 超標天數：{days_over} 天",
        ]

    year, month = int(month_str[:4]), int(month_str[5:7])
    days_in_month = monthrange(year, month)[1]

    lines.append("──────────────────────")
    lines.append(f"各月合計攝取：{total_intake:,} kcal")
    if daily_goal is not None:
        target_total = daily_goal * days_in_month
        lines.append(f"目標合計：{target_total:,} kcal")

    send_message(chat_id, "\n".join(lines))
```

**Step 4: Run full test suite to verify all pass**

```bash
pytest tests/test_health_handler.py -v
```
Expected: all tests pass (including the 4 pre-existing monthly tests — the new logic is backward-compatible for fully-recorded days since `_effective_daily_calories` returns actual sum when all 3 main meals are present).

**Step 5: Commit**

```bash
git add webhook_handler/handlers/health.py tests/test_health_handler.py
git commit -m "feat: apply TDEE-fill to monthly report averages and goal counts"
```

---

### Task 7: Update `help_module.py`

**Files:**
- Modify: `webhook_handler/handlers/help_module.py`

No new tests needed — this is display text only.

**Step 1: Update the overview section** — find the `*🥗 健康管理*` block in `_HELP_MODULES["overview"]["content"]` and update the `/health` line:

Old:
```python
"/health `[YYYY-MM]` — 今日飲食記錄或月報\n\n"
```

New:
```python
"/health `[week|YYYY-MM|YYYY]` — 今日、週、月或年報\n\n"
```

**Step 2: Update the health module detail** — find `_HELP_MODULES["health"]["content"]`, locate the `*查看記錄*` section and replace it:

Old:
```python
"*查看記錄*\n"
"• /health — 今日飲食記錄（各餐明細 + 目標進度）\n"
"• `/health 2026-03` — 指定月份健康月報\n"
"  含：有記錄天數、平均日攝取、達標/超標天數、月合計\n\n"
```

New:
```python
"*查看記錄*\n"
"• /health — 今日飲食記錄（各餐明細 + 目標進度）\n"
"• `/health week` — 本週每日明細 + 週平均\n"
"• `/health 2026-03` — 月報（平均日攝取、達標/超標天數）\n"
"• `/health 2026` — 年報（月份摘要 + 年度合計）\n\n"
"*💡 TDEE 填補規則*\n"
"若某天缺少早、午或晚餐記錄，週／月／年報會以 TDEE 代替該天卡路里，今日記錄亦會顯示警示。\n\n"
```

**Step 3: Run full test suite**

```bash
pytest tests/ -v
```
Expected: all tests pass.

**Step 4: Commit**

```bash
git add webhook_handler/handlers/help_module.py
git commit -m "docs: update health help text with week/year commands and TDEE-fill note"
```

---

### Task 8: Final verification and push

**Step 1: Run full test suite**

```bash
pytest tests/ -v
```
Expected: all tests pass, no failures.

**Step 2: Quick syntax check on changed files**

```bash
python -c "import ast; ast.parse(open('webhook_handler/handlers/health.py').read()); print('OK')"
python -c "import ast; ast.parse(open('webhook_handler/handlers/help_module.py').read()); print('OK')"
```
Expected: `OK` for both.

**Step 3: Push**

```bash
git push origin main
```