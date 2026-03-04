# tests/test_recurring_handler.py
import pytest
from decimal import Decimal
from unittest.mock import patch, MagicMock

from handlers.recurring import (
    handle_recurring,
    handle_del_recurring,
    handle_pause_recurring,
    handle_resume_recurring,
    handle_add_recurring,
    handle_step as recurring_handle_step,
    handle_edit_recurring,
    handle_callback,
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
             patch("handlers.recurring.query_gsi1", side_effect=[[_template()], []]), \
             patch("handlers.recurring.send_message") as mock_send:
            handle_recurring(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "薪水" in msg
            assert "20,000" in msg

    def test_empty_list_shows_hint(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.query_gsi1", side_effect=[[], []]), \
             patch("handlers.recurring.send_message") as mock_send:
            handle_recurring(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "尚無" in msg or "add_recurring" in msg.lower()

    def test_shows_paused_templates(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.query_gsi1", side_effect=[[], [_template(status="paused")]]), \
             patch("handlers.recurring.send_message") as mock_send:
            handle_recurring(USER_ID, CHAT_ID)
            msg = mock_send.call_args[0][1]
            assert "薪水" in msg
            assert "暫停" in msg


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

    def test_found_deletes_template(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.query_gsi3", return_value=_template()), \
             patch("handlers.recurring.delete_item") as mock_del, \
             patch("handlers.recurring.send_message") as mock_send:
            handle_del_recurring(USER_ID, CHAT_ID, "1")
            assert mock_del.called
            msg = mock_send.call_args[0][1]
            assert "已刪除" in msg


class TestHandlePauseRecurring:
    def test_not_found_shows_error(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.query_gsi3", return_value=None), \
             patch("handlers.recurring.send_message") as mock_send:
            handle_pause_recurring(USER_ID, CHAT_ID, "99")
            assert "❌" in mock_send.call_args[0][1]

    def test_already_paused_shows_warning(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.query_gsi3", return_value=_template(status="paused")), \
             patch("handlers.recurring.send_message") as mock_send:
            handle_pause_recurring(USER_ID, CHAT_ID, "1")
            assert "⚠️" in mock_send.call_args[0][1]

    def test_pauses_active_template(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.query_gsi3", return_value=_template(status="active")), \
             patch("handlers.recurring.update_item") as mock_update, \
             patch("handlers.recurring.send_message") as mock_send:
            handle_pause_recurring(USER_ID, CHAT_ID, "1")
            assert mock_update.called
            assert "已暫停" in mock_send.call_args[0][1]


class TestHandleResumeRecurring:
    def test_not_found_shows_error(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.query_gsi3", return_value=None), \
             patch("handlers.recurring.send_message") as mock_send:
            handle_resume_recurring(USER_ID, CHAT_ID, "99")
            assert "❌" in mock_send.call_args[0][1]

    def test_already_active_shows_warning(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.query_gsi3", return_value=_template(status="active")), \
             patch("handlers.recurring.send_message") as mock_send:
            handle_resume_recurring(USER_ID, CHAT_ID, "1")
            assert "⚠️" in mock_send.call_args[0][1]

    def test_resumes_paused_template(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.query_gsi3", return_value=_template(status="paused")), \
             patch("handlers.recurring.update_item") as mock_update, \
             patch("handlers.recurring.send_message") as mock_send:
            handle_resume_recurring(USER_ID, CHAT_ID, "1")
            assert mock_update.called
            assert "已恢復" in mock_send.call_args[0][1]


class TestAddRecurringConversation:
    def test_start_asks_for_title(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.set_conversation"), \
             patch("handlers.recurring.send_message") as mock_send:
            handle_add_recurring(USER_ID, CHAT_ID)
            assert "標題" in mock_send.call_args[0][1]

    def test_step1_title_saves_and_asks_amount(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.update_conversation") as mock_conv, \
             patch("handlers.recurring.send_message") as mock_send:
            recurring_handle_step(USER_ID, CHAT_ID, "薪水", 1, {})
            assert mock_conv.called
            assert "金額" in mock_send.call_args[0][1]

    def test_step2_invalid_amount_shows_error(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.update_conversation"), \
             patch("handlers.recurring.send_message") as mock_send:
            recurring_handle_step(USER_ID, CHAT_ID, "abc", 2, {"title": "薪水"})
            assert "❌" in mock_send.call_args[0][1]

    def test_step2_valid_amount_asks_type(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.update_conversation"), \
             patch("handlers.recurring.send_message") as mock_send:
            recurring_handle_step(USER_ID, CHAT_ID, "20000", 2, {"title": "薪水"})
            msg = mock_send.call_args[0][1]
            assert "收入" in msg or "支出" in msg

    def test_step4_invalid_day_shows_error(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.update_conversation"), \
             patch("handlers.recurring.send_message") as mock_send:
            recurring_handle_step(USER_ID, CHAT_ID, "32", 4, {"title": "薪水", "amount": "20000"})
            assert "❌" in mock_send.call_args[0][1]

    def test_step4_valid_day_asks_category(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.update_conversation"), \
             patch("handlers.recurring.send_message") as mock_send:
            recurring_handle_step(USER_ID, CHAT_ID, "1", 4, {"title": "薪水", "amount": "20000"})
            msg = mock_send.call_args[0][1]
            assert "分類" in msg

    def test_step6_skip_end_month(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.update_conversation") as mock_conv, \
             patch("handlers.recurring.send_message") as mock_send:
            data = {"title": "薪水", "amount": "20000", "fin_type": "income",
                    "day_of_month": 1, "category": "salary"}
            recurring_handle_step(USER_ID, CHAT_ID, "跳過", 6, data)
            assert data.get("end_month") is None
            assert mock_conv.called
            assert "備註" in mock_send.call_args[0][1]

    def test_step6_invalid_end_month_shows_error(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.update_conversation"), \
             patch("handlers.recurring.send_message") as mock_send:
            data = {"title": "薪水", "amount": "20000", "fin_type": "income",
                    "day_of_month": 1, "category": "salary"}
            recurring_handle_step(USER_ID, CHAT_ID, "bad-format", 6, data)
            assert "❌" in mock_send.call_args[0][1]

    def test_callback_type_income_advances_to_step4(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.update_conversation") as mock_conv, \
             patch("handlers.recurring.send_message") as mock_send:
            data = {"title": "薪水", "amount": "20000"}
            handle_callback(USER_ID, CHAT_ID, 1, "rec_type_income", 3, data)
            assert data["fin_type"] == "income"
            assert mock_conv.called
            assert "幾號" in mock_send.call_args[0][1]

    def test_callback_confirm_saves_template(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.delete_conversation"), \
             patch("handlers.recurring.put_item") as mock_put, \
             patch("handlers.recurring.get_next_short_id", return_value=1), \
             patch("handlers.recurring.generate_ulid", return_value="TESTUUID"), \
             patch("handlers.recurring.send_message") as mock_send:
            data = {
                "title": "薪水",
                "amount": "20000",
                "fin_type": "income",
                "day_of_month": 1,
                "category": "salary",
                "end_month": None,
                "notes": None,
            }
            handle_callback(USER_ID, CHAT_ID, 1, "rec_confirm", 8, data)
            assert mock_put.called
            assert "已新增" in mock_send.call_args[0][1]

    def test_callback_cancel_deletes_conversation(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.delete_conversation") as mock_del, \
             patch("handlers.recurring.send_message") as mock_send:
            handle_callback(USER_ID, CHAT_ID, 1, "rec_cancel", 8, {})
            assert mock_del.called
            assert "取消" in mock_send.call_args[0][1]


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

    def test_edit_step1_skip_keeps_title(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.update_conversation") as mock_conv, \
             patch("handlers.recurring.send_message") as mock_send:
            data = {
                "_module": "edit_recurring",
                "_pk": f"USER#{OWNER_ID}",
                "_sk": "FIN_RECURRING#01ABC",
                "_ulid": "01ABC",
                "title": "薪水",
                "amount": "20000",
                "fin_type": "income",
                "day_of_month": 1,
                "category": "salary",
            }
            recurring_handle_step(USER_ID, CHAT_ID, "跳過", 1, data)
            assert data["title"] == "薪水"  # unchanged
            assert mock_conv.called

    def test_edit_confirm_updates_template(self):
        with patch("handlers.recurring.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.recurring.delete_conversation"), \
             patch("handlers.recurring.update_item") as mock_update, \
             patch("handlers.recurring.query_gsi1", return_value=[]), \
             patch("handlers.recurring.send_message") as mock_send:
            data = {
                "_module": "edit_recurring",
                "_pk": f"USER#{OWNER_ID}",
                "_sk": "FIN_RECURRING#01ABC",
                "_ulid": "01ABC",
                "_short_id": 1,
                "title": "薪水updated",
                "amount": "25000",
                "fin_type": "income",
                "day_of_month": 1,
                "category": "salary",
                "end_month": None,
                "notes": None,
            }
            handle_callback(USER_ID, CHAT_ID, 1, "rec_confirm", 8, data)
            assert mock_update.called
            assert "已更新" in mock_send.call_args[0][1]
