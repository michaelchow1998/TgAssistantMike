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

See **[onboard.md](onboard.md)** for the full step-by-step deployment guide.

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
├── dependencies/           # Lambda layer: third-party packages
├── scripts/                # Utility scripts (setwebhook, etc.)
├── template.yaml           # AWS SAM template
├── onboard.md              # Deployment guide
└── spec.md                 # Full product specification (Chinese)
```

---

## Development

```bash
# Run tests
pytest tests/ -v

# Tail live Lambda logs
sam logs --stack-name secretary-bot --name WebhookHandlerFunction --region ap-northeast-1 --tail
sam logs --stack-name secretary-bot --name ReminderHandlerFunction --region ap-northeast-1 --tail

# Redeploy after code changes
sam build && sam deploy
```

> **Note:** `dependencies/python/` is a build artifact — it is gitignored. Rebuild it before deploying if `dependencies/requirements.txt` changes.

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
