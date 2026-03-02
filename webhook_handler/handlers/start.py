# webhook_handler/handlers/start.py
# ============================================================
# /start  和  /help
# ============================================================

import logging
from bot_telegram import send_message

logger = logging.getLogger(__name__)


def handle_start(chat_id):
    text = (
        "👋 *歡迎使用私人秘書 Bot！*\n\n"
        "我可以幫你管理：\n"
        "📅 行程安排\n"
        "📝 待辦事項\n"
        "🔨 工作進度\n"
        "💰 財務管理\n"
        "📦 訂閱管理\n\n"
        "輸入 /help 查看所有可用指令。"
    )
    send_message(chat_id, text)


def handle_help(chat_id):
    text = (
        "📋 *可用指令*\n\n"

        "*📅 行程管理*\n"
        "/add\\_schedule — 新增行程\n"
        "/today — 今日行程\n"
        "/week — 未來 7 天行程\n"
        "/cancel\\_schedule `ID` — 取消行程\n\n"

        "*📝 待辦事項*\n"
        "/add\\_todo — 新增待辦\n"
        "/todos — 查看待辦\n"
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
        "/payments — 待付款項\n"
        "/paid `ID` — 標記已付\n"
        "/finance\\_summary — 月度統計\n\n"

        "*📦 訂閱管理*\n"
        "/add\\_sub — 新增訂閱\n"
        "/subs — 查看訂閱\n"
        "/sub\\_due — 即將到期訂閱\n"
        "/renew\\_sub `ID` — 手動續訂\n"
        "/pause\\_sub `ID` — 暫停訂閱\n"
        "/resume\\_sub `ID` — 恢復訂閱\n"
        "/cancel\\_sub `ID` — 取消訂閱\n"
        "/edit\\_sub `ID` — 編輯訂閱\n"
        "/sub\\_cost — 費用統計\n\n"

        "*📊 綜合查詢*\n"
        "/summary — 每日摘要\n"
        "/search `關鍵字` — 搜尋\n"
        "/monthly\\_report — 月度報表\n\n"

        "*⚙️ 系統*\n"
        "/cancel — 取消當前操作"
    )
    send_message(chat_id, text)