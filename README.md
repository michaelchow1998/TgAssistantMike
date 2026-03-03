# Secretary Bot

A personal Telegram bot for scheduling, task tracking, finance, and daily reminders — deployed serverless on AWS.

> **Single-user**: each person deploys their own instance on their own AWS account.

---

## Features

| Module | Commands |
|---|---|
| **Schedule** | `/add_schedule` `/today` `/week` `/cancel_schedule` |
| **Todo** | `/add_todo` `/todos` `/done` `/delete_todo` |
| **Work** | `/add_work` `/works` `/update_progress` `/complete_work` |
| **Finance** | `/add_payment` `/add_income` `/add_expense` `/finances` `/mark_paid` |
| **Subscriptions** | `/add_sub` `/subs` `/cancel_sub` `/resume_sub` `/edit_sub` |
| **Health** | `/set_health` `/add_meal` `/health` |
| **Summary** | `/summary` `/help` |

**Daily reminders** (automated, no command needed):

| Time (HKT) | Reminder |
|---|---|
| 08:00 | Morning briefing — today's schedules, todos, work deadlines |
| 10:00 | Subscription billing alert (only if due today) |
| 12:00 | Payment due alert (only if due today) |
| 21:00 | Evening preview — tomorrow's agenda |

---

## Architecture

```
Telegram → API Gateway → WebhookHandlerFunction (Lambda)
                               ↓
                   BotMainTable / BotConversationTable (DynamoDB)
                               ↑
EventBridge Scheduler → ReminderHandlerFunction (Lambda) → Telegram
```

**Stack**: Python 3.13 · AWS Lambda (arm64) · API Gateway · DynamoDB · EventBridge Scheduler · SSM Parameter Store

All bot messages are in Traditional Chinese.

---

## Quick Start

See **[onboard.md](doc/onboard.md)** for the full step-by-step deployment guide.

**Summary:**

1. Create a Telegram bot via [@BotFather](https://t.me/BotFather) and note the token
2. Get your Telegram user ID via [@userinfobot](https://t.me/userinfobot)
3. Store secrets in AWS SSM Parameter Store (`/bot/token`, `/bot/owner_id`, `/bot/webhook_secret`, `/bot/webhook_path`)
4. Build the dependencies layer and deploy:
   ```bash
   pip install -r dependencies/requirements.txt -t dependencies/python/ \
       --platform manylinux2014_aarch64 --implementation cp \
       --python-version 3.13 --only-binary=:all: --upgrade

   sam build && sam deploy
   ```
5. Register the webhook:
   ```bash
   cp eg.env .env   # fill in your values
   python scripts/setwebhook.py
   ```

---

## Project Structure

```
.
├── webhook_handler/        # Lambda: handles Telegram webhook messages
│   └── handlers/           # One file per feature module
├── reminder_handler/       # Lambda: scheduled daily reminders
│   └── reminders/
├── shared/python/          # Lambda layer: shared modules
│   ├── bot_config.py       # SSM + env var config (cached)
│   ├── bot_db.py           # DynamoDB CRUD + GSI helpers
│   ├── bot_telegram.py     # Telegram API client (httpx)
│   ├── bot_utils.py        # Date parsing, formatting, IDs
│   └── bot_constants.py    # All enums, categories, constants
├── tests/                  # Unit tests (pytest, no AWS required)
│   ├── conftest.py         # sys.path setup for Lambda layers
│   └── test_*.py
├── dependencies/           # Lambda layer: third-party packages
├── scripts/                # Utility scripts (setwebhook, etc.)
├── requirements-dev.txt    # Dev dependencies (pytest)
├── template.yaml           # AWS SAM template
├── onboard.md              # Deployment guide
└── spec.md                 # Full product specification (Chinese)
```

---

## Development

```bash
# Run tests
pip install -r requirements-dev.txt   # one-time: installs pytest
pytest tests/ -v

# Tail live Lambda logs
sam logs --stack-name secretary-bot --name WebhookHandlerFunction --region ap-northeast-1 --tail
sam logs --stack-name secretary-bot --name ReminderHandlerFunction --region ap-northeast-1 --tail

# Redeploy after code changes
sam build && sam deploy
```

> **Note:** `dependencies/python/` is a build artifact — it is gitignored. Rebuild it before deploying if `dependencies/requirements.txt` changes.

### Tests

Tests live in `tests/` and use `pytest` with `unittest.mock` — no AWS credentials or live services required. `tests/conftest.py` injects the Lambda layer paths (`shared/python`, `webhook_handler`, `reminder_handler`) into `sys.path` so imports resolve correctly.

| File | Coverage |
|---|---|
| `test_bot_utils.py` | Date/time parsing (Chinese shortcuts), formatting, repeat-occurrence helpers |
| `test_bot_telegram.py` | Inline keyboard and confirm/skip keyboard builders |
| `test_bot_constants.py` | Contract tests — entity types, conv modules, meal display, command sets |
| `test_health_handler.py` | Health module: parsers, conversation flows, today summary, monthly report |
| `test_subscription_handler.py` | `_calc_next_billing` — monthly/quarterly/yearly, day-clamping edge cases |
| `test_notifier.py` | Reminder formatting helpers and `_split_message` chunking |
| `test_router.py` | Routing: owner auth, unknown commands, cancel, conversation dispatch |

---

## AWS Resources

| Resource | Name |
|---|---|
| Stack | `secretary-bot` |
| Region | `ap-northeast-1` |
| Main DynamoDB table | `BotMainTable` |
| Conversation table | `BotConversationTable` |

---

## Cost

At personal-use volume, monthly AWS cost is effectively **$0** — all services stay within the free tier:

- Lambda: 1M free requests/month
- API Gateway: 1M free requests/month (first 12 months)
- DynamoDB: 25 GB storage + 25 WCU/RCU free
- EventBridge Scheduler: 14M invocations free/month
