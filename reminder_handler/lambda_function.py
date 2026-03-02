# reminder_handler/lambda_function.py
# ============================================================
# 排程提醒 Lambda — 入口
#
# EventBridge Scheduler 帶入：
#   {"reminder_type": "morning"}
#   {"reminder_type": "subscription_alert"}
#   {"reminder_type": "payment_alert"}
#   {"reminder_type": "evening"}
# ============================================================

import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))


def lambda_handler(event, context):
    reminder_type = event.get("reminder_type", "morning")

    logger.info(json.dumps({
        "action": "reminder_triggered",
        "reminder_type": reminder_type,
    }))

    from reminders import ReminderService

    svc = ReminderService()

    dispatch = {
        "morning":            svc.morning_briefing,
        "subscription_alert": svc.subscription_alert,
        "payment_alert":      svc.payment_alert,
        "evening":            svc.evening_preview,
    }

    handler = dispatch.get(reminder_type)
    if handler:
        sent = handler()
        logger.info(json.dumps({
            "action": "reminder_completed",
            "reminder_type": reminder_type,
            "sent": sent,
        }))
    else:
        logger.warning(f"Unknown reminder_type: {reminder_type}")

    return {"statusCode": 200}