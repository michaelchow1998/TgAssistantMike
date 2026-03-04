#!/usr/bin/env bash
# scripts/deploy.sh — build and deploy the secretary-bot SAM stack
#
# On Windows (Git Bash / WSL), SAM CLI must be invoked via cmd.exe.
# Usage: bash scripts/deploy.sh
set -euo pipefail

STACK_NAME="secretary-bot"
REGION="ap-northeast-1"

# On Windows the SAM CLI wrapper is a .cmd file that only runs under cmd.exe
SAM="cmd.exe /c sam"

echo "==> sam build"
$SAM build

echo "==> sam deploy"
$SAM deploy \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset

echo "==> Done"
