import json
import logging

logger = logging.getLogger()
logger.setLevel("INFO")


def lambda_handler(event, context):
    logger.info("Reminder triggered: %s", json.dumps(event))
    return {"ok": True}