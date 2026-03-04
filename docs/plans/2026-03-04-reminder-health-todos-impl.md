# Reminder Evening Health + Morning Todo Count Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add today's health summary to the evening reminder and always show total pending todo count in the morning briefing.

**Architecture:** Two new DB query helpers in `db_queries.py` expose health data to the reminder layer. `_sec_todos` in `ReminderService` is updated to always emit a count line. A new `_sec_health` method queries today's meals and settings and renders inline with the TDEE-fill rule. All tests go in the new `tests/test_reminder_service.py`.

**Tech Stack:** Python 3.13, pytest, unittest.mock, boto3 DynamoDB (via shared `bot_db` layer)

---

## Context

- Reminder handler lives in `reminder_handler/reminders/`
- `conftest.py` already adds `reminder_handler/` to `sys.path` so `from reminders.X import ...` works in tests
- Mock at the **caller's namespace**: patch `reminders.reminder_service.get_today_meals`, not `bot_db.get_item`
- `ReminderService.__init__` sets `self.today_s`, `self.end_s`, etc. — bypass it in tests using `object.__new__`
- Health data GSI1: `gsi1pk=f"USER#{owner_id}#HEALTH"`, `sk_condition=Key("GSI1SK").begins_with(date_str)`
- Health settings: `PK=f"USER#{owner_id}"`, `SK="HEALTH_SETTINGS#active"` (plain `get_item` call)
- Run tests with: `pytest tests/test_reminder_service.py -v`

---

### Task 1: DB query helpers for health data

**Files:**
- Modify: `reminder_handler/reminders/db_queries.py`
- Test: `tests/test_reminder_service.py` (create new file)

**Step 1: Create `tests/test_reminder_service.py` with the DB query tests**

```python
# tests/test_reminder_service.py
# ============================================================
# Unit tests for ReminderService section builders.
# ============================================================

import pytest
from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import patch, MagicMock

from reminders.reminder_service import ReminderService
from reminders.db_queries import get_today_meals, get_health_settings


OWNER_ID = 12345
TODAY = "2026-03-03"


def _make_service(today_str=TODAY):
    """Create a ReminderService bypassing __init__ with a fixed date."""
    svc = object.__new__(ReminderService)
    d = date.fromisoformat(today_str)
    svc.today = d
    svc.today_s = today_str
    svc.wd = ["一", "二", "三", "四", "五", "六", "日"][d.weekday()]
    svc.end_s = (d + timedelta(days=3)).isoformat()
    return svc


# ================================================================
#  DB query helpers
# ================================================================

class TestGetTodayMeals:
    def test_calls_gsi1_with_correct_pk_and_prefix(self):
        with patch("reminders.db_queries._db_query_gsi1") as mock_q, \
             patch("reminders.db_queries._db_get_item"):
            get_today_meals(OWNER_ID, TODAY)
            mock_q.assert_called_once()
            call_kwargs = mock_q.call_args
            assert call_kwargs[1]["gsi1pk"] == f"USER#{OWNER_ID}#HEALTH"

    def test_returns_list_from_query(self):
        fake_meals = [{"meal_type": "breakfast", "calories": Decimal("500")}]
        with patch("reminders.db_queries._db_query_gsi1", return_value=fake_meals), \
             patch("reminders.db_queries._db_get_item"):
            result = get_today_meals(OWNER_ID, TODAY)
            assert result == fake_meals


class TestGetHealthSettings:
    def test_calls_get_item_with_correct_keys(self):
        with patch("reminders.db_queries._db_get_item") as mock_get, \
             patch("reminders.db_queries._db_query_gsi1"):
            get_health_settings(OWNER_ID)
            mock_get.assert_called_once_with(
                f"USER#{OWNER_ID}", "HEALTH_SETTINGS#active"
            )

    def test_returns_none_when_not_found(self):
        with patch("reminders.db_queries._db_get_item", return_value=None), \
             patch("reminders.db_queries._db_query_gsi1"):
            result = get_health_settings(OWNER_ID)
            assert result is None

    def test_returns_settings_dict_when_found(self):
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        with patch("reminders.db_queries._db_get_item", return_value=settings), \
             patch("reminders.db_queries._db_query_gsi1"):
            result = get_health_settings(OWNER_ID)
            assert result == settings
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_reminder_service.py::TestGetTodayMeals tests/test_reminder_service.py::TestGetHealthSettings -v
```
Expected: ImportError — `get_today_meals` and `get_health_settings` not defined yet.

**Step 3: Implement in `db_queries.py`**

Add `get_item` to the existing `bot_db` import at the top of `db_queries.py`:

```python
# Change this line:
from bot_db import query_gsi1 as _db_query_gsi1
# To this:
from bot_db import query_gsi1 as _db_query_gsi1, get_item as _db_get_item
```

Add the two new functions at the end of `db_queries.py`:

```python
# ================================================================
#  Health
# ================================================================

def get_today_meals(owner_id, date_str):
    """Today's health meal records for the reminder health section."""
    from boto3.dynamodb.conditions import Key
    return _db_query_gsi1(
        gsi1pk=f"USER#{owner_id}#HEALTH",
        sk_condition=Key("GSI1SK").begins_with(date_str),
    )


def get_health_settings(owner_id):
    """Health settings (TDEE + deficit target)."""
    return _db_get_item(f"USER#{owner_id}", "HEALTH_SETTINGS#active")
```

**Step 4: Run to verify pass**

```bash
pytest tests/test_reminder_service.py::TestGetTodayMeals tests/test_reminder_service.py::TestGetHealthSettings -v
```
Expected: 5 passed.

**Step 5: Commit**

```bash
git add reminder_handler/reminders/db_queries.py tests/test_reminder_service.py
git commit -m "feat: add get_today_meals and get_health_settings to db_queries"
```

---

### Task 2: Morning todo count always shown

**Files:**
- Modify: `reminder_handler/reminders/reminder_service.py` (`_sec_todos` method, lines ~358–400)
- Test: `tests/test_reminder_service.py`

**Step 1: Add failing tests**

Add to `tests/test_reminder_service.py`:

```python
# ================================================================
#  _sec_todos — morning todo section
# ================================================================

class TestSecTodos:
    def _make_todo(self, title, due_date=""):
        return {"title": title, "due_date": due_date, "priority": "medium"}

    def test_no_todos_returns_none(self):
        svc = _make_service()
        result = svc._sec_todos({"todos": []})
        assert result is None

    def test_todos_all_no_due_date_shows_count(self):
        # Todos with no due date → not urgently due → should still show count
        todos = [
            self._make_todo("Task A"),
            self._make_todo("Task B"),
            self._make_todo("Task C"),
        ]
        svc = _make_service()
        result = svc._sec_todos({"todos": todos})
        assert result is not None
        assert "3" in result
        assert "無近期到期" in result

    def test_todos_with_no_urgent_items_shows_count(self):
        # Todos due far in the future (beyond 3-day window) → show count
        todos = [self._make_todo("Far todo", due_date="2026-12-31")]
        svc = _make_service()
        result = svc._sec_todos({"todos": todos})
        assert result is not None
        assert "1" in result
        assert "無近期到期" in result

    def test_urgent_todos_show_count_in_header(self):
        # Overdue todo → normal urgent display, but count in header
        todos = [self._make_todo("Overdue", due_date="2026-02-01")]
        svc = _make_service()
        result = svc._sec_todos({"todos": todos})
        assert result is not None
        assert "1" in result           # count
        assert "逾期" in result        # urgency shown

    def test_count_includes_no_due_date_todos(self):
        # 1 overdue + 1 no-due-date → count = 2
        todos = [
            self._make_todo("Overdue", due_date="2026-02-01"),
            self._make_todo("No due"),
        ]
        svc = _make_service()
        result = svc._sec_todos({"todos": todos})
        assert "2" in result
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_reminder_service.py::TestSecTodos -v
```
Expected: 3–4 tests FAIL (the count/無近期到期 assertions fail with current code).

**Step 3: Update `_sec_todos` in `reminder_service.py`**

Locate the method (around line 358). Replace the logic **after** the three lists are built:

Old block:
```python
        if not overdue and not today_t and not upcoming:
            return None

        lines = ["📝 *待辦事項*"]
```

New block:
```python
        count = len(items)
        has_urgent = overdue or today_t or upcoming

        if not has_urgent:
            return f"📝 *待辦事項（共 {count} 項）*\n無近期到期項目。"

        lines = [f"📝 *待辦事項（共 {count} 項）*"]
```

**Step 4: Run to verify pass**

```bash
pytest tests/test_reminder_service.py::TestSecTodos -v
```
Expected: 5 passed.

**Step 5: Run full test suite to check nothing broken**

```bash
pytest tests/ -v
```
Expected: all pass.

**Step 6: Commit**

```bash
git add reminder_handler/reminders/reminder_service.py tests/test_reminder_service.py
git commit -m "feat: always show pending todo count in morning briefing"
```

---

### Task 3: Evening health section

**Files:**
- Modify: `reminder_handler/reminders/reminder_service.py`
  - Add imports for `get_today_meals`, `get_health_settings`
  - Add `_sec_health` method
  - Call `_sec_health` in `evening_preview`
- Test: `tests/test_reminder_service.py`

**Step 1: Add failing tests**

Add to `tests/test_reminder_service.py`:

```python
# ================================================================
#  _sec_health — evening health section
# ================================================================

class TestSecHealth:
    def test_no_meals_returns_none(self):
        svc = _make_service()
        with patch("reminders.reminder_service.get_today_meals", return_value=[]), \
             patch("reminders.reminder_service.get_health_settings", return_value=None), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID):
            result = svc._sec_health()
            assert result is None

    def test_meals_present_shows_meal_lines(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("600"), "date": TODAY},
            {"meal_type": "lunch",     "calories": Decimal("700"), "date": TODAY},
            {"meal_type": "dinner",    "calories": Decimal("500"), "date": TODAY},
        ]
        svc = _make_service()
        with patch("reminders.reminder_service.get_today_meals", return_value=meals), \
             patch("reminders.reminder_service.get_health_settings", return_value=None), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID):
            result = svc._sec_health()
            assert result is not None
            assert "早餐" in result
            assert "600" in result
            assert "午餐" in result
            assert "700" in result
            assert "晚餐" in result
            assert "500" in result

    def test_unrecorded_meal_shown_as_not_recorded(self):
        # Only breakfast recorded
        meals = [{"meal_type": "breakfast", "calories": Decimal("600"), "date": TODAY}]
        svc = _make_service()
        with patch("reminders.reminder_service.get_today_meals", return_value=meals), \
             patch("reminders.reminder_service.get_health_settings", return_value=None), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID):
            result = svc._sec_health()
            assert "（未記錄）" in result

    def test_no_settings_hides_goal_line(self):
        meals = [{"meal_type": "breakfast", "calories": Decimal("600"), "date": TODAY}]
        svc = _make_service()
        with patch("reminders.reminder_service.get_today_meals", return_value=meals), \
             patch("reminders.reminder_service.get_health_settings", return_value=None), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID):
            result = svc._sec_health()
            assert "每日目標" not in result

    def test_all_main_meals_with_settings_shows_goal_progress(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("500"), "date": TODAY},
            {"meal_type": "lunch",     "calories": Decimal("600"), "date": TODAY},
            {"meal_type": "dinner",    "calories": Decimal("500"), "date": TODAY},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        svc = _make_service()
        with patch("reminders.reminder_service.get_today_meals", return_value=meals), \
             patch("reminders.reminder_service.get_health_settings", return_value=settings), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID):
            result = svc._sec_health()
            assert "每日目標" in result
            assert "1,700" in result   # goal = 2200 - 500
            assert "剩餘" in result    # 1700 - 1600 = 100 remaining
            assert "✅" in result

    def test_over_goal_shows_surplus(self):
        # Total = 2000 > goal 1700 → surplus
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("700"), "date": TODAY},
            {"meal_type": "lunch",     "calories": Decimal("800"), "date": TODAY},
            {"meal_type": "dinner",    "calories": Decimal("500"), "date": TODAY},
        ]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        svc = _make_service()
        with patch("reminders.reminder_service.get_today_meals", return_value=meals), \
             patch("reminders.reminder_service.get_health_settings", return_value=settings), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID):
            result = svc._sec_health()
            assert "超出" in result
            assert "⚠️" in result

    def test_missing_main_meal_shows_tdee_fill_warning(self):
        # Only breakfast → lunch+dinner missing → TDEE fill
        meals = [{"meal_type": "breakfast", "calories": Decimal("600"), "date": TODAY}]
        settings = {"tdee": Decimal("2200"), "deficit": Decimal("500")}
        svc = _make_service()
        with patch("reminders.reminder_service.get_today_meals", return_value=meals), \
             patch("reminders.reminder_service.get_health_settings", return_value=settings), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID):
            result = svc._sec_health()
            assert "缺少主食記錄" in result
            assert "TDEE" in result
            assert "2,200" in result   # TDEE value


class TestEveningPreviewIncludesHealth:
    def test_health_section_included_when_meals_exist(self):
        meals = [
            {"meal_type": "breakfast", "calories": Decimal("600"), "date": TODAY},
            {"meal_type": "lunch",     "calories": Decimal("700"), "date": TODAY},
            {"meal_type": "dinner",    "calories": Decimal("500"), "date": TODAY},
        ]
        svc = _make_service()
        with patch("reminders.reminder_service.get_schedules_effective_on", return_value=[]), \
             patch("reminders.reminder_service.get_pending_todos", return_value=[]), \
             patch("reminders.reminder_service.get_pending_payments", return_value=[]), \
             patch("reminders.reminder_service.get_active_subscriptions", return_value=[]), \
             patch("reminders.reminder_service.get_active_work", return_value=[]), \
             patch("reminders.reminder_service.get_today_meals", return_value=meals), \
             patch("reminders.reminder_service.get_health_settings", return_value=None), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID), \
             patch("reminders.reminder_service.send") as mock_send:
            svc.evening_preview()
            msg = mock_send.call_args[0][0]
            assert "今日健康" in msg

    def test_health_section_omitted_when_no_meals(self):
        svc = _make_service()
        with patch("reminders.reminder_service.get_schedules_effective_on", return_value=[]), \
             patch("reminders.reminder_service.get_pending_todos", return_value=[]), \
             patch("reminders.reminder_service.get_pending_payments", return_value=[]), \
             patch("reminders.reminder_service.get_active_subscriptions", return_value=[]), \
             patch("reminders.reminder_service.get_active_work", return_value=[]), \
             patch("reminders.reminder_service.get_today_meals", return_value=[]), \
             patch("reminders.reminder_service.get_health_settings", return_value=None), \
             patch("reminders.reminder_service.get_owner_id", return_value=OWNER_ID), \
             patch("reminders.reminder_service.send") as mock_send:
            svc.evening_preview()
            msg = mock_send.call_args[0][0]
            assert "今日健康" not in msg
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_reminder_service.py::TestSecHealth tests/test_reminder_service.py::TestEveningPreviewIncludesHealth -v
```
Expected: ImportError or AttributeError — `_sec_health` not defined.

**Step 3: Update imports in `reminder_service.py`**

Add to the `from .db_queries import (...)` block:

```python
from .db_queries import (
    get_schedules_for_date,
    get_schedules_effective_on,
    get_pending_todos,
    get_pending_payments,
    get_active_subscriptions,
    get_active_work,
    get_today_meals,       # ADD
    get_health_settings,   # ADD
)
```

Also add at the top of the file (after `import os`):

```python
from bot_config import get_owner_id
```

**Step 4: Add `_sec_health` method** to `ReminderService`, after `_sec_stats`:

```python
    # ============================================================
    #  Evening Section Builder — Health
    # ============================================================

    _HEALTH_MEAL_DISPLAY = {
        "breakfast": ("🌅", "早餐"),
        "lunch":     ("☀️", "午餐"),
        "dinner":    ("🌙", "晚餐"),
        "other":     ("🍎", "其他"),
    }

    def _sec_health(self):
        owner_id = get_owner_id()
        meals = get_today_meals(owner_id, self.today_s)
        if not meals:
            return None

        settings = get_health_settings(owner_id)
        meal_map = {m["meal_type"]: int(m["calories"]) for m in meals}

        lines = ["🥗 *今日健康*"]
        actual_total = 0
        for meal_type in ("breakfast", "lunch", "dinner", "other"):
            emoji, label = self._HEALTH_MEAL_DISPLAY[meal_type]
            if meal_type in meal_map:
                cal = meal_map[meal_type]
                actual_total += cal
                lines.append(f"{emoji} {label}：{cal:,} kcal")
            else:
                lines.append(f"{emoji} {label}：（未記錄）")

        lines.append(DIV)
        lines.append(f"總攝取：{actual_total:,} kcal")

        if settings:
            tdee = int(settings["tdee"])
            deficit = int(settings["deficit"])
            daily_goal = tdee - deficit

            main_meals = {"breakfast", "lunch", "dinner"}
            if not main_meals.issubset(meal_map.keys()):
                effective = tdee
                lines.append(f"⚠️ 缺少主食記錄，以 TDEE 計算：{effective:,} kcal")
            else:
                effective = actual_total

            remaining = daily_goal - effective
            if remaining >= 0:
                lines.append(f"每日目標：{daily_goal:,} kcal  剩餘：{remaining:,} kcal ✅")
            else:
                lines.append(f"每日目標：{daily_goal:,} kcal  超出：{abs(remaining):,} kcal ⚠️")

        return "\n".join(lines)
```

**Step 5: Call `_sec_health` in `evening_preview`**

Locate the end of `evening_preview`, just before the footer lines:

```python
        if len(secs) == 1:
            secs.append("✨ 明天暫無待處理事項，好好休息！")

        secs.append(f"{DIV}\n🌟 晚安，明天也加油！")
```

Insert the health section call **before** the `if len(secs) == 1` check:

```python
        # ── 今日健康 ──
        h = self._sec_health()
        if h:
            secs.append(h)

        if len(secs) == 1:
            secs.append("✨ 明天暫無待處理事項，好好休息！")

        secs.append(f"{DIV}\n🌟 晚安，明天也加油！")
```

**Step 6: Run to verify pass**

```bash
pytest tests/test_reminder_service.py::TestSecHealth tests/test_reminder_service.py::TestEveningPreviewIncludesHealth -v
```
Expected: 9 passed.

**Step 7: Run full test suite**

```bash
pytest tests/ -v
```
Expected: all tests pass.

**Step 8: Commit**

```bash
git add reminder_handler/reminders/reminder_service.py tests/test_reminder_service.py
git commit -m "feat: add today health summary to evening reminder"
```

---

### Task 4: Final verification and push

**Step 1: Syntax check both changed files**

```bash
python -c "import ast; ast.parse(open('reminder_handler/reminders/db_queries.py').read()); print('db_queries OK')"
python -c "import ast; ast.parse(open('reminder_handler/reminders/reminder_service.py').read()); print('reminder_service OK')"
```
Expected: both print OK.

**Step 2: Run full test suite one final time**

```bash
pytest tests/ -v
```
Expected: all tests pass, no failures or errors.

**Step 3: Push**

```bash
git push origin main
```