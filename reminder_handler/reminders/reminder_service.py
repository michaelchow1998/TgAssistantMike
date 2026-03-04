# reminders/reminder_service.py
# ============================================================
# ReminderService — 建構並發送 4 種排程提醒
#
#   morning_briefing()       08:00  完整日報
#   subscription_alert()     10:00  訂閱到期（無則跳過）
#   payment_alert()          12:00  付款到期（無則跳過）
#   evening_preview()        21:00  明日預覽
#
# ── 各 Entity 預期屬性 ──
#   Schedule:     title, date, time, category
#   Todo:         title, due_date, priority (high|medium|low)
#   Payment:      title, due_date, amount
#   Subscription: name, next_due, amount, cycle
#   Work:         title, deadline, progress (0–100)
# ============================================================

import os
import logging
from datetime import datetime, timedelta

from bot_config import get_owner_id
from bot_constants import HEALTH_MEAL_DISPLAY
from bot_db import put_item
from bot_utils import generate_ulid
from bot_db import get_next_short_id as next_short_id

import pytz                                        # dependencies layer

from .db_queries import (
    get_schedules_for_date,
    get_schedules_effective_on,
    get_pending_todos,
    get_pending_payments,
    get_active_subscriptions,
    get_active_work,
    get_today_meals,
    get_health_settings,
    get_active_recurring_templates,
    get_fin_records_for_month,
)
from .notifier import (
    send,
    fmt_float,
    fmt_int,
    fmt_amount,
    fmt_bar,
    day_diff,
    day_label,
    DIV,
    WEEKDAYS,
    PRIO_ICON,
)

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────

TZ = pytz.timezone(os.environ.get("TIMEZONE", "Asia/Hong_Kong"))
AHEAD = 3       # 預覽天數


# ================================================================
#  ReminderService
# ================================================================

class ReminderService:

    def __init__(self):
        self.now = datetime.now(TZ)
        self.today = self.now.date()
        self.today_s = self.today.isoformat()          # "2026-03-02"
        self.wd = WEEKDAYS[self.today.weekday()]        # "一"
        self.end_s = (self.today + timedelta(days=AHEAD)).isoformat()

    # ── 資料取得（單次查詢，多處複用）──

    def _fetch_all(self):
        return {
            "schedules": get_schedules_effective_on(self.today_s),
            "todos":     get_pending_todos(),
            "work":      get_active_work(),
            "payments":  get_pending_payments(),
            "subs":      get_active_subscriptions(),
        }

    # ============================================================
    #  1) Morning Briefing — 08:00
    # ============================================================

    def morning_briefing(self) -> bool:
        data = self._fetch_all()

        secs = [
            f"🌅 *早安！今日摘要*\n"
            f"📆 {self.today_s}（{self.wd}）\n{DIV}"
        ]

        # Auto-generate recurring records on the 1st of month
        generated = self._generate_recurring_records()
        if generated > 0:
            secs.append(f"🔄 已自動新增 {generated} 筆週期財務記錄")

        for builder in [
            self._sec_schedules,
            self._sec_todos,
            self._sec_work,
            self._sec_payments,
            self._sec_subs,
            self._sec_stats,
        ]:
            s = builder(data)
            if s:
                secs.append(s)

        if len(secs) == 1:
            secs.append("✨ 今天沒有待處理事項，好好享受！")

        secs.append(f"{DIV}\n💡 /help 查看所有指令")

        send("\n\n".join(secs))
        logger.info("Morning briefing sent")
        return True

    # ============================================================
    #  2) Subscription Alert — 10:00
    # ============================================================

    def subscription_alert(self) -> bool:
        subs = get_active_subscriptions()

        overdue = [
            s for s in subs
            if s.get("next_due", "9999") < self.today_s
        ]
        due_today = [
            s for s in subs
            if s.get("next_due") == self.today_s
        ]

        if not overdue and not due_today:
            logger.info("No subscription alerts, skipping")
            return False

        lines = [
            f"📦 *訂閱扣款提醒*\n"
            f"📆 {self.today_s}（{self.wd}）\n{DIV}"
        ]

        if overdue:
            total = sum(fmt_float(s.get("amount", 0)) for s in overdue)
            lines.append(f"\n⚠️ *逾期 {len(overdue)} 項（{fmt_amount(total)}）*")
            for s in sorted(overdue, key=lambda x: x.get("next_due", "")):
                d = abs(day_diff(s["next_due"], self.today))
                lines.append(
                    f"  • {s.get('name', '?')} "
                    f"{fmt_amount(s.get('amount', 0))}（逾期 {d} 天）"
                )

        if due_today:
            total = sum(fmt_float(s.get("amount", 0)) for s in due_today)
            lines.append(f"\n🔴 *今日扣款 {len(due_today)} 項（{fmt_amount(total)}）*")
            for s in due_today:
                cycle = s.get("cycle", "")
                cycle_s = f" [{cycle}]" if cycle else ""
                lines.append(
                    f"  • {s.get('name', '?')} "
                    f"{fmt_amount(s.get('amount', 0))}{cycle_s}"
                )

        lines.append(f"\n{DIV}\n⚡ 請確認帳戶餘額充足！")

        send("\n".join(lines))
        logger.info(f"Subscription alert sent: {len(overdue)} overdue, {len(due_today)} today")
        return True

    # ============================================================
    #  3) Payment Alert — 12:00
    # ============================================================

    def payment_alert(self) -> bool:
        payments = get_pending_payments()

        overdue = [
            p for p in payments
            if p.get("due_date", "9999") < self.today_s
        ]
        due_today = [
            p for p in payments
            if p.get("due_date") == self.today_s
        ]

        if not overdue and not due_today:
            logger.info("No payment alerts, skipping")
            return False

        lines = [
            f"💳 *付款到期提醒*\n"
            f"📆 {self.today_s}（{self.wd}）\n{DIV}"
        ]

        if overdue:
            total = sum(fmt_float(p.get("amount", 0)) for p in overdue)
            lines.append(f"\n⚠️ *逾期 {len(overdue)} 筆（{fmt_amount(total)}）*")
            for p in sorted(overdue, key=lambda x: x.get("due_date", "")):
                d = abs(day_diff(p["due_date"], self.today))
                lines.append(
                    f"  • {p.get('title', '?')} "
                    f"{fmt_amount(p.get('amount', 0))}（逾期 {d} 天）"
                )

        if due_today:
            total = sum(fmt_float(p.get("amount", 0)) for p in due_today)
            lines.append(f"\n🔴 *今日到期 {len(due_today)} 筆（{fmt_amount(total)}）*")
            for p in due_today:
                lines.append(
                    f"  • {p.get('title', '?')} "
                    f"{fmt_amount(p.get('amount', 0))}"
                )

        lines.append(f"\n{DIV}\n⚡ 請儘速處理以上款項！")

        send("\n".join(lines))
        logger.info(f"Payment alert sent: {len(overdue)} overdue, {len(due_today)} today")
        return True

    # ============================================================
    #  4) Evening Preview — 21:00
    # ============================================================

    def evening_preview(self) -> bool:
        tmr = self.today + timedelta(days=1)
        tmr_s = tmr.isoformat()
        tmr_wd = WEEKDAYS[tmr.weekday()]

        secs = [
            f"🌙 *晚安！明日預覽*\n"
            f"📆 {tmr_s}（{tmr_wd}）\n{DIV}"
        ]

        # ── 明日行程 ──
        scheds = get_schedules_effective_on(tmr_s)
        if scheds:
            scheds.sort(key=lambda x: x.get("time", "99:99"))
            lines = [f"📅 *明日行程（{len(scheds)}）*"]
            for s in scheds:
                t = s.get("time", "")
                prefix = t if t else "全天"
                cat = s.get("category", "")
                cat_s = f" [{cat}]" if cat else ""
                lines.append(f"  • {prefix} {s.get('title', '')}{cat_s}")
            secs.append("\n".join(lines))

        # ── 逾期 + 明日到期待辦 ──
        todos = get_pending_todos()
        overdue_t = [
            t for t in todos
            if t.get("due_date", "9999") < self.today_s
        ]
        tmr_t = [
            t for t in todos
            if t.get("due_date") == tmr_s
        ]

        if overdue_t or tmr_t:
            lines = ["📝 *待辦提醒*"]

            if overdue_t:
                lines.append(f"⚠️ 逾期 {len(overdue_t)} 項：")
                for t in sorted(overdue_t, key=lambda x: x.get("due_date", ""))[:5]:
                    d = abs(day_diff(t["due_date"], self.today))
                    ico = PRIO_ICON.get(t.get("priority", ""), "⚪")
                    lines.append(f"  {ico} {t.get('title', '')}（逾期 {d} 天）")
                if len(overdue_t) > 5:
                    lines.append(f"  …還有 {len(overdue_t) - 5} 項")

            if tmr_t:
                lines.append(f"📌 明日到期 {len(tmr_t)} 項：")
                for t in tmr_t:
                    ico = PRIO_ICON.get(t.get("priority", ""), "⚪")
                    lines.append(f"  {ico} {t.get('title', '')}")

            secs.append("\n".join(lines))

        # ── 明日付款 ──
        payments = get_pending_payments()
        overdue_p = [
            p for p in payments
            if p.get("due_date", "9999") < self.today_s
        ]
        tmr_p = [
            p for p in payments
            if p.get("due_date") == tmr_s
        ]

        if overdue_p or tmr_p:
            lines = ["💳 *付款提醒*"]
            if overdue_p:
                total = sum(fmt_float(p.get("amount", 0)) for p in overdue_p)
                lines.append(f"⚠️ 逾期 {len(overdue_p)} 筆（{fmt_amount(total)}）")
            if tmr_p:
                total = sum(fmt_float(p.get("amount", 0)) for p in tmr_p)
                lines.append(f"📌 明日到期 {len(tmr_p)} 筆（{fmt_amount(total)}）：")
                for p in tmr_p:
                    lines.append(
                        f"  • {p.get('title', '?')} "
                        f"{fmt_amount(p.get('amount', 0))}"
                    )
            secs.append("\n".join(lines))

        # ── 明日訂閱扣款 ──
        subs = get_active_subscriptions()
        tmr_sub = [
            s for s in subs
            if s.get("next_due") == tmr_s
        ]

        if tmr_sub:
            total = sum(fmt_float(s.get("amount", 0)) for s in tmr_sub)
            lines = [f"📦 *明日扣款（{len(tmr_sub)} 項，{fmt_amount(total)}）*"]
            for s in tmr_sub:
                lines.append(
                    f"  • {s.get('name', '?')} "
                    f"{fmt_amount(s.get('amount', 0))}"
                )
            secs.append("\n".join(lines))

        # ── 明日工作截止 ──
        work = get_active_work()
        tmr_w = [
            w for w in work
            if w.get("deadline") == tmr_s
        ]

        if tmr_w:
            lines = [f"💼 *明日截止（{len(tmr_w)}）*"]
            for w in tmr_w:
                pct = fmt_int(w.get("progress", 0))
                lines.append(
                    f"  • {w.get('title', '')}\n"
                    f"    {fmt_bar(pct)}"
                )
            secs.append("\n".join(lines))

        # ── 今日健康 ──
        h = self._sec_health()
        if h:
            secs.append(h)

        if len(secs) == 1:
            secs.append("✨ 明天暫無待處理事項，好好休息！")

        secs.append(f"{DIV}\n🌟 晚安，明天也加油！")

        send("\n\n".join(secs))
        logger.info("Evening preview sent")
        return True

    # ============================================================
    #  Morning Section Builders
    # ============================================================

    def _sec_schedules(self, data):
        items = data["schedules"]
        if not items:
            return None

        items.sort(key=lambda x: x.get("time", "99:99"))
        lines = [f"📅 *今日行程（{len(items)}）*"]
        for s in items:
            t = s.get("time", "")
            prefix = t if t else "全天"
            cat = s.get("category", "")
            cat_s = f" [{cat}]" if cat else ""
            lines.append(f"  • {prefix} {s.get('title', '')}{cat_s}")
        return "\n".join(lines)

    def _sec_todos(self, data):
        items = data["todos"]
        if not items:
            return None

        overdue, today_t, upcoming = [], [], []

        for t in items:
            dd = t.get("due_date", "")
            if not dd:
                continue
            if dd < self.today_s:
                overdue.append(t)
            elif dd == self.today_s:
                today_t.append(t)
            elif dd <= self.end_s:
                upcoming.append(t)

        count = len(items)
        has_urgent = overdue or today_t or upcoming

        if not has_urgent:
            return f"📝 *待辦事項（共 {count} 項）*\n無近期到期項目。"

        lines = [f"📝 *待辦事項（共 {count} 項）*"]

        if overdue:
            lines.append(f"⚠️ *逾期 {len(overdue)} 項*")
            for t in sorted(overdue, key=lambda x: x["due_date"]):
                d = abs(day_diff(t["due_date"], self.today))
                ico = PRIO_ICON.get(t.get("priority", ""), "⚪")
                lines.append(f"  {ico} {t.get('title', '')}（逾期 {d} 天）")

        if today_t:
            lines.append(f"🔴 *今日到期 {len(today_t)} 項*")
            for t in today_t:
                ico = PRIO_ICON.get(t.get("priority", ""), "⚪")
                lines.append(f"  {ico} {t.get('title', '')}")

        if upcoming:
            lines.append(f"📌 *{AHEAD} 天內 {len(upcoming)} 項*")
            for t in sorted(upcoming, key=lambda x: x["due_date"]):
                d = day_diff(t["due_date"], self.today)
                lines.append(f"  • {t.get('title', '')}（{day_label(d)}）")

        return "\n".join(lines)

    def _sec_work(self, data):
        items = data["work"]
        if not items:
            return None

        overdue, upcoming = [], []

        for w in items:
            dl = w.get("deadline", "")
            if not dl:
                continue
            if dl < self.today_s:
                overdue.append(w)
            elif dl <= self.end_s:
                upcoming.append(w)

        if not overdue and not upcoming:
            return None

        lines = ["💼 *工作截止*"]

        if overdue:
            lines.append(f"⚠️ *逾期 {len(overdue)} 項*")
            for w in sorted(overdue, key=lambda x: x["deadline"]):
                d = abs(day_diff(w["deadline"], self.today))
                pct = fmt_int(w.get("progress", 0))
                lines.append(
                    f"  • {w.get('title', '')}（逾期 {d} 天）\n"
                    f"    {fmt_bar(pct)}"
                )

        if upcoming:
            lines.append(f"⏰ *{AHEAD} 天內 {len(upcoming)} 項*")
            for w in sorted(upcoming, key=lambda x: x["deadline"]):
                d = day_diff(w["deadline"], self.today)
                pct = fmt_int(w.get("progress", 0))
                lines.append(
                    f"  • {w.get('title', '')}（{day_label(d)}）\n"
                    f"    {fmt_bar(pct)}"
                )

        return "\n".join(lines)

    def _sec_payments(self, data):
        items = data["payments"]
        if not items:
            return None

        overdue, today_p, upcoming = [], [], []

        for p in items:
            dd = p.get("due_date", "")
            if not dd:
                continue
            if dd < self.today_s:
                overdue.append(p)
            elif dd == self.today_s:
                today_p.append(p)
            elif dd <= self.end_s:
                upcoming.append(p)

        if not overdue and not today_p and not upcoming:
            return None

        lines = ["💰 *付款提醒*"]

        if overdue:
            total = sum(fmt_float(p.get("amount", 0)) for p in overdue)
            lines.append(f"⚠️ *逾期 {len(overdue)} 筆（{fmt_amount(total)}）*")
            for p in sorted(overdue, key=lambda x: x["due_date"]):
                d = abs(day_diff(p["due_date"], self.today))
                lines.append(
                    f"  • {p.get('title', '?')} "
                    f"{fmt_amount(p.get('amount', 0))}（逾期 {d} 天）"
                )

        if today_p:
            total = sum(fmt_float(p.get("amount", 0)) for p in today_p)
            lines.append(f"🔴 *今日到期 {len(today_p)} 筆（{fmt_amount(total)}）*")
            for p in today_p:
                lines.append(
                    f"  • {p.get('title', '?')} "
                    f"{fmt_amount(p.get('amount', 0))}"
                )

        if upcoming:
            total = sum(fmt_float(p.get("amount", 0)) for p in upcoming)
            lines.append(f"📌 *{AHEAD} 天內 {len(upcoming)} 筆（{fmt_amount(total)}）*")
            for p in sorted(upcoming, key=lambda x: x["due_date"]):
                d = day_diff(p["due_date"], self.today)
                lines.append(
                    f"  • {p.get('title', '?')} "
                    f"{fmt_amount(p.get('amount', 0))}（{day_label(d)}）"
                )

        return "\n".join(lines)

    def _sec_subs(self, data):
        items = data["subs"]
        if not items:
            return None

        due_soon = [
            s for s in items
            if s.get("next_due", "9999") <= self.end_s
        ]

        if not due_soon:
            return None

        due_soon.sort(key=lambda x: x.get("next_due", ""))
        total = sum(fmt_float(s.get("amount", 0)) for s in due_soon)

        lines = [f"📦 *訂閱扣款（{len(due_soon)} 項，{fmt_amount(total)}）*"]
        for s in due_soon:
            d = day_diff(s["next_due"], self.today)
            cycle = s.get("cycle", "")
            cycle_s = f" [{cycle}]" if cycle else ""
            lines.append(
                f"  • {s.get('name', '?')} "
                f"{fmt_amount(s.get('amount', 0))}（{day_label(d)}）{cycle_s}"
            )
        return "\n".join(lines)

    def _sec_stats(self, data):
        s_count = len(data["schedules"])
        t_all   = data["todos"]
        w_count = len(data["work"])
        p_all   = data["payments"]
        sub_all = data["subs"]

        t_total   = len(t_all)
        t_overdue = sum(1 for t in t_all if t.get("due_date", "9999") < self.today_s)
        p_amount  = sum(fmt_float(p.get("amount", 0)) for p in p_all)
        s_due     = sum(1 for s in sub_all if s.get("next_due", "9999") <= self.end_s)

        if not any([s_count, t_total, w_count, p_all, sub_all]):
            return None

        t_str = str(t_total)
        if t_overdue:
            t_str += f"（{t_overdue}⚠️）"

        lines = [
            "📊 *總覽*",
            f"  行程 {s_count} ∣ 待辦 {t_str} ∣ 工作 {w_count}",
        ]

        money_parts = []
        if p_all:
            money_parts.append(f"待付 {fmt_amount(p_amount)}（{len(p_all)} 筆）")
        if s_due:
            money_parts.append(f"訂閱 {s_due} 項近期扣款")
        if money_parts:
            lines.append(f"  {'∣'.join(money_parts)}")

        return "\n".join(lines)

    # ============================================================
    #  Evening Section Builder — Health
    # ============================================================

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
            info = HEALTH_MEAL_DISPLAY[meal_type]
            emoji, label = info["emoji"], info["label"]
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

            # At 21:00 the day is nearly complete. If a main meal is unrecorded we
            # substitute the full TDEE rather than show a falsely optimistic figure.
            # The /health command shows raw totals regardless of completeness.
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

    # ============================================================
    #  Auto-generate Recurring Finance Records
    # ============================================================

    def _generate_recurring_records(self):
        """Auto-generate FIN records from recurring templates on the 1st of the month."""
        if self.today.day != 1:
            return 0

        owner_id = get_owner_id()
        templates = get_active_recurring_templates(owner_id)
        month_prefix = self.today_s[:7]
        generated = 0

        for t in templates:
            end_month = t.get("end_month")
            if end_month and end_month < month_prefix:
                continue  # past end_month, skip

            fin_type = t.get("fin_type", "income")
            ulid = t["SK"].split("#", 1)[1]

            # Dedup: skip if a FIN record with this recurring_id already exists this month
            existing = get_fin_records_for_month(owner_id, fin_type, month_prefix)
            if any(r.get("recurring_id") == ulid for r in existing):
                continue

            # Create the FIN record
            day = t.get("day_of_month", 1)
            record_date = f"{month_prefix}-{day:02d}"
            new_ulid = generate_ulid()
            sid = next_short_id("FIN")
            item = {
                "PK": f"USER#{owner_id}",
                "SK": f"FIN#{new_ulid}",
                "GSI1PK": f"USER#{owner_id}#FIN#{fin_type}",
                "GSI1SK": f"{record_date}#{new_ulid}",
                "GSI3PK": "FIN",
                "GSI3SK": f"{sid:05d}",
                "entity_type": "FIN",
                "fin_type": fin_type,
                "title": t.get("title", ""),
                "amount": t.get("amount"),
                "date": record_date,
                "category": t.get("category", "other"),
                "notes": t.get("notes"),
                "status": "paid",
                "recurring_id": ulid,
                "short_id": sid,
            }
            put_item(item)
            generated += 1

        return generated