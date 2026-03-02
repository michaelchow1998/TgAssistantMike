# scripts/setwebhook.py
import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SECRET = os.getenv("WEBHOOK_SECRET")
PATH = os.getenv("WEBHOOK_PATH")

WEBHOOK_BASE = "https://tddc8n7h54.execute-api.ap-northeast-1.amazonaws.com/prod/webhook/"
WEBHOOK_URL = f"{WEBHOOK_BASE}{PATH}"

resp = requests.post(
    f"https://api.telegram.org/bot{TOKEN}/setWebhook",
    json={
        "url": WEBHOOK_URL,
        "secret_token": SECRET,
        "allowed_updates": ["message", "callback_query"],
    },
)
print(resp.json())