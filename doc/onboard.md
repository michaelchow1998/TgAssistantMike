# Onboarding Guide — Deploy Your Own Secretary Bot

This bot is **single-user** (owner-only). Each person who wants to use it must deploy their own instance on their own AWS account.

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | 3.13 | https://python.org |
| AWS CLI | v2 | https://aws.amazon.com/cli/ |
| AWS SAM CLI | latest | https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html |
| AWS Account | — | https://aws.amazon.com |
| Telegram account | — | https://telegram.org |

---

## Step 1 — Create a Telegram Bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts (choose a name and username)
3. BotFather replies with your **bot token** — save it:
   ```
   7654321098:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

---

## Step 2 — Get Your Telegram User ID

1. Search for **@userinfobot** on Telegram
2. Send it any message
3. It replies with your **user ID** — save it:
   ```
   123456789
   ```

---

## Step 3 — Set Up AWS

### Configure AWS CLI

```bash
aws configure
# Enter: Access Key ID, Secret Access Key, region (ap-northeast-1), output (json)
```

### Store secrets in SSM Parameter Store

```bash
# Bot token (SecureString)
aws ssm put-parameter \
    --name "/bot/token" \
    --value "YOUR_BOT_TOKEN" \
    --type SecureString \
    --region ap-northeast-1

# Your Telegram user ID (String)
aws ssm put-parameter \
    --name "/bot/owner_id" \
    --value "YOUR_USER_ID" \
    --type String \
    --region ap-northeast-1

# Webhook secret — any random string (SecureString)
aws ssm put-parameter \
    --name "/bot/webhook_secret" \
    --value "$(openssl rand -hex 32)" \
    --type SecureString \
    --region ap-northeast-1

# Webhook path — another random string, becomes part of the URL (SecureString)
aws ssm put-parameter \
    --name "/bot/webhook_path" \
    --value "$(openssl rand -hex 16)" \
    --type SecureString \
    --region ap-northeast-1
```

> **Note the values you set for `webhook_secret` and `webhook_path`** — you'll need them in Step 6.

---

## Step 4 — Clone & Configure the Project

```bash
git clone <repo-url>
cd AssistantMike
```

Copy the example env file (used only for the webhook registration script):

```bash
cp eg.env .env
```

Edit `.env` and fill in the values:

```
TELEGRAM_BOT_TOKEN=7654321098:AAHxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WEBHOOK_SECRET=<the value you set for /bot/webhook_secret>
WEBHOOK_PATH=<the value you set for /bot/webhook_path>
OWNER_ID=123456789
WEBHOOK_BASE_URL=https://<id>.execute-api.<region>.amazonaws.com/prod/webhook/
```

> You will get the `WEBHOOK_BASE_URL` value from the `sam deploy` output in Step 5.

---

## Step 5 — Build & Deploy

### Build the dependencies layer

```bash
pip install -r dependencies/requirements.txt -t dependencies/python/ \
    --platform manylinux2014_aarch64 \
    --implementation cp \
    --python-version 3.13 \
    --only-binary=:all: \
    --upgrade
```

### Set up SAM deploy config

```bash
cp samconfig.toml.example samconfig.toml
```

Edit `samconfig.toml` and set your preferred region and (optionally) an alert email.

### Deploy to AWS

```bash
sam build
sam deploy
```

`sam deploy` will show a changeset — review it and type `y` to confirm.

When it finishes, note the `WebhookUrl` output value:

```
WebhookUrl = https://<id>.execute-api.ap-northeast-1.amazonaws.com/prod/webhook/
```

---

## Step 6 — Register the Telegram Webhook

Install the local script dependency:

```bash
pip install requests python-dotenv
```

Run the registration script:

```bash
python scripts/setwebhook.py
```

Expected response:

```json
{"ok": true, "result": true, "description": "Webhook was set"}
```

---

## Step 7 — Test It

Open Telegram, find your bot, and send:

```
/start
```

You should receive a welcome message. If not, check the logs:

```bash
sam logs --stack-name secretary-bot --name WebhookHandlerFunction --region ap-northeast-1 --tail
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Bot doesn't respond | Webhook not registered | Re-run `scripts/setwebhook.py` |
| `403 Forbidden` from API | Wrong secret path | Check `WEBHOOK_PATH` in `.env` matches SSM `/bot/webhook_path` |
| `⛔ 你無權使用此 Bot` | Wrong owner ID | Check SSM `/bot/owner_id` matches your actual Telegram user ID |
| Lambda errors in logs | Missing SSM parameter | Verify all 4 SSM parameters exist with correct names |
| `sam deploy` fails | Stack name conflict | Each deployer must use their own AWS account |

---

## Cost Estimate

At personal-use volume (a few hundred messages/day), monthly AWS cost is effectively **$0** — all services stay within the free tier or close to it:

- Lambda: 1M free requests/month
- API Gateway: 1M free requests/month (first 12 months)
- DynamoDB: 25 GB free storage, 25 WCU/RCU free
- EventBridge Scheduler: 14M invocations free/month