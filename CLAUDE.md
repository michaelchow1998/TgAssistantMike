# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Secretary Bot** — a personal Telegram bot deployed on AWS Serverless (Lambda + API Gateway + DynamoDB + EventBridge Scheduler). All bot messages are in Traditional Chinese. Python 3.13, arm64.

## Architecture

```
Telegram → API Gateway → webhook_handler (Lambda)
                              ↓
                         DynamoDB (BotMainTable, BotConversationTable)
                              ↑
EventBridge (cron) → reminder_handler (Lambda) → Telegram API (httpx)
```

### AWS Resources

| Resource             | Name/Value                                                                     |
|----------------------|--------------------------------------------------------------------------------|
| Stack Name           | `secretary-bot`                                                                |
| Region               | `ap-northeast-1`                                                               |
| API Gateway          | `https://<id>.execute-api.ap-northeast-1.amazonaws.com/prod/webhook/`         |
| Webhook Lambda       | `bot-webhook-handler`                                                          |
| Reminder Lambda      | `bot-reminder-handler`                                                         |
| Main Table           | `BotMainTable`                                                                 |
| Conversation Table   | `BotConversationTable`                                                         |
| Alert SNS Topic      | `bot-alerts`                                                                   |
| Dependencies Layer   | httpx, pytz, python-ulid                                                       |

## Key Commands

```bash
# Build & Deploy
sam build
sam deploy

# View logs (live tail)
sam logs --stack-name secretary-bot --name WebhookHandlerFunction --region ap-northeast-1 --tail
sam logs --stack-name secretary-bot --name ReminderHandlerFunction --region ap-northeast-1 --tail

# List stack outputs
sam list stack-outputs --stack-name secretary-bot --region ap-northeast-1

# Rebuild dependencies layer (after requirements change)
pip install -r dependencies/requirements.txt -t dependencies/python/ \
    --platform manylinux2014_aarch64 \
    --implementation cp \
    --python-version 3.13 \
    --only-binary=:all: \
    --upgrade

# Run tests
pytest tests/ -v

# Register Telegram webhook (requires .env)
python scripts/setwebhook.py
```

## Common Mistakes

1. **Stack name is `secretary-bot`, not `AssistantMike`** — always pass `--region ap-northeast-1`
2. **Dependencies layer is a build artifact** — `dependencies/python/` is gitignored; rebuild before `sam deploy` if packages changed
3. **Webhook requires a secret path segment** — API Gateway URL needs `/webhook/<secret_path>`, without it → 403
4. **SSM parameters must exist before deploy** — `/bot/token`, `/bot/owner_id`, `/bot/webhook_secret`, `/bot/webhook_path`

## Code Architecture

### Two Lambda Functions

| Function | CodeUri | Trigger |
|---|---|---|
| `WebhookHandlerFunction` | `webhook_handler/` | HTTP POST `/webhook/{proxy+}` via API Gateway |
| `ReminderHandlerFunction` | `reminder_handler/` | EventBridge Scheduler (4× daily) |

### Two Lambda Layers

- **DependenciesLayer** (`dependencies/`) — third-party: httpx, pytz, python-ulid
- **SharedLayer** (`shared/`) — internal shared modules

### Shared Modules (`shared/python/`)

All modules use module-level caching (survive warm Lambda invocations):

| Module | Purpose |
|---|---|
| `bot_config.py` | SSM Parameter Store + env var config; caches all SSM reads |
| `bot_db.py` | DynamoDB CRUD for main table and conversation table; GSI query helpers |
| `bot_telegram.py` | Telegram Bot API via httpx sync client; keyboard builder helpers |
| `bot_utils.py` | Date/time parsing (Chinese shortcuts supported), currency formatting, ID generation |
| `bot_constants.py` | All entity type strings, status enums, category maps, conversation module names |

### DynamoDB Tables

**BotMainTable** — single-table design, PAY_PER_REQUEST, PITR enabled:
- PK/SK: `ENTITY_TYPE#ULID` pattern
- GSI1 (`GSI_Type_Date`): query by entity type + date range
- GSI2 (`GSI_Category`): query by category
- GSI3 (`GSI_ShortID`): look up by human-facing short integer ID (zero-padded 5 digits)

**BotConversationTable** — stores multi-step conversation state per user:
- Key: `PK=USER#{user_id}`, `SK=CONV#active`
- TTL on `expire_at` (30-minute timeout)
- Deleted on `/cancel` or conversation completion

### Environment Variables (set by SAM template)

| Variable | Default |
|---|---|
| `MAIN_TABLE_NAME` | `BotMainTable` |
| `CONV_TABLE_NAME` | `BotConversationTable` |
| `TIMEZONE` | `Asia/Hong_Kong` |
| `LOG_LEVEL` | `INFO` |

### SSM Parameters Required

| Parameter | Description |
|---|---|
| `/bot/token` | Telegram bot token (SecureString) |
| `/bot/owner_id` | Bot owner Telegram user ID (String) |
| `/bot/webhook_secret` | Webhook secret token (SecureString) |
| `/bot/webhook_path` | Secret path segment for webhook URL (SecureString) |

### Request Flow (WebhookHandler)

1. Verify `x-telegram-bot-api-secret-token` header against SSM `/bot/webhook_secret`
2. Parse Telegram Update JSON
3. `handlers/router.py` dispatches: callback_query → callback handler; message → owner check → command or conversation step
4. Always return HTTP 200 to prevent Telegram retries

### Conversation Pattern

Commands in `CONVERSATION_STARTER_COMMANDS` (e.g. `/add_schedule`, `/add_todo`) initiate multi-step dialogs:
- State stored in BotConversationTable: `{module, step, data, expire_at}`
- Each handler module exposes `handle_step(user_id, chat_id, text, step, data)` and `handle_callback(...)`
- `/cancel` always clears active conversation

### Reminder Flow (ReminderHandler)

EventBridge passes `{"reminder_type": "<type>"}`. Types: `morning` (08:00 HKT), `subscription_alert` (10:00), `payment_alert` (12:00), `evening` (21:00).

## Adding a New Command Handler

1. Create or extend a file in `webhook_handler/handlers/`
2. Expose `handle_<cmd>(user_id, chat_id, ...)` — plus `handle_step` / `handle_callback` if multi-step
3. Add the route in `webhook_handler/handlers/router.py` (`_route_command`)
4. If it starts a conversation, add the command to `CONVERSATION_STARTER_COMMANDS` in `shared/python/bot_constants.py` and add dispatch entries in `router.py`
