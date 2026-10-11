"""Durable, confirmed broadcast queue with restart-safe per-recipient progress."""
import asyncio
import logging
from datetime import datetime, timezone
from pymongo.errors import BulkWriteError
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError, RetryAfter, TelegramForbiddenError
from app.config import Settings
from app.services.permissions import is_owner_or_moderator

router = Router(name="broadcast")
log = logging.getLogger(__name__)

def now():
    return datetime.now(timezone.utc)

@router.message(Command("broadcast"))
async def broadcast(message: Message, settings: Settings, database):
    if not message.from_user or not await is_owner_or_moderator(database.db, message.from_user.id, settings):
        return
    if not message.reply_to_message:
        await message.answer("Reply to the message you want to broadcast, then send /broadcast.")
        return
    admin_id = message.from_user.id
    active = await database.db.broadcast_drafts.find_one({"admin_id": admin_id, "status": {"$in": ["queued", "running"]}})
    if active:
        await message.answer("Your previous broadcast is still queued or running.")
        return
    source = message.reply_to_message
    recipients = await database.db.users.count_documents({"banned": {"$ne": True}})
    await database.db.broadcast_drafts.update_one(
        {"admin_id": admin_id},
        {"$set": {"admin_id": admin_id, "chat_id": source.chat.id, "message_id": source.message_id,
                  "created_at": now(), "status": "draft"}},
        upsert=True,
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="CONFIRM", callback_data="broadcast:yes"),
        InlineKeyboardButton(text="CANCEL", callback_data="broadcast:no"),
    ], [InlineKeyboardButton(text="BACK", callback_data="broadcast:back")]])
    await message.answer(f"BROADCAST CONFIRMATION\nReview the message before sending it to users.\nRecipients: {recipients}", reply_markup=keyboard)

@router.callback_query(F.data.startswith("broadcast:"))
async def confirm(query: CallbackQuery, settings: Settings, database):
    if not query.from_user or not await is_owner_or_moderator(database.db, query.from_user.id, settings):
        await query.answer("Not authorized.", show_alert=True)
        return
    action = query.data.split(":", 1)[1]
    admin_id = query.from_user.id
    if action in ("no", "back"):
        await database.db.broadcast_drafts.delete_one({"admin_id": admin_id, "status": "draft"})
        await query.answer("Broadcast cancelled.")
        if query.message:
            await query.message.edit_text("Broadcast cancelled." if action == "no" else "Back. Draft cancelled.")
        return
    draft = await database.db.broadcast_drafts.find_one_and_update(
        {"admin_id": admin_id, "status": "draft"},
        {"$set": {"status": "queued", "queued_at": now(),
                  "report_chat_id": query.message.chat.id if query.message else admin_id,
                  "report_message_id": query.message.message_id if query.message else None}},
    )
    if not draft:
        await query.answer("No pending broadcast draft, or it has already been queued.", show_alert=True)
        return
    # A durable job is uniquely tied to the draft; duplicate callback clicks cannot create duplicate jobs.
    job = await database.db.broadcast_jobs.find_one_and_update(
        {"draft_id": draft["_id"]},
        {"$setOnInsert": {
            "draft_id": draft["_id"], "admin_id": admin_id, "source_chat_id": draft["chat_id"],
            "source_message_id": draft["message_id"], "report_chat_id": draft.get("report_chat_id", admin_id),
            "report_message_id": draft.get("report_message_id"), "status": "preparing",
            "created_at": now(), "recipients_loaded": False,
        }},
        upsert=True, return_document=True,
    )
    job_id = job["_id"]
    if not job.get("recipients_loaded"):
        ids = []
        async for user in database.db.users.find({"banned": {"$ne": True}}, {"user_id": 1}):
            ids.append({"job_id": job_id, "user_id": user["user_id"], "status": "pending"})
        if ids:
            try:
                await database.db.broadcast_recipients.insert_many(ids, ordered=False)
            except BulkWriteError:
                # Unique job/user index makes this safe to repeat after an interrupted setup.
                pass
        await database.db.broadcast_jobs.update_one(
            {"_id": job_id}, {"$set": {"recipients_loaded": True, "status": "pending", "recipient_count": len(ids)}}
        )
    await query.answer("Broadcast queued.")
    if query.message:
        await query.message.edit_text("Broadcast queued. You will receive the delivery report when it finishes.")

async def run_broadcast_worker(bot, db, poll_seconds: int = 2):
    """Resume queued broadcasts after restarts; a 'sending' recipient is not resent blindly."""
    # If the process stopped mid-request, outcome is ambiguous; count it as failed instead of risking a duplicate.
    await db.broadcast_recipients.update_many({"status": "sending"}, {"$set": {"status": "unknown", "error": "process restarted during send"}})
    while True:
        job = await db.broadcast_jobs.find_one_and_update(
            {"status": {"$in": ["pending", "processing"]}},
            {"$set": {"status": "processing", "worker_seen_at": now()}},
            sort=[("created_at", 1)],
        )
        if not job:
            await asyncio.sleep(poll_seconds)
            continue
        job_id = job["_id"]
        recipient = await db.broadcast_recipients.find_one_and_update(
            {"job_id": job_id, "status": "pending"},
            {"$set": {"status": "sending", "attempted_at": now()}},
            sort=[("user_id", 1)],
        )
        if not recipient:
            counts = {}
            for status in ("sent", "failed", "blocked", "unknown"):
                counts[status] = await db.broadcast_recipients.count_documents({"job_id": job_id, "status": status})
            total = sum(counts.values())
            report = (f"BROADCAST REPORT\nRecipients: {total}\nSent successfully: {counts['sent']}\n"
                      f"Failed: {counts['failed'] + counts['unknown']}\nBlocked/unreachable: {counts['blocked']}")
            try:
                if job.get("report_message_id"):
                    await bot.edit_message_text(report, chat_id=job["report_chat_id"], message_id=job["report_message_id"])
                else:
                    await bot.send_message(job["report_chat_id"], report)
            except TelegramAPIError:
                log.exception("Could not send broadcast report for job %s", job_id)
            await db.broadcast_jobs.update_one({"_id": job_id}, {"$set": {"status": "completed", "completed_at": now(), "counts": counts}})
            await db.broadcast_drafts.delete_one({"_id": job["draft_id"]})
            continue
        uid = recipient["user_id"]
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=job["source_chat_id"], message_id=job["source_message_id"])
            await db.broadcast_recipients.update_one({"_id": recipient["_id"]}, {"$set": {"status": "sent", "finished_at": now()}})
        except RetryAfter as exc:
            await db.broadcast_recipients.update_one({"_id": recipient["_id"]}, {"$set": {"status": "pending", "retry_after": float(exc.retry_after)}})
            await asyncio.sleep(float(exc.retry_after) + 0.5)
        except TelegramForbiddenError:
            await db.broadcast_recipients.update_one({"_id": recipient["_id"]}, {"$set": {"status": "blocked", "finished_at": now()}})
            await db.users.update_one({"user_id": uid}, {"$set": {"blocked": True, "last_delivery_error": "forbidden"}})
        except TelegramAPIError as exc:
            await db.broadcast_recipients.update_one({"_id": recipient["_id"]}, {"$set": {"status": "failed", "error": type(exc).__name__, "finished_at": now()}})
            await db.users.update_one({"user_id": uid}, {"$set": {"last_delivery_error": type(exc).__name__, "last_delivery_error_at": now()}})
        except Exception as exc:
            log.exception("Unexpected broadcast failure for user %s", uid)
            await db.broadcast_recipients.update_one({"_id": recipient["_id"]}, {"$set": {"status": "failed", "error": type(exc).__name__, "finished_at": now()}})
        await asyncio.sleep(0.05)
