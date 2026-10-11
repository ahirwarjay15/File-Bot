import asyncio
import logging
from datetime import datetime, timedelta, timezone
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from app.config import Settings

logger = logging.getLogger(__name__)

async def deliver_reference(bot: Bot, db, settings: Settings, *, user_id: int, file_doc: dict, deeplink: str):
    sent = await bot.copy_message(chat_id=user_id, from_chat_id=file_doc["source_chat_id"], message_id=file_doc["source_message_id"])
    auto = await db.settings.find_one({"key": "auto_delete"})
    if auto and auto.get("enabled"):
        minutes = max(1, min(int(auto.get("minutes", 30)), 10080))
        alert = await bot.send_message(user_id, auto.get("notice") or f"⏳ This file will be deleted in {minutes} minutes.")
        deadline = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        await db.tasks.insert_one({"kind":"delete_delivery", "user_id":user_id, "message_ids":[sent.message_id, alert.message_id], "deadline":deadline, "deeplink":deeplink, "status":"pending", "created_at":datetime.now(timezone.utc)})
    return sent

async def run_task_worker(bot: Bot, db, poll_seconds: int = 5):
    while True:
        now = datetime.now(timezone.utc)
        tasks = db.tasks.find({"status":"pending", "deadline":{"$lte":now}}).limit(50)
        async for task in tasks:
            claimed = await db.tasks.update_one({"_id":task["_id"], "status":"pending"}, {"$set":{"status":"processing"}})
            if not claimed.modified_count:
                continue
            try:
                for mid in task.get("message_ids", []):
                    try:
                        await bot.delete_message(task["user_id"], mid)
                    except TelegramAPIError:
                        logger.info("Could not delete message %s for user %s", mid, task["user_id"])
                after = await db.settings.find_one({"key":"after_delete"})
                if after and after.get("enabled"):
                    await bot.send_message(task["user_id"], after.get("text") or "The file expired.", reply_markup=None)
                await db.tasks.update_one({"_id":task["_id"]}, {"$set":{"status":"done", "finished_at":datetime.now(timezone.utc)}})
            except Exception:
                logger.exception("Delete task failed")
                await db.tasks.update_one({"_id":task["_id"]}, {"$set":{"status":"pending"}})
        await asyncio.sleep(poll_seconds)
