# webhook_handler/handlers/help_module.py
# ============================================================
# 說明模組 — /help 互動式教學，含各模組詳細指令說明
# ============================================================

import logging

from bot_telegram import (
    send_message,
    edit_message_text,
    build_inline_keyboard,
)

logger = logging.getLogger(__name__)

# ================================================================
#  Module help content registry
# ================================================================

_HELP_MODULES = {
    "overview": {
        "title": "📋 指令總覽",
        "content": (
            "📋 *所有可用指令*\n\n"

            "*📅 行程管理*\n"
            "/add\\_schedule — 新增行程\n"
            "/today — 今日行程\n"
            "/week — 未來 7 天行程\n"
            "/cancel\\_schedule `ID` — 取消行程\n\n"

            "*📝 待辦事項*\n"
            "/add\\_todo — 新增待辦\n"
            "/todos — 查看待辦清單\n"
            "/done `ID` — 完成待辦\n"
            "/del\\_todo `ID` — 刪除待辦\n\n"

            "*🔨 工作進度*\n"
            "/add\\_work — 新增工作\n"
            "/work — 查看進行中工作\n"
            "/update\\_progress `ID` `%` — 更新進度\n"
            "/deadlines — 即將到期工作\n\n"

            "*💰 財務管理*\n"
            "/add\\_payment — 新增應付款項\n"
            "/add\\_income — 新增收入\n"
            "/add\\_expense — 新增支出\n"
            "/payments — 查看待付款項\n"
            "/paid `ID` — 標記已付\n"
            "/del\\_fin `ID` — 刪除財務記錄\n"
            "/edit\\_fin `ID` — 編輯財務記錄\n"
            "/finance\\_summary `[YYYY-MM]` — 月度財務統計\n\n"

            "*📦 訂閱管理*\n"
            "/add\\_sub — 新增訂閱\n"
            "/subs — 查看訂閱列表\n"
            "/sub\\_due — 即將到期訂閱\n"
            "/renew\\_sub `ID` — 手動續訂\n"
            "/pause\\_sub `ID` — 暫停訂閱\n"
            "/resume\\_sub `ID` — 恢復訂閱\n"
            "/cancel\\_sub `ID` — 取消訂閱\n"
            "/edit\\_sub `ID` — 編輯訂閱\n"
            "/sub\\_cost — 訂閱費用統計\n\n"

            "*📊 綜合查詢*\n"
            "/summary — 每日摘要\n"
            "/search `關鍵字` — 全域搜尋\n"
            "/monthly\\_report — 月度報表\n\n"

            "*⚙️ 系統*\n"
            "/help — 查看說明\n"
            "/cancel — 取消當前操作"
        ),
    },

    "schedule": {
        "title": "📅 行程管理",
        "content": (
            "📅 *行程管理 — 使用說明*\n\n"

            "*新增行程*\n"
            "指令：/add\\_schedule\n"
            "Bot 會依序詢問：\n"
            "1️⃣ 標題 — 輸入行程名稱\n"
            "2️⃣ 日期 — 支援多種格式（見下方）\n"
            "3️⃣ 時間 — `HH:MM` 格式，可跳過\n"
            "4️⃣ 分類 — 點選按鈕\n"
            "5️⃣ 備註 — 可跳過\n"
            "6️⃣ 確認 — 確認後儲存\n\n"

            "*查看行程*\n"
            "• /today — 顯示今天的所有行程\n"
            "• /week — 顯示未來 7 天行程，按日期分組\n\n"

            "*取消行程*\n"
            "• `/cancel_schedule 3` — 取消 ID 為 3 的行程\n\n"

            "*📆 日期格式範例*\n"
            "• `今天`、`明天`、`後天`、`大後天`\n"
            "• `下週一` ~ `下週日`\n"
            "• `下個月15號`\n"
            "• `2026-03-15` 或 `03/15` 或 `3/15`\n\n"

            "*💡 小提示*\n"
            "• 每個行程有唯一 ID，用於取消操作\n"
            "• 行程按時間排序，全天事件排在最前\n"
            "• 任何時候輸入 /cancel 可中止新增流程"
        ),
    },

    "todo": {
        "title": "📝 待辦事項",
        "content": (
            "📝 *待辦事項 — 使用說明*\n\n"

            "*新增待辦*\n"
            "指令：/add\\_todo\n"
            "Bot 會依序詢問：\n"
            "1️⃣ 標題 — 輸入待辦名稱\n"
            "2️⃣ 截止日 — 可跳過（無截止日）\n"
            "3️⃣ 優先級 — 🔴高 / 🟡中 / 🟢低\n"
            "4️⃣ 分類 — 點選按鈕\n"
            "5️⃣ 備註 — 可跳過\n"
            "6️⃣ 確認 — 確認後儲存\n\n"

            "*查看待辦*\n"
            "• /todos — 顯示所有未完成待辦\n"
            "• 按優先級排序，高優先在前\n"
            "• 逾期項目會標記 ⚠️\n\n"

            "*完成待辦*\n"
            "• `/done 3` — 標記 ID 3 為已完成\n\n"

            "*刪除待辦*\n"
            "• `/del_todo 3` — 刪除 ID 3 的待辦\n\n"

            "*💡 小提示*\n"
            "• 建議善用優先級，讓重要事項一目了然\n"
            "• 沒有截止日的待辦會排在最後\n"
            "• 完成與刪除是不同的——完成會記錄在報表中"
        ),
    },

    "work": {
        "title": "🔨 工作進度",
        "content": (
            "🔨 *工作進度 — 使用說明*\n\n"

            "*新增工作*\n"
            "指令：/add\\_work\n"
            "Bot 會依序詢問：\n"
            "1️⃣ 標題 — 輸入工作名稱\n"
            "2️⃣ 描述 — 可跳過\n"
            "3️⃣ 截止日 — 可跳過（無截止日）\n"
            "4️⃣ 分類 — 點選按鈕\n"
            "5️⃣ 確認 — 確認後儲存（初始進度 0%）\n\n"

            "*查看工作*\n"
            "• /work — 顯示所有進行中工作\n"
            "• 按截止日排序，含進度條顯示\n\n"

            "*更新進度*\n"
            "• `/update_progress 1 45` — 將 ID 1 的進度更新為 45%\n"
            "• `/update_progress 1 100` — 進度達 100% 時自動標記完成 🎉\n\n"

            "*即將到期*\n"
            "• /deadlines — 顯示 7 天內到期的工作\n"
            "• 分為「已逾期」和「即將到期」兩區\n\n"

            "*💡 小提示*\n"
            "• 進度條會視覺化顯示：█████░░░░░ 50%\n"
            "• 設定 100% 會自動將工作標記為完成\n"
            "• 用 /deadlines 掌握緊急工作"
        ),
    },

    "finance": {
        "title": "💰 財務管理",
        "content": (
            "💰 *財務管理 — 使用說明*\n\n"

            "*三種記帳類型*\n"
            "💳 /add\\_payment — 應付款項（有到期日，需標記已付）\n"
            "💵 /add\\_income — 收入（記錄後即完成）\n"
            "💸 /add\\_expense — 支出（記錄後即完成）\n\n"

            "*新增流程*（三者相同）\n"
            "1️⃣ 名稱 — 輸入項目名稱\n"
            "2️⃣ 金額 — 如 `1500` 或 `299.50`\n"
            "3️⃣ 日期 — 到期日/收入日/支出日\n"
            "4️⃣ 分類 — 點選按鈕（10 種分類）\n"
            "5️⃣ 備註 — 可跳過\n"
            "6️⃣ 確認\n\n"

            "*管理款項*\n"
            "• /payments — 查看所有待付款項\n"
            "• `/paid 3` — 標記 ID 3 為已付\n"
            "• 逾期款項會標記 ⚠️\n\n"

            "*月度統計*\n"
            "• /finance\\_summary — 本月收支統計\n"
            "• 含收入、支出、已付款、待付款\n"
            "• 自動計算淨額和支出分類明細\n\n"

            "*💡 小提示*\n"
            "• 應付款項適合記錄帳單、房租等\n"
            "• 收入/支出記錄後不需額外操作\n"
            "• 每月用 /finance\\_summary 檢視花費分佈"
        ),
    },

    "subscription": {
        "title": "📦 訂閱管理",
        "content": (
            "📦 *訂閱管理 — 使用說明*\n\n"

            "*新增訂閱*\n"
            "指令：/add\\_sub\n"
            "1️⃣ 名稱 — 如 Netflix、Spotify\n"
            "2️⃣ 金額 — 每期扣款金額\n"
            "3️⃣ 週期 — 每月/每季/每年\n"
            "4️⃣ 帳單日 — 1-31 號\n"
            "5️⃣ 下次扣款日\n"
            "6️⃣ 分類 — 串流/軟體/雲端 等\n"
            "7️⃣ 備註 — 可跳過\n"
            "8️⃣ 確認\n\n"

            "*查看訂閱*\n"
            "• /subs — 所有訂閱（啟用+暫停）\n"
            "• /sub\\_due — 7 天內到期的訂閱\n"
            "• /sub\\_cost — 費用統計（月/年估算，分類明細）\n\n"

            "*管理訂閱*\n"
            "• `/renew_sub 1` — 手動續訂，自動推算下次日期\n"
            "• `/pause_sub 1` — 暫停（不會出現在到期提醒）\n"
            "• `/resume_sub 1` — 恢復（需輸入新的扣款日）\n"
            "• `/cancel_sub 1` — 取消（會要求確認）\n"
            "• `/edit_sub 1` — 編輯（可改名稱/金額/週期等）\n\n"

            "*💡 小提示*\n"
            "• 續訂會根據週期自動計算下次扣款日\n"
            "• 暫停的訂閱不計入月費統計\n"
            "• 取消後無法恢復，請謹慎操作\n"
            "• 用 /sub\\_cost 查看每月訂閱花了多少錢"
        ),
    },

    "query": {
        "title": "📊 綜合查詢",
        "content": (
            "📊 *綜合查詢 — 使用說明*\n\n"

            "*每日摘要*\n"
            "指令：/summary\n"
            "一次查看今天的所有重要事項：\n"
            "• 📅 今日行程\n"
            "• 📝 待辦事項（逾期警告）\n"
            "• 🔨 即將到期工作\n"
            "• 💳 待付款項\n"
            "• 📦 即將扣款訂閱\n\n"

            "*全域搜尋*\n"
            "指令：`/search 關鍵字`\n"
            "• 搜尋所有模組：行程、待辦、工作、財務、訂閱\n"
            "• 比對標題、描述、備註、名稱\n"
            "• 最多顯示 20 筆結果\n"
            "• 範例：`/search 會議`、`/search Netflix`\n\n"

            "*月度報表*\n"
            "指令：/monthly\\_report\n"
            "本月完整統計：\n"
            "• 📅 行程數量與分類\n"
            "• 📝 待辦完成率\n"
            "• 🔨 工作進度與分類\n"
            "• 💰 收支明細與 Top 3 支出\n"
            "• 📦 訂閱月費估算\n"
            "• 💡 本月總支出估算\n\n"

            "*💡 小提示*\n"
            "• 建議每天早上用 /summary 掌握當日重點\n"
            "• 月底用 /monthly\\_report 回顧整月表現\n"
            "• /search 找不到？試試不同關鍵字"
        ),
    },

    "tips": {
        "title": "💡 使用技巧",
        "content": (
            "💡 *使用技巧*\n\n"

            "*🔤 通用操作*\n"
            "• 任何新增流程中，輸入 /cancel 可立即中止\n"
            "• 新增流程中可直接輸入新的新增指令來覆蓋\n"
            "• 每個項目都有唯一短 ID，用於後續操作\n\n"

            "*📆 日期輸入*\n"
            "所有需要日期的地方都支援：\n"
            "• 中文：`今天`、`明天`、`後天`、`大後天`\n"
            "• 中文：`下週一` ~ `下週日`\n"
            "• 中文：`下個月15號`\n"
            "• 標準格式：`2026-03-15`\n"
            "• 簡寫：`03/15` 或 `3/15`（自動判斷年份）\n\n"

            "*💲 金額輸入*\n"
            "• 整數：`1500`\n"
            "• 小數：`299.50`（最多兩位小數）\n"
            "• 支援千分位：`1,500`\n\n"

            "*📱 快速工作流*\n"
            "每日建議流程：\n"
            "1. 早上 → /summary 查看今日重點\n"
            "2. 完成事項 → /done ID\n"
            "3. 記帳 → /add\\_expense\n"
            "4. 月底 → /monthly\\_report 回顧\n\n"

            "*⚙️ 對話狀態*\n"
            "• 每個新增流程有 30 分鐘超時\n"
            "• 超時後會自動失效\n"
            "• 同一時間只能進行一個新增操作"
        ),
    },
}

# Button layout for the help menu
_HELP_MENU_ROWS = [
    [
        {"text": "📋 指令總覽", "callback_data": "help_overview"},
    ],
    [
        {"text": "📅 行程管理", "callback_data": "help_schedule"},
        {"text": "📝 待辦事項", "callback_data": "help_todo"},
    ],
    [
        {"text": "🔨 工作進度", "callback_data": "help_work"},
        {"text": "💰 財務管理", "callback_data": "help_finance"},
    ],
    [
        {"text": "📦 訂閱管理", "callback_data": "help_subscription"},
        {"text": "📊 綜合查詢", "callback_data": "help_query"},
    ],
    [
        {"text": "💡 使用技巧", "callback_data": "help_tips"},
    ],
]

# Text alias mapping for /help <module>
_HELP_ALIASES = {
    "schedule":     "schedule",
    "行程":         "schedule",
    "todo":         "todo",
    "待辦":         "todo",
    "work":         "work",
    "工作":         "work",
    "finance":      "finance",
    "財務":         "finance",
    "subscription": "subscription",
    "sub":          "subscription",
    "訂閱":         "subscription",
    "query":        "query",
    "查詢":         "query",
    "tips":         "tips",
    "技巧":         "tips",
    "overview":     "overview",
    "all":          "overview",
    "全部":         "overview",
}


# ================================================================
#  /help [module] — Entry point
# ================================================================

def handle_help(chat_id, args=""):
    """
    /help           → show interactive menu
    /help schedule  → show schedule help directly
    /help 待辦      → show todo help directly
    """
    args = args.strip().lower()

    if args:
        module_key = _HELP_ALIASES.get(args)
        if module_key and module_key in _HELP_MODULES:
            _send_module_help(chat_id, module_key)
            return
        else:
            send_message(
                chat_id,
                f"❌ 未知的模組：`{args}`\n\n"
                "可用模組：`schedule`、`todo`、`work`、`finance`、`subscription`、`query`、`tips`",
            )
            return

    # No args → show interactive menu
    text = (
        "📖 *使用說明*\n\n"
        "歡迎使用私人秘書 Bot！\n"
        "請選擇要查看的模組說明：\n\n"
        "你也可以直接輸入：\n"
        "`/help schedule` 或 `/help 行程`"
    )
    send_message(
        chat_id,
        text,
        reply_markup=build_inline_keyboard(_HELP_MENU_ROWS),
    )


# ================================================================
#  Callback handler (called from router standalone callback)
# ================================================================

def handle_help_callback(user_id, chat_id, message_id, callback_data):
    """
    Handle help_* callbacks.
    Returns True if handled, False otherwise.
    """
    if not callback_data.startswith("help_"):
        return False

    module_key = callback_data[len("help_"):]
    if module_key not in _HELP_MODULES:
        return False

    module = _HELP_MODULES[module_key]

    # Build back button
    back_rows = [
        [{"text": "⬅️ 返回說明選單", "callback_data": "help_back"}],
    ]

    edit_message_text(
        chat_id,
        message_id,
        module["content"],
        reply_markup=build_inline_keyboard(back_rows),
    )
    return True


def handle_help_back_callback(user_id, chat_id, message_id):
    """Handle the back button — return to help menu."""
    text = (
        "📖 *使用說明*\n\n"
        "歡迎使用私人秘書 Bot！\n"
        "請選擇要查看的模組說明：\n\n"
        "你也可以直接輸入：\n"
        "`/help schedule` 或 `/help 行程`"
    )
    edit_message_text(
        chat_id,
        message_id,
        text,
        reply_markup=build_inline_keyboard(_HELP_MENU_ROWS),
    )


# ================================================================
#  Helper — send module help as a new message
# ================================================================

def _send_module_help(chat_id, module_key):
    """Send module help as a new message (for /help <module>)."""
    module = _HELP_MODULES[module_key]
    back_rows = [
        [{"text": "📖 查看其他模組", "callback_data": "help_back_new"}],
    ]
    send_message(
        chat_id,
        module["content"],
        reply_markup=build_inline_keyboard(back_rows),
    )