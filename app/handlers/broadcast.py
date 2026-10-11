import asyncio
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from app.config import Settings
from app.services.permissions import is_owner_or_moderator

router=Router(name="broadcast")

@router.message(Command("broadcast"))
async def broadcast(message:Message,settings:Settings,database):
    if not message.from_user or not await is_owner_or_moderator(database.db,message.from_user.id,settings): return
    if not message.reply_to_message:
        await message.answer("Reply to the message you want to broadcast, then send /broadcast."); return
    source=message.reply_to_message
    users=database.db.users.find({"banned":{"$ne":True}},{"user_id":1})
    # First request confirmation so a misfire cannot send to every user.
    await database.db.broadcast_drafts.update_one({"admin_id":message.from_user.id},{"$set":{"admin_id":message.from_user.id,"chat_id":source.chat.id,"message_id":source.message_id}},upsert=True)
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    await message.answer("Confirm broadcast to all non-banned tracked users?",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Confirm",callback_data="broadcast:yes"),InlineKeyboardButton(text="Cancel",callback_data="broadcast:no")]]))

from aiogram import F
from aiogram.types import CallbackQuery

@router.callback_query(F.data.startswith("broadcast:"))
async def broadcast_confirm(query:CallbackQuery,settings:Settings,database):
    await query.answer()
    if not query.from_user or not await is_owner_or_moderator(database.db,query.from_user.id,settings): return
    if query.data.endswith(":no"):
        await database.db.broadcast_drafts.delete_one({"admin_id":query.from_user.id})
        if query.message: await query.message.edit_text("Broadcast cancelled.")
        return
    draft=await database.db.broadcast_drafts.find_one({"admin_id":query.from_user.id})
    if not draft:
        if query.message: await query.message.edit_text("Draft expired; start again.")
        return
    sent=failed=0
    async for user in database.db.users.find({"banned":{"$ne":True}},{"user_id":1}):
        try:
            await query.bot.copy_message(chat_id=user["user_id"],from_chat_id=draft["chat_id"],message_id=draft["message_id"])
            sent+=1
        except Exception:
            failed+=1
        await asyncio.sleep(0.05)
    await database.db.broadcast_drafts.delete_one({"admin_id":query.from_user.id})
    if query.message: await query.message.edit_text(f"Broadcast complete. Sent: {sent}; failed/unreachable: {failed}.")
