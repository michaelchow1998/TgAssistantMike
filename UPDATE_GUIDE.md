# Update Guide — AssistantMike

## Quick Reference

| What changed?                | What to run                               |
|------------------------------|-------------------------------------------|
| Lambda code only             | `sam build && sam deploy`                 |
| `template.yaml`              | `sam build && sam deploy`                 |
| `dependencies/requirements`  | Rebuild layer → `sam build && sam deploy` |
| Env vars / parameters        | `sam deploy` (if defined in template)     |
| Everything                   | Full deploy checklist (see below)         |

---

## Scenario 1: Code Only Change

> Changed files in `webhook_handler/`, `reminder_handler/`, or `shared/`

```bash
sam build
sam deploy
# Review changeset → y
```

Verify:

```bash
sam logs --stack-name secretary-bot --name WebhookHandlerFunction --region ap-northeast-1 --tail
```

---

## Scenario 2: Dependencies Changed

> Added/removed/updated packages in `dependencies/requirements.txt`

```bash
# Step 1: Rebuild the layer
rm -rf dependencies/python
mkdir -p dependencies/python
pip install -r dependencies/requirements.txt -t dependencies/python/ \
    --platform manylinux2014_aarch64 \
    --implementation cp \
    --python-version 3.13 \
    --only-binary=:all: \
    --upgrade

# Step 2: Build & deploy
sam build
sam deploy
```

---

## Scenario 3: Infrastructure Changed

> Modified `template.yaml` (new Lambda, DynamoDB table, API route, IAM policy, etc.)

```bash
# Step 1: Validate first
sam validate --lint

# Step 2: Build & deploy
sam build
sam deploy
# ⚠️ READ THE CHANGESET CAREFULLY before confirming
```

### Dangerous Changes (require extra care)

| Change | Risk |
|---|---|
| Delete/rename DynamoDB table | DATA LOSS — migrate data first |
| Change DynamoDB key schema | REQUIRES REPLACEMENT — new table |
| Change API Gateway path | Update Telegram webhook URL |
| Change Lambda function name | Other references may break |
| Change stack name | Creates entirely new stack |

---

## Scenario 4: Environment Variables Changed

> New secret, changed token, etc.

If defined in `template.yaml`:

```bash
sam build
sam deploy
```

If using parameter overrides:

```bash
sam deploy --parameter-overrides \
    "AlertEmail=new@email.com"
```

If only in `.env` (local dev): no deploy needed, just update `.env`.

---

## Scenario 5: Hotfix (Fastest Deploy)

> Emergency fix; no dependency or template changes

```bash
# Direct Lambda update (bypasses SAM)
aws lambda update-function-code \
    --function-name bot-webhook-handler \
    --zip-file fileb://webhook_handler.zip \
    --region ap-northeast-1
```

⚠️ Not recommended — SAM state will be out of sync. Always follow up with `sam build && sam deploy`.

---

## Full Deploy Checklist

```
1. ✅ Save all files
2. ✅ Run tests              → pytest tests/ -v
3. ✅ Validate template      → sam validate --lint
4. ✅ Rebuild deps (if any)  → pip install ... -t dependencies/python/
5. ✅ Build                  → sam build
6. ✅ Deploy                 → sam deploy
7. ✅ Read changeset         → Confirm y
8. ✅ Verify logs            → sam logs --stack-name secretary-bot --tail
9. ✅ Test live              → Send a Telegram command
10. ✅ Commit to git         → git add . && git commit -m "description"
```

---

## Post-Deploy Verification

```bash
# Check stack status
aws cloudformation describe-stacks \
    --stack-name secretary-bot \
    --region ap-northeast-1 \
    --query "Stacks[0].StackStatus"

# Check Lambda errors (last 10 min)
sam logs --stack-name secretary-bot \
    --name WebhookHandlerFunction \
    --region ap-northeast-1 \
    --start-time "10min ago"

sam logs --stack-name secretary-bot \
    --name ReminderHandlerFunction \
    --region ap-northeast-1 \
    --start-time "10min ago"

# Check API Gateway is responding (expected: 403 = Lambda is alive, secret path missing)
curl -X POST "https://tddc8n7h54.execute-api.ap-northeast-1.amazonaws.com/prod/webhook/" \
    -H "Content-Type: application/json" \
    -d "{}" \
    -w "\n%{http_code}\n"
```

---

## Rollback

```bash
# Roll back to previous CloudFormation deployment
aws cloudformation rollback-stack \
    --stack-name secretary-bot \
    --region ap-northeast-1

# Or redeploy from last known good commit
git log --oneline -5          # find the good commit
git checkout <commit-hash>
sam build && sam deploy
git checkout main             # return to main after
```

---

## Git Workflow

```bash
# After every successful deploy
git add .
git status                    # verify no secrets staged
git commit -m "feat: description of what changed"
git push origin main
```

### Commit Message Convention

| Prefix | Use for |
|---|---|
| `feat:` | New feature |
| `fix:` | Bug fix |
| `infra:` | `template.yaml` / infrastructure change |
| `deps:` | Dependency update |
| `docs:` | Documentation only |
| `refactor:` | Code change that doesn't fix a bug or add a feature |
| `test:` | Adding tests |
