# tests/test_router.py
# ============================================================
# Unit tests for webhook_handler/handlers/router.py.
# Tests routing logic, owner verification, conversation
# dispatch, and the /cancel command.
# ============================================================

import pytest
from unittest.mock import patch, MagicMock

from handlers.router import route_update

OWNER_ID = 123
CHAT_ID = 456
MSG_ID = 789

# Helper to build a minimal Telegram message update
def _msg_update(text, user_id=OWNER_ID):
    return {
        "message": {
            "from": {"id": user_id},
            "chat": {"id": CHAT_ID},
            "text": text,
        }
    }

# Helper to build a callback query update
def _cb_update(data, user_id=OWNER_ID):
    return {
        "callback_query": {
            "id": "cb123",
            "from": {"id": user_id},
            "message": {"chat": {"id": CHAT_ID}, "message_id": MSG_ID},
            "data": data,
        }
    }


# ================================================================
#  Owner verification
# ================================================================

class TestOwnerVerification:
    def test_unknown_user_gets_blocked(self):
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.send_message") as mock_send:
            route_update(_msg_update("/help", user_id=999))
            mock_send.assert_called_once()
            assert "無權" in mock_send.call_args[0][1]

    def test_owner_is_not_blocked(self):
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.get_conversation", return_value=None), \
             patch("handlers.router.send_message") as mock_send:
            route_update(_msg_update("/unknown_xyz"))
            # Should reach the command handler, not the auth block
            assert "無權" not in mock_send.call_args[0][1]


# ================================================================
#  Unknown command
# ================================================================

class TestUnknownCommand:
    def test_unknown_command_sends_error(self):
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.get_conversation", return_value=None), \
             patch("handlers.router.send_message") as mock_send:
            route_update(_msg_update("/not_a_real_command"))
            mock_send.assert_called_once()
            assert "未知指令" in mock_send.call_args[0][1]

    def test_unknown_command_includes_command_name(self):
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.get_conversation", return_value=None), \
             patch("handlers.router.send_message") as mock_send:
            route_update(_msg_update("/no_such_cmd"))
            assert "/no_such_cmd" in mock_send.call_args[0][1]


# ================================================================
#  Non-command plain text
# ================================================================

class TestNonCommandText:
    def test_plain_text_without_conversation_prompts_help(self):
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.get_conversation", return_value=None), \
             patch("handlers.router.send_message") as mock_send:
            route_update(_msg_update("hello"))
            mock_send.assert_called_once()
            assert "請輸入指令" in mock_send.call_args[0][1]


# ================================================================
#  /cancel command
# ================================================================

class TestCancelCommand:
    def test_cancel_with_active_conv_clears_it(self):
        conv = {"module": "health", "step": "calories", "data": {}}
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.get_conversation", return_value=conv), \
             patch("handlers.router.delete_conversation") as mock_del, \
             patch("handlers.router.send_message") as mock_send:
            route_update(_msg_update("/cancel"))
            mock_del.assert_called_once_with(OWNER_ID)
            assert "已取消" in mock_send.call_args[0][1]

    def test_cancel_without_active_conv_says_nothing_to_cancel(self):
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.get_conversation", return_value=None), \
             patch("handlers.router.delete_conversation") as mock_del, \
             patch("handlers.router.send_message") as mock_send:
            route_update(_msg_update("/cancel"))
            mock_del.assert_not_called()
            assert "沒有" in mock_send.call_args[0][1]


# ================================================================
#  Command during active conversation
# ================================================================

class TestCommandDuringConversation:
    def test_regular_command_during_conv_warns_user(self):
        conv = {"module": "health", "step": "calories", "data": {}}
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.get_conversation", return_value=conv), \
             patch("handlers.router.send_message") as mock_send:
            # /work is not a conversation starter
            route_update(_msg_update("/work"))
            assert "正在進行" in mock_send.call_args[0][1]

    def test_conversation_starter_during_conv_overrides_it(self):
        conv = {"module": "health", "step": "calories", "data": {}}
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.get_conversation", return_value=conv), \
             patch("handlers.router.send_message"), \
             patch("handlers.health.set_conversation") as mock_set_conv, \
             patch("handlers.health.get_item", return_value=None):
            # /set_health is in CONVERSATION_STARTER_COMMANDS → should start new flow
            route_update(_msg_update("/set_health"))
            mock_set_conv.assert_called_once()


# ================================================================
#  Conversation step dispatch
# ================================================================

class TestConversationStepDispatch:
    def test_health_step_dispatched_to_health_handler(self):
        conv = {"module": "health", "step": "calories", "data": {"meal_type": "lunch", "date": "2026-03-03"}}
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.get_conversation", return_value=conv), \
             patch("handlers.health.handle_step") as mock_step, \
             patch("handlers.health.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.health.put_item"), \
             patch("handlers.health.delete_conversation"), \
             patch("handlers.health.send_message"), \
             patch("handlers.health.query_gsi1", return_value=[]), \
             patch("handlers.health.get_item", return_value=None), \
             patch("handlers.health.get_today", return_value="2026-03-03"), \
             patch("handlers.health.get_weekday_name", return_value="週二"), \
             patch("handlers.health.get_now") as mock_now:
            mock_now.return_value.isoformat.return_value = "ts"
            route_update(_msg_update("800"))
            mock_step.assert_called_once_with(
                OWNER_ID, CHAT_ID, "800",
                conv["step"], conv["data"],
            )

    def test_set_health_step_dispatched_to_health_handler(self):
        conv = {"module": "set_health", "step": "tdee", "data": {}}
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.get_conversation", return_value=conv), \
             patch("handlers.health.handle_step") as mock_step:
            route_update(_msg_update("2200"))
            mock_step.assert_called_once_with(
                OWNER_ID, CHAT_ID, "2200",
                conv["step"], conv["data"],
            )


# ================================================================
#  Callback query dispatch
# ================================================================

class TestCallbackDispatch:
    def test_unauthorized_callback_gets_blocked(self):
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.answer_callback_query") as mock_answer:
            route_update(_cb_update("meal_breakfast", user_id=999))
            mock_answer.assert_called_once_with("cb123", "⛔ 無權操作")

    def test_health_callback_dispatched_to_health_handler(self):
        conv = {"module": "health", "step": "meal_type", "data": {}}
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.get_conversation", return_value=conv), \
             patch("handlers.router.answer_callback_query"), \
             patch("handlers.health.handle_callback") as mock_cb:
            route_update(_cb_update("meal_breakfast"))
            mock_cb.assert_called_once_with(
                OWNER_ID, CHAT_ID, MSG_ID,
                "meal_breakfast", conv["step"], conv["data"],
            )

    def test_set_health_callback_dispatched_to_health_handler(self):
        conv = {"module": "set_health", "step": "confirm", "data": {"tdee": 2200, "deficit": 500}}
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.get_conversation", return_value=conv), \
             patch("handlers.router.answer_callback_query"), \
             patch("handlers.health.handle_callback") as mock_cb:
            route_update(_cb_update("sethealth_confirm"))
            mock_cb.assert_called_once_with(
                OWNER_ID, CHAT_ID, MSG_ID,
                "sethealth_confirm", conv["step"], conv["data"],
            )

    def test_help_standalone_callback_dispatched(self):
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.get_conversation", return_value=None), \
             patch("handlers.router.answer_callback_query"), \
             patch("handlers.help_module.handle_help_callback",
                   return_value=True) as mock_help_cb:
            route_update(_cb_update("help_schedule"))
            mock_help_cb.assert_called_once()

    def test_message_with_no_text_is_ignored(self):
        update = {
            "message": {
                "from": {"id": OWNER_ID},
                "chat": {"id": CHAT_ID},
                # no "text" key
            }
        }
        with patch("handlers.router.get_owner_id", return_value=OWNER_ID), \
             patch("handlers.router.send_message") as mock_send:
            route_update(update)
            mock_send.assert_not_called()
