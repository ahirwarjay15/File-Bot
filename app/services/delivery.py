"""Delivery services and durable expiry worker."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
log = logging.getLogger(__name__)

DEFAULT_NOTICE = "Your files will be automatically deleted after {auto_delete_time}."

def _now():
    return datetime.now(timezone.utc)

def _minutes(cfg):
    allowed = (2, 5, 15, 30, 60, 180, 360, 720, 1440)
    value = int((cfg or {}).get("minutes", 30))
    return value if value in allowed else 30

def _notice(cfg, minutes):
    value = (cfg or {}).get("notice") or DEFAULT_NOTICE
    label = (f"{minutes // 60} hours" if minutes % 60 == 0 and minutes >= 60
             else f"{minutes} minutes" if minutes < 60
             else f"{minutes // 60}h {minutes % 60}m")
    return value.replace("{auto_delete_time}", label)

async def _save_expiry_task(db, user_id, message_ids, deadline, deeplink):
    await db.tasks.insert_one({
        "kind": "delete_delivery", "user_id": user_id,
        "message_ids": list(message_ids), "deadline": deadline,
        "deeplink": deeplink, "status": "pending",
        "created_at": _now(), "messages_deleted": False,
        "after_delete_attempted": False,
    })

async def deliver_reference(bot: Bot, db, settings, *, user_id: int, file_doc: dict, deeplink: str):
    sent = await bot.copy_message(chat_id=user_id, from_chat_id=file_doc["source_chat_id"], message_id=file_doc["source_message_id"])
    auto = await db.settings.find_one({"key": "auto_delete", "enabled": True})
    if not auto:
        return sent
    minutes = _minutes(auto)
    deadline = _now() + timedelta(minutes=minutes)
    message_ids = [sent.message_id]
    try:
        alert = await bot.send_message(user_id, _notice(auto, minutes))
        message_ids.append(alert.message_id)
    except TelegramAPIError:
        log.exception("File delivered, but auto-delete notice could not be sent")
    await _save_expiry_task(db, user_id, message_ids, deadline, deeplink)
    return sent

async def deliver_batch(bot: Bot, db, *, user_id: int, batch: dict, deeplink: str):
    auto = await db.settings.find_one({"key": "auto_delete", "enabled": True})
    minutes = _minutes(auto) if auto else None
    deadline = None
    delivered = []
    failed = 0
    for item in batch.get("items", []):
        try:
            sent = await bot.copy_message(chat_id=user_id, from_chat_id=item["source_chat_id"], message_id=item["source_message_id"])
            delivered.append(sent.message_id)
            if auto and deadline is None:
                deadline = _now() + timedelta(minutes=minutes)
        except TelegramAPIError:
            failed += 1
            log.exception("Batch item delivery failed")
    if auto and deadline and delivered:
        message_ids = list(delivered)
        if deadline > _now():
            try:
                alert = await bot.send_message(user_id, _notice(auto, minutes))
                message_ids.append(alert.message_id)
            except TelegramAPIError:
                log.exception("Batch delivered, but auto-delete notice could not be sent")
        await _save_expiry_task(db, user_id, message_ids, deadline, deeplink)
    return len(delivered), failed

async def run_task_worker(bot: Bot, db, poll_seconds: int = 5):
    while True:
        now = _now()
        async for task in db.tasks.find({"status": "pending", "deadline": {"$lte": now}}).sort("deadline", 1).limit(50):
            claimed = await db.tasks.update_one({"_id": task["_id"], "status": "pending"}, {"$set": {"status": "processing", "claimed_at": _now()}})
            if not claimed.modified_count:
                continue
            try:
                if not task.get("messages_deleted", False):
                    for mid in task.get("message_ids", []):
                        try:
                            await bot.delete_message(task["user_id"], mid)
                        except TelegramAPIError:
                            log.info("Could not delete delivered message %s for user %s", mid, task["user_id"])
                    await db.tasks.update_one({"_id": task["_id"]}, {"$set": {"messages_deleted": True}})
                auto = await db.settings.find_one({"key": "auto_delete", "enabled": True})
                after = await db.settings.find_one({"key": "after_delete", "enabled": True}) if auto else None
                if after and not task.get("after_delete_attempted", False):
                    await db.tasks.update_one({"_id": task["_id"]}, {"$set": {"after_delete_attempted": True}})
                    text = after.get("text") or "Yᴏᴜʀ Vɪᴅᴇᴏ / Fɪʟᴇ Iꜱ Sᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ Dᴇʟᴇᴛᴇᴅ ✅"
                    link = task.get("deeplink")
                    markup = InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text=after.get("button_text") or "Gᴇᴛ ʏᴏᴜʀ ꜰɪʟᴇꜱ ᴀɢᴀɪɴ", url=link)
                    ]]) if link else None
                    try:
                        await bot.send_message(task["user_id"], text, reply_markup=markup)
                    except TelegramAPIError:
                        log.exception("After-delete replacement message could not be sent")
                await db.tasks.update_one({"_id": task["_id"]}, {"$set": {"status": "done", "finished_at": _now()}})
            except Exception:
                log.exception("Expiry task failed")
                await db.tasks.update_one({"_id": task["_id"]}, {"$set": {"status": "pending", "last_error_at": _now()}})
        await asyncio.sleep(poll_seconds)
