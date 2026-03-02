# reminders/__init__.py
# ============================================================
# Package exports — clean import from lambda_function.py:
#
#   from reminders import ReminderService
# ============================================================

from .reminder_service import ReminderService

__all__ = ["ReminderService"]