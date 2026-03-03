# tests/test_bot_telegram.py
# ============================================================
# Unit tests for keyboard builder helpers in bot_telegram.py.
# These are pure functions — no network calls involved.
# ============================================================

from bot_telegram import (
    build_inline_keyboard,
    build_confirm_keyboard,
    build_skip_keyboard,
)


# ================================================================
#  build_inline_keyboard
# ================================================================

class TestBuildInlineKeyboard:
    def test_single_button_single_row(self):
        rows = [[{"text": "A", "callback_data": "a"}]]
        result = build_inline_keyboard(rows)
        assert result == {
            "inline_keyboard": [
                [{"text": "A", "callback_data": "a"}]
            ]
        }

    def test_two_buttons_same_row(self):
        rows = [[
            {"text": "Yes", "callback_data": "yes"},
            {"text": "No", "callback_data": "no"},
        ]]
        kb = build_inline_keyboard(rows)
        assert len(kb["inline_keyboard"]) == 1
        assert len(kb["inline_keyboard"][0]) == 2
        assert kb["inline_keyboard"][0][0]["callback_data"] == "yes"
        assert kb["inline_keyboard"][0][1]["callback_data"] == "no"

    def test_two_rows(self):
        rows = [
            [{"text": "Row1", "callback_data": "r1"}],
            [{"text": "Row2", "callback_data": "r2"}],
        ]
        kb = build_inline_keyboard(rows)
        assert len(kb["inline_keyboard"]) == 2
        assert kb["inline_keyboard"][0][0]["text"] == "Row1"
        assert kb["inline_keyboard"][1][0]["text"] == "Row2"

    def test_only_text_and_callback_data_in_buttons(self):
        rows = [[{"text": "X", "callback_data": "x", "extra": "ignored"}]]
        kb = build_inline_keyboard(rows)
        btn = kb["inline_keyboard"][0][0]
        assert set(btn.keys()) == {"text", "callback_data"}

    def test_empty_rows(self):
        kb = build_inline_keyboard([])
        assert kb == {"inline_keyboard": []}


# ================================================================
#  build_confirm_keyboard
# ================================================================

class TestBuildConfirmKeyboard:
    def test_has_two_buttons_in_one_row(self):
        kb = build_confirm_keyboard("yes_data", "no_data")
        assert len(kb["inline_keyboard"]) == 1
        assert len(kb["inline_keyboard"][0]) == 2

    def test_confirm_button_text(self):
        kb = build_confirm_keyboard("yes_data", "no_data")
        btn_yes = kb["inline_keyboard"][0][0]
        assert "確認" in btn_yes["text"]
        assert btn_yes["callback_data"] == "yes_data"

    def test_cancel_button_text(self):
        kb = build_confirm_keyboard("yes_data", "no_data")
        btn_no = kb["inline_keyboard"][0][1]
        assert "取消" in btn_no["text"]
        assert btn_no["callback_data"] == "no_data"

    def test_custom_callback_data(self):
        kb = build_confirm_keyboard("sethealth_confirm", "sethealth_cancel")
        assert kb["inline_keyboard"][0][0]["callback_data"] == "sethealth_confirm"
        assert kb["inline_keyboard"][0][1]["callback_data"] == "sethealth_cancel"


# ================================================================
#  build_skip_keyboard
# ================================================================

class TestBuildSkipKeyboard:
    def test_default_label(self):
        kb = build_skip_keyboard("skip_date")
        assert len(kb["inline_keyboard"]) == 1
        assert len(kb["inline_keyboard"][0]) == 1
        btn = kb["inline_keyboard"][0][0]
        assert "跳過" in btn["text"]
        assert btn["callback_data"] == "skip_date"

    def test_custom_label(self):
        kb = build_skip_keyboard("skip_action", label="⏭ 略過")
        btn = kb["inline_keyboard"][0][0]
        assert btn["text"] == "⏭ 略過"

    def test_callback_data_preserved(self):
        kb = build_skip_keyboard("fin_skip_date")
        assert kb["inline_keyboard"][0][0]["callback_data"] == "fin_skip_date"
