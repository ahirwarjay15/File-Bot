"""Batch creator: collects up to 100 messages, then emits one deep link per item."""
import asyncio
import logging
import time
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.exceptions import TelegramAPIError
from app.config import Settings
from app.database.files import FileRepository
from app.services.permissions import is_owner_or_moderator

router = Router(name="batch")
log = logging.getLogger(__name__)

class BatchState(StatesGroup):
    collecting = State()

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Generate links", callback_data="batch:generate"), InlineKeyboardButton(text="Cancel", callback_data="batch:cancel")]])

@router.message(Command("batch"))
async def batch_start(message: Message, state: FSMContext, settings: Settings, database):
    if not message.from_user or not await is_owner_or_moderator(database.db, message.from_user.id, settings):
        return
    await state.set_state(BatchState.collecting)
    await state.set_data({"items": [], "started": time.time(), "last_activity": time.time()})
    await message.answer("Send up to 100 files/messages in the order you want. Tap Generate links when finished. Session expires after 200 seconds.", reply_markup=menu())

@router.message(BatchState.collecting, F.text == "/cancel")
async def batch_cancel_text(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Batch cancelled.")

@router.message(BatchState.collecting)
async def batch_collect(message: Message, state: FSMContext, settings: Settings, database):
    if message.text and message.text.startswith("/"):
        return
    data = await state.get_data()
    if time.time() - data.get("last_activity", 0) > 200:
        await state.clear()
        await message.answer("Batch session expired. Start again with /batch.")
        return
    items = data.get("items", [])
    if len(items) >= 100:
        await message.answer("Maximum 100 messages reached. Tap Generate links.")
        return
    if not settings.source_channel_id:
        await message.answer("Owner must configure SOURCE_CHANNEL_ID first.")
        return
    try:
        copied = await message.bot.copy_message(chat_id=settings.source_channel_id, from_chat_id=message.chat.id, message_id=message.message_id)
        items.append({"source_chat_id": settings.source_channel_id, "source_message_id": copied.message_id, "file_name": (message.document.file_name if message.document else None)})
        await state.update_data(items=items, last_activity=time.time())
        await message.answer(f"Added {len(items)}/100.", reply_markup=menu())
    except TelegramAPIError:
        log.exception("Batch source copy failed")
        await message.answer("Couldn't save this message to the source channel. Check bot admin permissions.")

@router.callback_query(F.data.startswith("batch:"))
async def batch_actions(query: CallbackQuery, state: FSMContext, settings: Settings, database):
    await query.answer()
    if not query.from_user or not await is_owner_or_moderator(database.db, query.from_user.id, settings):
        return
    action = query.data.split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        if query.message:
            await query.message.edit_text("Batch cancelled.")
        return
    data = await state.get_data()
    if await state.get_state() != BatchState.collecting.state or time.time() - data.get("last_activity", 0) > 200:
        await state.clear()
        if query.message:
            await query.message.edit_text("Batch session expired. Start again with /batch.")
        return
    items = data.get("items", [])
    if not items:
        if query.message:
            await query.message.answer("No messages collected yet.")
        return
    repo = FileRepository(database.db)
    me = await query.bot.get_me()
    lines = []
    for item in items:
        doc = await repo.save_file(source_chat_id=item["source_chat_id"], source_message_id=item["source_message_id"], created_by=query.from_user.id, file_name=item.get("file_name"))
        lines.append(f"https://t.me/{me.username}?start=file_{doc['file_key']}")
    await state.clear()
    text = "Batch links (same order as received):\n" + "\n".join(f"{i}. {url}" for i, url in enumerate(lines, 1))
    # Split long output safely under Telegram's message limit.
    for offset in range(0, len(text), 3500):
        await query.message.answer(text[offset:offset+3500])
    if query.message:
        await query.message.answer(f"Generated {len(lines)} links.")
