"""Delivery services, durable batch progress, and expiry worker."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

log = logging.getLogger(__name__)
DEFAULT_NOTICE = "Your files will be automatically deleted after {auto_delete_time}."


def _now():
    return datetime.now(timezone.utc)


async def claim_delivery_request(db, request_key: str, user_id: int, payload: str) -> bool:
    try:
        await db.delivery_requests.insert_one({
            "request_key": request_key, "user_id": user_id, "payload": payload,
            "status": "processing", "created_at": _now(), "updated_at": _now(),
        })
        return True
    except Exception as exc:
        if getattr(exc, "code", None) != 11000:
            raise
        existing = await db.delivery_requests.find_one({"request_key": request_key})
        if not existing or existing.get("status") in ("processing", "done"):
            return False
        result = await db.delivery_requests.update_one(
            {"request_key": request_key, "status": "failed"},
            {"$set": {"status": "processing", "updated_at": _now(), "last_retry_at": _now()}},
        )
        return bool(result.modified_count)


async def finish_delivery_request(db, request_key: str, success: bool):
    await db.delivery_requests.update_one(
        {"request_key": request_key, "status": "processing"},
        {"$set": {"status": "done" if success else "failed", "updated_at": _now()}},
    )


def _minutes(cfg):
    allowed = (2, 5, 15, 30, 60, 180, 360, 720, 1440)
    try:
        value = int((cfg or {}).get("minutes", 30))
    except (TypeError, ValueError):
        return 30
    return value if value in allowed else 30


def _notice(cfg, minutes):
    value = (cfg or {}).get("notice") or DEFAULT_NOTICE
    if minutes % 60 == 0 and minutes >= 60:
        hours = minutes // 60
        label = f"{hours} hour" if hours == 1 else f"{hours} hours"
    elif minutes < 60:
        label = f"{minutes} minutes"
    else:
        label = f"{minutes // 60}h {minutes % 60}m"
    return value.replace("{auto_delete_time}", label)


async def _save_expiry_task(db, user_id, message_ids, deadline, deeplink, request_key=None):
    task = {
        "kind": "delete_delivery", "user_id": user_id,
        "message_ids": list(message_ids), "deadline": deadline,
        "deeplink": deeplink, "status": "pending",
        "created_at": _now(), "messages_deleted": False,
        "after_delete_attempted": False,
    }
    if request_key:
        task["request_key"] = request_key
        await db.tasks.update_one(
            {"request_key": request_key}, {"$setOnInsert": task}, upsert=True
        )
    else:
        await db.tasks.insert_one(task)


async def deliver_reference(bot: Bot, db, settings, *, user_id: int, file_doc: dict, deeplink: str, request_key: str | None = None):
    """Use the durable per-item queue for a single-file delivery as well."""
    item = {
        "source_chat_id": file_doc["source_chat_id"],
        "source_message_id": file_doc["source_message_id"],
        "file_name": file_doc.get("file_name"),
    }
    return await deliver_batch(
        bot, db, user_id=user_id, batch={"batch_id": None, "items": [item]},
        deeplink=deeplink, request_key=request_key,
    )

async def _process_batch_delivery(bot: Bot, db, request_key: str):
    """Resume a persisted batch at the next not-yet-attempted item."""
    try:
        doc = await db.batch_deliveries.find_one({"request_key": request_key})
        if not doc or doc.get("status") == "done":
            return (len((doc or {}).get("delivered_message_ids", [])), int((doc or {}).get("failed_count", 0)))
        items = doc.get("items", [])
        while int(doc.get("next_index", 0)) < len(items):
            index = int(doc.get("next_index", 0))
            state = (doc.get("item_states") or [{} for _ in items])[index]
            if state.get("status") == "sending":
                # The process may have died after Telegram accepted the copy but before MongoDB recorded it.
                await db.batch_deliveries.update_one(
                    {"request_key": request_key, "status": "processing", "next_index": index},
                    {"$set": {f"item_states.{index}.status": "unknown", "next_index": index + 1},
                     "$inc": {"failed_count": 1}},
                )
                doc = await db.batch_deliveries.find_one({"request_key": request_key})
                continue
            claim = await db.batch_deliveries.update_one(
                {"request_key": request_key, "status": "processing", "next_index": index,
                 f"item_states.{index}.status": "pending"},
                {"$set": {f"item_states.{index}.status": "sending",
                          f"item_states.{index}.started_at": _now()}},
            )
            if not claim.modified_count:
                doc = await db.batch_deliveries.find_one({"request_key": request_key})
                if not doc or doc.get("status") != "processing":
                    return (len((doc or {}).get("delivered_message_ids", [])), int((doc or {}).get("failed_count", 0)))
                continue
            item = items[index]
            try:
                sent = await bot.copy_message(
                    chat_id=doc["user_id"], from_chat_id=item["source_chat_id"],
                    message_id=item["source_message_id"],
                )
                deadline = doc.get("deadline")
                if doc.get("auto_delete") and deadline is None:
                    deadline = _now() + timedelta(minutes=int(doc["minutes"]))
                fields = {
                    f"item_states.{index}.status": "delivered",
                    f"item_states.{index}.message_id": sent.message_id,
                    f"item_states.{index}.finished_at": _now(),
                    "next_index": index + 1,
                }
                if deadline is not None:
                    fields["deadline"] = deadline
                await db.batch_deliveries.update_one(
                    {"request_key": request_key, "status": "processing", "next_index": index},
                    {"$set": fields, "$push": {"delivered_message_ids": sent.message_id}},
                )
            except TelegramAPIError as exc:
                await db.batch_deliveries.update_one(
                    {"request_key": request_key, "status": "processing", "next_index": index},
                    {"$set": {f"item_states.{index}.status": "failed",
                              f"item_states.{index}.error": type(exc).__name__,
                              f"item_states.{index}.finished_at": _now(),
                              "next_index": index + 1},
                     "$inc": {"failed_count": 1}},
                )
                log.warning("Batch item %s failed for user %s: %s", index, doc["user_id"], type(exc).__name__)
            doc = await db.batch_deliveries.find_one({"request_key": request_key})

        doc = await db.batch_deliveries.find_one({"request_key": request_key})
        delivered_ids = list(doc.get("delivered_message_ids", []))
        deadline = doc.get("deadline")
        if doc.get("auto_delete") and deadline and deadline > _now() and doc.get("alert_status") == "pending":
            claimed = await db.batch_deliveries.update_one(
                {"request_key": request_key, "status": "processing", "alert_status": "pending"},
                {"$set": {"alert_status": "sending", "alert_started_at": _now()}},
            )
            if claimed.modified_count:
                try:
                    alert = await bot.send_message(doc["user_id"], _notice({"notice": doc.get("notice")}, int(doc["minutes"])))
                    await db.batch_deliveries.update_one(
                        {"request_key": request_key, "status": "processing"},
                        {"$set": {"alert_status": "sent", "alert_message_id": alert.message_id, "alert_sent_at": _now()}},
                    )
                except TelegramAPIError as exc:
                    await db.batch_deliveries.update_one(
                        {"request_key": request_key, "status": "processing"},
                        {"$set": {"alert_status": "failed", "alert_error": type(exc).__name__}},
                    )
                    log.exception("Batch delivered but auto-delete notice could not be sent")
        elif doc.get("alert_status") == "sending":
            # Do not resend an alert with an ambiguous outcome after restart.
            await db.batch_deliveries.update_one(
                {"request_key": request_key, "status": "processing", "alert_status": "sending"},
                {"$set": {"alert_status": "unknown"}},
            )
        doc = await db.batch_deliveries.find_one({"request_key": request_key})
        if doc.get("auto_delete") and doc.get("deadline"):
            message_ids = list(doc.get("delivered_message_ids", []))
            if doc.get("alert_status") == "sent" and doc.get("alert_message_id"):
                message_ids.append(doc["alert_message_id"])
            await _save_expiry_task(
                db, doc["user_id"], message_ids, doc["deadline"], doc["deeplink"],
                request_key=f"batch-expiry:{request_key}",
            )
        await db.batch_deliveries.update_one(
            {"request_key": request_key, "status": "processing"},
            {"$set": {"status": "done", "finished_at": _now()}},
        )
        final = await db.batch_deliveries.find_one({"request_key": request_key})
        return (len(final.get("delivered_message_ids", [])), int(final.get("failed_count", 0)))
    except Exception:
        log.exception("Batch delivery processing interrupted; persisted progress will be resumed")
        await db.batch_deliveries.update_one(
            {"request_key": request_key, "status": "processing"},
            {"$set": {"status": "pending", "last_error_at": _now()}},
        )
        raise


async def deliver_batch(bot: Bot, db, *, user_id: int, batch: dict, deeplink: str, request_key: str | None = None):
    """Persist every batch item before sending, so restarts can resume safely."""
    request_key = request_key or f"batch:{user_id}:{token_urlsafe(12)}"
    existing = await db.batch_deliveries.find_one({"request_key": request_key})
    if not existing:
        auto = await db.settings.find_one({"key": "auto_delete", "enabled": True})
        items = list(batch.get("items", []))
        if not items:
            return (0, 0)
        doc = {
            "request_key": request_key, "user_id": user_id, "batch_id": batch.get("batch_id"),
            "items": items, "item_states": [{"status": "pending"} for _ in items],
            "next_index": 0, "delivered_message_ids": [], "failed_count": 0,
            "auto_delete": bool(auto), "minutes": _minutes(auto) if auto else None,
            "notice": (auto or {}).get("notice", DEFAULT_NOTICE), "deadline": None,
            "alert_status": "pending", "deeplink": deeplink, "status": "processing",
            "created_at": _now(),
        }
        try:
            await db.batch_deliveries.insert_one(doc)
        except Exception as exc:
            if getattr(exc, "code", None) != 11000:
                raise
    else:
        if existing.get("status") == "done":
            return (len(existing.get("delivered_message_ids", [])), int(existing.get("failed_count", 0)))
        if existing.get("status") == "pending":
            claim = await db.batch_deliveries.update_one(
                {"request_key": request_key, "status": "pending"},
                {"$set": {"status": "processing", "resumed_at": _now()}},
            )
            if not claim.modified_count:
                return (len(existing.get("delivered_message_ids", [])), int(existing.get("failed_count", 0)))
    return await _process_batch_delivery(bot, db, request_key)


async def run_batch_delivery_worker(bot: Bot, db, poll_seconds: int = 2):
    """Resume durable batch deliveries left pending by a prior interruption."""
    while True:
        doc = await db.batch_deliveries.find_one_and_update(
            {"status": "pending"},
            {"$set": {"status": "processing", "worker_claimed_at": _now()}},
            sort=[("created_at", 1)],
            return_document=True,
        )
        if not doc:
            await asyncio.sleep(poll_seconds)
            continue
        try:
            await _process_batch_delivery(bot, db, doc["request_key"])
        except Exception:
            log.exception("Background batch delivery remains pending and will retry")
        await asyncio.sleep(0.05)


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
                    except (TelegramForbiddenError, TelegramBadRequest):
                        log.warning("After-delete replacement cannot be sent for user %s", task["user_id"])
                    except TelegramAPIError:
                        await db.tasks.update_one({"_id": task["_id"]}, {"$set": {"after_delete_attempted": False}})
                        log.exception("Transient After-delete replacement failure; expiry task will retry")
                        raise
                await db.tasks.update_one({"_id": task["_id"]}, {"$set": {"status": "done", "finished_at": _now()}})
            except Exception:
                log.exception("Expiry task failed")
                await db.tasks.update_one({"_id": task["_id"]}, {"$set": {"status": "pending", "last_error_at": _now()}})
        await asyncio.sleep(poll_seconds)
