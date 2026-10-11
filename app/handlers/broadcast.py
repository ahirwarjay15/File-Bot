"""Confirmed, rate-limited broadcast with a durable draft and actual result counts."""
import asyncio,logging
from datetime import datetime,timezone
from aiogram import Router,F
from aiogram.filters import Command
from aiogram.types import Message,CallbackQuery,InlineKeyboardMarkup,InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError,RetryAfter,TelegramForbiddenError
from app.config import Settings
from app.services.permissions import is_owner_or_moderator
router=Router(name="broadcast");log=logging.getLogger(__name__)

@router.message(Command("broadcast"))
async def broadcast(message:Message,settings:Settings,database):
    if not message.from_user or not await is_owner_or_moderator(database.db,message.from_user.id,settings):return
    if not message.reply_to_message:
        await message.answer("Reply to the message you want to broadcast, then send /broadcast.");return
    source=message.reply_to_message
    recipients=await database.db.users.count_documents({"banned":{"$ne":True}})
    await database.db.broadcast_drafts.update_one({"admin_id":message.from_user.id},{"$set":{"admin_id":message.from_user.id,"chat_id":source.chat.id,"message_id":source.message_id,"created_at":datetime.now(timezone.utc)}},upsert=True)
    keyboard=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Confirm",callback_data="broadcast:yes"),InlineKeyboardButton(text="Cancel",callback_data="broadcast:no")]])
    await message.answer(f"Broadcast confirmation\nRecipients: {recipients}\nReview the replied message before sending.",reply_markup=keyboard)

@router.callback_query(F.data.startswith("broadcast:"))
async def confirm(query:CallbackQuery,settings:Settings,database):
    await query.answer()
    if not query.from_user or not await is_owner_or_moderator(database.db,query.from_user.id,settings):return
    if query.data=="broadcast:no":
        await database.db.broadcast_drafts.delete_one({"admin_id":query.from_user.id})
        if query.message:await query.message.edit_text("Broadcast cancelled.")
        return
    # Atomically claim the draft to avoid two clicks starting two broadcasts.
    draft=await database.db.broadcast_drafts.find_one_and_update({"admin_id":query.from_user.id,"status":{"$ne":"sending"}},{"$set":{"status":"sending","started_at":datetime.now(timezone.utc)}})
    if not draft:
        if query.message:await query.message.edit_text("Broadcast is already running or the draft expired.")
        return
    sent=failed=blocked=0
    async for user in database.db.users.find({"banned":{"$ne":True}},{"user_id":1}):
        uid=user["user_id"]
        try:
            await query.bot.copy_message(chat_id=uid,from_chat_id=draft["chat_id"],message_id=draft["message_id"])
            sent+=1
        except RetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after)+0.5)
            try:
                await query.bot.copy_message(chat_id=uid,from_chat_id=draft["chat_id"],message_id=draft["message_id"]);sent+=1
            except TelegramForbiddenError:
                failed+=1;blocked+=1
                await database.db.users.update_one({"user_id":uid},{"$set":{"blocked":True,"last_delivery_error":"forbidden"}})
            except Exception:
                failed+=1
        except TelegramForbiddenError:
            failed+=1;blocked+=1
            await database.db.users.update_one({"user_id":uid},{"$set":{"blocked":True,"last_delivery_error":"forbidden"}})
        except TelegramAPIError as exc:
            failed+=1
            await database.db.users.update_one({"user_id":uid},{"$set":{"last_delivery_error":type(exc).__name__,"last_delivery_error_at":datetime.now(timezone.utc)}})
        await asyncio.sleep(0.05)
    await database.db.broadcast_drafts.delete_one({"admin_id":query.from_user.id})
    if query.message:
        await query.message.edit_text(f"Broadcast report\nRecipients: {sent+failed}\nSent successfully: {sent}\nFailed: {failed}\nBlocked/unreachable: {blocked}.")
