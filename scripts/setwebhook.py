# scripts/setwebhook.py
import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SECRET = os.getenv("WEBHOOK_SECRET")
PATH = os.getenv("WEBHOOK_PATH")
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE_URL")  # e.g. https://<id>.execute-api.<region>.amazonaws.com/prod/webhook/

if not WEBHOOK_BASE:
    raise ValueError("WEBHOOK_BASE_URL is not set in .env — copy it from `sam list stack-outputs`")

WEBHOOK_URL = f"{WEBHOOK_BASE.rstrip('/')}/{PATH}"

resp = requests.post(
    f"https://api.telegram.org/bot{TOKEN}/setWebhook",
    json={
        "url": WEBHOOK_URL,
        "secret_token": SECRET,
        "allowed_updates": ["message", "callback_query"],
    },
)
print(resp.json())