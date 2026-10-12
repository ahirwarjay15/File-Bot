"""MongoDB-backed batch collection with one permanent deeplink per batch."""
import logging
import time
from secrets import token_urlsafe
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, CopyTextButton
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.dispatcher.event.bases import SkipHandler
from app.config import Settings
from app.database.files import FileRepository
from app.services.permissions import is_owner_or_moderator

router = Router(name="batch")
log = logging.getLogger(__name__)
SESSION_TTL = 200

class BatchState(StatesGroup):
    collecting = State()

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="ɢᴇɴᴇʀᴀᴛᴇ ʟɪɴᴋ", callback_data="batch:generate")],
        [InlineKeyboardButton(text="ᴄᴀɴᴄᴇʟ", callback_data="batch:cancel"),
         InlineKeyboardButton(text="《 BACK", callback_data="batch:back")],
    ])

def _now():
    return datetime.now(timezone.utc)

async def _session(db, user_id: int):
    return await db.batch_sessions.find_one({"admin_id": user_id, "status": {"$in": ["collecting", "generating"]}})

async def _expired(session) -> bool:
    if not session:
        return True
    if session.get("status") == "generating":
        return False
    return time.time() - float(session.get("last_activity_ts", 0)) > SESSION_TTL

async def _expire_session(db, user_id: int):
    await db.batch_sessions.update_one(
        {"admin_id": user_id, "status": "collecting"},
        {"$set": {"status": "expired", "finished_at": _now()}},
    )

async def _render_status(message: Message, count: int, session=None, database=None):
    text = (
        f"BATCH STORAGE\n\nStored files: {count}/100\n\n"
        "Want to add more messages? Just send them here!\n\n"
        "✨ You can now send multiple messages at once."
    )
    session = session or (await _session(database.db, message.from_user.id) if database and message.from_user else None)
    if session and session.get("status_message_id"):
        try:
            await message.bot.edit_message_text(
                chat_id=session.get("status_chat_id", message.chat.id),
                message_id=session["status_message_id"],
                text=text,
                reply_markup=menu(),
            )
            return
        except TelegramBadRequest as exc:
            if "message is not modified" in str(exc).lower():
                return
        except TelegramAPIError:
            log.warning("Could not update the existing batch status panel", exc_info=True)
            return
    sent = await message.answer(text, reply_markup=menu())
    if session and database:
        await database.db.batch_sessions.update_one(
            {"_id": session["_id"]},
            {"$set": {"status_message_id": sent.message_id, "status_chat_id": message.chat.id}},
        )

@router.message(Command("batch"))
async def batch_start(message: Message, state: FSMContext, settings: Settings, database):
    if not message.from_user or not await is_owner_or_moderator(database.db, message.from_user.id, settings):
        return
    if not settings.source_channel_id:
        await message.answer("Configure SOURCE_CHANNEL_ID first.")
        return
    uid = message.from_user.id
    existing = await _session(database.db, uid)
    if existing and not await _expired(existing):
        if existing.get("batch_id"):
            saved_batch = await database.db.batches.find_one({"batch_id": existing["batch_id"], "kind": "batch"})
            if saved_batch:
                me = await message.bot.get_me()
                link = f"https://t.me/{me.username}?start=batch_{saved_batch['batch_id']}"
                await database.db.batch_sessions.update_one({"_id": existing["_id"]}, {"$set": {"status": "completed", "completed_at": _now()}})
                await state.clear()
                await message.answer(link, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="ᴄᴏᴘʏ", copy_text=CopyTextButton(text=link))
                ]]))
                return
        await database.db.batch_sessions.update_one(
            {"_id": existing["_id"]},
            {"$set": {"status": "collecting", "last_activity_ts": time.time(), "last_activity_at": _now()}},
        )
        if not existing.get("batch_id") or len(str(existing.get("batch_id", ""))) != 15:
            batch_id = await FileRepository(database.db).reserve_code(15, "batch")
            await database.db.batch_sessions.update_one(
                {"_id": existing["_id"]},
                {"$set": {"batch_id": batch_id}},
            )
        await state.set_state(BatchState.collecting)
        await state.set_data({"admin_id": uid})
        await _render_status(message, len(existing.get("items", [])), existing, database)
        return
    if existing:
        await _expire_session(database.db, uid)
    batch_id = await FileRepository(database.db).reserve_code(15, "batch")
    await database.db.batch_sessions.update_one(
        {"admin_id": uid},
        {"$set": {"admin_id": uid, "items": [], "status": "collecting",
                  "batch_id": batch_id,
                  "started_at": _now(), "last_activity_at": _now(),
                  "last_activity_ts": time.time()}},
        upsert=True,
    )
    await state.set_state(BatchState.collecting)
    await state.set_data({"admin_id": uid})
    fresh = await _session(database.db, uid)
    await _render_status(message, 0, fresh, database)

@router.message(BatchState.collecting, Command("cancel"))
async def cancel_command(message: Message, state: FSMContext, settings: Settings, database):
    if not message.from_user or not await is_owner_or_moderator(database.db, message.from_user.id, settings):
        return
    session = await _session(database.db, message.from_user.id)
    if session:
        await database.db.batch_sessions.update_one(
            {"_id": session["_id"], "status": "collecting"},
            {"$set": {"status": "cancelled", "finished_at": _now()}},
        )
    await state.clear()
    await message.answer("Batch process cancelled. No changes were made to previously saved files.")

async def _collect_message(message: Message, settings: Settings, database, uid: int):
    session = await _session(database.db, uid)
    if not session:
        return False
    if await _expired(session):
        await _expire_session(database.db, uid)
        status_id = session.get("status_message_id")
        if status_id:
            try:
                await message.bot.delete_message(session.get("status_chat_id", message.chat.id), status_id)
            except TelegramAPIError:
                pass
        await message.answer("Time's up. Try again.\n/batch")
        return True
    if message.text and message.text.startswith("/"):
        return False
    items = session.get("items", [])
    if any(item.get("original_message_id") == message.message_id for item in items):
        await message.answer("This message is already included in the batch.")
        return True
    if len(items) >= 100:
        await message.answer("Maximum 100 messages reached. Generate the batch link.")
        return True
    try:
        copied = await message.bot.copy_message(
            chat_id=settings.source_channel_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        item = {
            "source_chat_id": settings.source_channel_id,
            "source_message_id": copied.message_id,
            "file_name": message.document.file_name if message.document else None,
            "source_message_date": message.date.isoformat() if message.date else None,
            "original_message_id": message.message_id,
            "reply_markup": (
                message.reply_markup.model_dump(mode="json", exclude_none=True)
                if message.reply_markup else None
            ),
            **({"original_has_buttons": True} if message.reply_markup and message.reply_markup.inline_keyboard else {}),
        }
        # Conditional update prevents adding to a session cancelled or expired concurrently.
        result = await database.db.batch_sessions.update_one(
            {"_id": session["_id"], "status": "collecting",
             "$expr": {"$lt": [{"$size": "$items"}, 100]}},
            {"$push": {"items": item},
             "$max": {"last_activity_ts": time.time()},
             "$currentDate": {"last_activity_at": True}},
        )
        if not result.modified_count:
            await message.answer("Batch session changed. Use /batch to resume or start again.")
            return True
        latest = await _session(database.db, uid)
        await _render_status(message, len(latest.get("items", [])) if latest else len(items) + 1, latest, database)
    except TelegramAPIError:
        log.exception("Batch source copy failed")
        await message.answer("Couldn't save this message. Check source-channel permissions.")
    return True

@router.message(BatchState.collecting)
async def collect_in_state(message: Message, state: FSMContext, settings: Settings, database):
    if not message.from_user:
        return
    if message.text and message.text.startswith("/"):
        raise SkipHandler
    handled = await _collect_message(message, settings, database, message.from_user.id)
    if not handled:
        await state.clear()
        raise SkipHandler

@router.callback_query(F.data.startswith("batch:"))
async def actions(query: CallbackQuery, state: FSMContext, settings: Settings, database):
    await query.answer()
    if not query.from_user or not await is_owner_or_moderator(database.db, query.from_user.id, settings):
        return
    uid = query.from_user.id
    action = query.data.split(":", 1)[1]
    session = await _session(database.db, uid)
    if action in ("cancel", "back"):
        if session:
            await database.db.batch_sessions.update_one(
                {"_id": session["_id"], "status": "collecting"},
                {"$set": {"status": "cancelled", "finished_at": _now()}},
            )
        await state.clear()
        if query.message:
            await query.message.edit_text("Batch process cancelled. No changes were made to previously saved files." if action == "cancel" else "Back. Batch collection ended; previously saved files were not changed.")
        return
    if not session or await _expired(session):
        if session:
            await _expire_session(database.db, uid)
        await state.clear()
        if query.message:
            try:
                await query.message.delete()
            except TelegramAPIError:
                pass
            await query.message.answer("Time's up. Try again.\n/batch")
        return
    items = sorted(session.get("items", []), key=lambda item: item.get("original_message_id", item.get("source_message_id", 0)))
    if not items:
        if query.message:
            await query.message.answer("Add at least one message first.")
        return
    # Mark as generating before saving to prevent double-click duplicate batches.
    claim = await database.db.batch_sessions.update_one(
        {"_id": session["_id"], "status": "collecting"},
        {"$set": {"status": "generating", "finished_at": _now()}},
    )
    if not claim.modified_count:
        if query.message:
            await query.message.answer("This batch is already being generated.")
        return
    try:
        batch = await FileRepository(database.db).save_batch(items, uid, batch_id=session.get('batch_id'))
        me = await query.bot.get_me()
        link = f"https://t.me/{me.username}?start=batch_{batch['batch_id']}"
        await database.db.batch_sessions.update_one(
            {"_id": session["_id"]},
            {"$set": {"status": "completed", "batch_id": batch["batch_id"], "completed_at": _now()}},
        )
        await state.clear()
        if query.message:
            await query.message.answer(
                link,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="ᴄᴏᴘʏ", copy_text=CopyTextButton(text=link))
                ]]),
            )
    except Exception:
        log.exception("Batch generation failed")
        await database.db.batch_sessions.update_one(
            {"_id": session["_id"], "status": "generating"},
            {"$set": {"status": "collecting", "last_error_at": _now()}},
        )
        if query.message:
            await query.message.answer("Batch link generation failed. Your collected messages are still saved; tap Generate link again.")


async def run_batch_session_worker(bot, db, poll_seconds: int = 2):
    """Expire idle batch sessions durably and notify the collecting moderator."""
    import asyncio
    while True:
        cutoff = time.time() - SESSION_TTL
        async for session in db.batch_sessions.find({"status": "collecting", "last_activity_ts": {"$lte": cutoff}}).limit(100):
            result = await db.batch_sessions.update_one(
                {"_id": session["_id"], "status": "collecting", "last_activity_ts": {"$lte": cutoff}},
                {"$set": {"status": "expired", "finished_at": _now()}},
            )
            if result.modified_count:
                try:
                    status_id = session.get("status_message_id")
                    status_chat = session.get("status_chat_id", session["admin_id"])
                    if status_id:
                        try:
                            await bot.delete_message(status_chat, status_id)
                        except TelegramAPIError:
                            pass
                    await bot.send_message(session["admin_id"], "Time's up. Try again.\n/batch")
                except TelegramAPIError:
                    log.info("Could not notify moderator %s that batch session expired", session["admin_id"])
        await asyncio.sleep(poll_seconds)
