"""Persistent batch creation: up to 100 ordered messages, one permanent batch deeplink."""
import logging,time
from aiogram import Router,F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State,StatesGroup
from aiogram.types import Message,InlineKeyboardMarkup,InlineKeyboardButton,CallbackQuery
from aiogram.exceptions import TelegramAPIError
from app.config import Settings
from app.database.files import FileRepository
from app.services.permissions import is_owner_or_moderator

router=Router(name="batch"); log=logging.getLogger(__name__)
class BatchState(StatesGroup): collecting=State()
def menu():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Generate link",callback_data="batch:generate"),InlineKeyboardButton(text="Cancel",callback_data="batch:cancel")]])

@router.message(Command("batch"))
async def batch_start(message:Message,state:FSMContext,settings:Settings,database):
    if not message.from_user or not await is_owner_or_moderator(database.db,message.from_user.id,settings):return
    if not settings.source_channel_id:
        await message.answer("Configure SOURCE_CHANNEL_ID first.");return
    await state.set_state(BatchState.collecting)
    await state.set_data({"items":[],"last_activity":time.time()})
    await message.answer("Send up to 100 messages in original order. You can send multiple messages across updates. Tap Generate link when finished. Session ends after 200 seconds of inactivity.",reply_markup=menu())

@router.message(BatchState.collecting,Command("cancel"))
async def cancel(message:Message,state:FSMContext):
    await state.clear();await message.answer("Batch process cancelled. No changes were made to previously saved files.")

@router.message(BatchState.collecting)
async def collect(message:Message,state:FSMContext,settings:Settings,database):
    if message.text and message.text.startswith("/"):return
    data=await state.get_data()
    if time.time()-data.get("last_activity",0)>200:
        await state.clear();await message.answer("Time's up. Try again.");return
    items=data.get("items",[])
    if len(items)>=100:
        await message.answer("Maximum 100 messages reached. Generate the batch link.");return
    try:
        copied=await message.bot.copy_message(chat_id=settings.source_channel_id,from_chat_id=message.chat.id,message_id=message.message_id)
        items.append({"source_chat_id":settings.source_channel_id,"source_message_id":copied.message_id,"file_name":message.document.file_name if message.document else None})
        await state.update_data(items=items,last_activity=time.time())
        await message.answer(f"Batch storage\nStored messages: {len(items)}/100\nWant to add more? Send them here.",reply_markup=menu())
    except TelegramAPIError:
        log.exception("Batch source copy failed");await message.answer("Couldn't save this message. Check source-channel permissions.")

@router.callback_query(F.data.startswith("batch:"))
async def actions(query:CallbackQuery,state:FSMContext,settings:Settings,database):
    await query.answer()
    if not query.from_user or not await is_owner_or_moderator(database.db,query.from_user.id,settings):return
    action=query.data.split(":",1)[1]
    if action=="cancel":
        await state.clear()
        if query.message:await query.message.edit_text("Batch process cancelled. No changes were made to previously saved files.")
        return
    data=await state.get_data()
    if await state.get_state()!=BatchState.collecting.state or time.time()-data.get("last_activity",0)>200:
        await state.clear()
        if query.message:await query.message.edit_text("Time's up. Try again.")
        return
    items=data.get("items",[])
    if not items:
        if query.message:await query.message.answer("Add at least one message first.")
        return
    batch=await FileRepository(database.db).save_batch(items,query.from_user.id)
    await state.clear()
    me=await query.bot.get_me();link=f"https://t.me/{me.username}?start=batch_{batch['batch_id']}"
    if query.message:
        await query.message.answer(link,reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="COPY",copy_text={"text":link})]]))
