# tests/conftest.py
# ============================================================
# Adds shared layer, webhook handler and reminder handler
# directories to sys.path so tests can import project modules
# without needing a real Lambda environment.
# ============================================================

import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# shared/python  →  bot_config, bot_db, bot_utils, bot_telegram, bot_constants
sys.path.insert(0, os.path.join(PROJECT_ROOT, "shared", "python"))

# webhook_handler  →  `from handlers.X import ...`
sys.path.insert(0, os.path.join(PROJECT_ROOT, "webhook_handler"))

# reminder_handler  →  `from reminders.X import ...`
sys.path.insert(0, os.path.join(PROJECT_ROOT, "reminder_handler"))
