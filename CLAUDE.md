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
5. **Always update `help_module.py` when adding a new handler** — `webhook_handler/handlers/help_module.py` contains `_HELP_MODULES`, `_HELP_MENU_ROWS`, and `_HELP_ALIASES`; new commands must be added to all three or they won't appear in `/help`
6. **Mock at the handler's import level, not the source module** — patch `"handlers.health.get_item"`, not `"bot_db.get_item"`; functions are resolved at the call site's namespace

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
5. **Update `help_module.py`** — add entry to `_HELP_MODULES`, button to `_HELP_MENU_ROWS`, and alias(es) to `_HELP_ALIASES`
6. Add entity/module constants to `bot_constants.py` (`ENTITY_*`, `CONV_MODULE_*`, display names)
7. Write unit tests in `tests/` — follow the mock-at-handler-namespace pattern

## Testing

```bash
# Install dev dependencies (one-time)
pip install -r requirements-dev.txt

# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/test_health_handler.py -v
```

### Test Structure

| File | What it covers |
|---|---|
| `tests/conftest.py` | Adds `shared/python`, `webhook_handler`, `reminder_handler` to `sys.path` |
| `tests/test_bot_utils.py` | All date/time parsing, formatting, repeat-occurrence helpers |
| `tests/test_bot_telegram.py` | Inline keyboard and confirm/skip keyboard builders |
| `tests/test_bot_constants.py` | Contract tests — verifies constant values haven't silently changed |
| `tests/test_health_handler.py` | Health handler: parsers, conversation steps, callbacks, summary rendering |
| `tests/test_subscription_handler.py` | `_calc_next_billing` across monthly/quarterly/yearly cycles |
| `tests/test_notifier.py` | Reminder notifier formatting helpers and `_split_message` |
| `tests/test_router.py` | Router: owner auth, unknown commands, conversation dispatch, callbacks |

### Mocking Convention

Shared modules (`bot_db`, `bot_config`, `bot_telegram`) use lazy initialisation — they only call boto3/SSM on first function call, so **importing them never fails** even without AWS credentials.

Patch dependencies at the **handler's namespace**, not the source:

```python
# Correct — patches the name as the handler resolves it
patch("handlers.health.get_item", return_value=None)

# Wrong — patches the source, handler already holds its own reference
patch("bot_db.get_item", return_value=None)
```
