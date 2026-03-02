# webhook_handler/handlers/start.py
# ============================================================
# /start — 歡迎訊息
# ============================================================

import logging
from bot_telegram import send_message, build_inline_keyboard

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
        "輸入 /help 查看完整使用說明。"
    )
    rows = [
        [{"text": "📖 查看使用說明", "callback_data": "help_back_new"}],
    ]
    send_message(chat_id, text, reply_markup=build_inline_keyboard(rows))