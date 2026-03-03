# tests/test_bot_constants.py
# ============================================================
# Contract tests for bot_constants.py.
# Verifies that key constant values, dict keys, and set members
# have not been accidentally changed or removed.
# ============================================================

import bot_constants as C


# ================================================================
#  Entity type string values
# ================================================================

class TestEntityTypes:
    def test_sch(self):
        assert C.ENTITY_SCH == "SCH"

    def test_todo(self):
        assert C.ENTITY_TODO == "TODO"

    def test_work(self):
        assert C.ENTITY_WORK == "WORK"

    def test_fin(self):
        assert C.ENTITY_FIN == "FIN"

    def test_sub(self):
        assert C.ENTITY_SUB == "SUB"

    def test_health(self):
        assert C.ENTITY_HEALTH == "HEALTH"

    def test_counter(self):
        assert C.ENTITY_COUNTER == "COUNTER"


# ================================================================
#  Conversation module string values
# ================================================================

class TestConvModules:
    def test_health(self):
        assert C.CONV_MODULE_HEALTH == "health"

    def test_set_health(self):
        assert C.CONV_MODULE_SET_HEALTH == "set_health"

    def test_schedule(self):
        assert C.CONV_MODULE_SCHEDULE == "schedule"

    def test_finance(self):
        assert C.CONV_MODULE_FINANCE == "finance"


# ================================================================
#  Health meal display dict
# ================================================================

class TestHealthMealDisplay:
    EXPECTED_KEYS = {"breakfast", "lunch", "dinner", "other"}

    def test_has_all_meal_types(self):
        assert set(C.HEALTH_MEAL_DISPLAY.keys()) == self.EXPECTED_KEYS

    def test_breakfast_has_label_and_emoji(self):
        b = C.HEALTH_MEAL_DISPLAY["breakfast"]
        assert "label" in b and "emoji" in b

    def test_lunch_label(self):
        assert C.HEALTH_MEAL_DISPLAY["lunch"]["label"] == "午餐"

    def test_dinner_label(self):
        assert C.HEALTH_MEAL_DISPLAY["dinner"]["label"] == "晚餐"

    def test_other_label(self):
        assert C.HEALTH_MEAL_DISPLAY["other"]["label"] == "其他"

    def test_meal_constants_match_display_keys(self):
        assert C.HEALTH_MEAL_BREAKFAST in C.HEALTH_MEAL_DISPLAY
        assert C.HEALTH_MEAL_LUNCH in C.HEALTH_MEAL_DISPLAY
        assert C.HEALTH_MEAL_DINNER in C.HEALTH_MEAL_DISPLAY
        assert C.HEALTH_MEAL_OTHER in C.HEALTH_MEAL_DISPLAY


# ================================================================
#  CONVERSATION_STARTER_COMMANDS
# ================================================================

class TestConversationStarterCommands:
    def test_set_health_in_set(self):
        assert "/set_health" in C.CONVERSATION_STARTER_COMMANDS

    def test_add_meal_in_set(self):
        assert "/add_meal" in C.CONVERSATION_STARTER_COMMANDS

    def test_add_schedule_in_set(self):
        assert "/add_schedule" in C.CONVERSATION_STARTER_COMMANDS

    def test_edit_fin_in_set(self):
        assert "/edit_fin" in C.CONVERSATION_STARTER_COMMANDS

    def test_all_entries_start_with_slash(self):
        for cmd in C.CONVERSATION_STARTER_COMMANDS:
            assert cmd.startswith("/"), f"{cmd!r} does not start with '/'"


# ================================================================
#  MODULE_DISPLAY_NAMES completeness
# ================================================================

class TestModuleDisplayNames:
    def test_health_in_display_names(self):
        assert C.CONV_MODULE_HEALTH in C.MODULE_DISPLAY_NAMES

    def test_set_health_in_display_names(self):
        assert C.CONV_MODULE_SET_HEALTH in C.MODULE_DISPLAY_NAMES

    def test_all_display_names_are_non_empty_strings(self):
        for module, name in C.MODULE_DISPLAY_NAMES.items():
            assert isinstance(name, str) and name, f"Empty name for {module!r}"

    def test_all_conv_modules_have_display_name(self):
        modules = [
            C.CONV_MODULE_SCHEDULE, C.CONV_MODULE_TODO, C.CONV_MODULE_WORK,
            C.CONV_MODULE_FINANCE, C.CONV_MODULE_SUBSCRIPTION,
            C.CONV_MODULE_RESUME_SUB, C.CONV_MODULE_EDIT_SUB,
            C.CONV_MODULE_EDIT_FIN, C.CONV_MODULE_HEALTH, C.CONV_MODULE_SET_HEALTH,
        ]
        for mod in modules:
            assert mod in C.MODULE_DISPLAY_NAMES, f"Missing display name for {mod!r}"


# ================================================================
#  Misc constants
# ================================================================

class TestMiscConstants:
    def test_conv_ttl_is_30_minutes(self):
        assert C.CONV_TTL_SECONDS == 1800

    def test_no_due_date_sentinel(self):
        assert C.NO_DUE_DATE_SENTINEL == "9999-12-31"

    def test_short_id_pad_width(self):
        assert C.SHORT_ID_PAD_WIDTH == 5
