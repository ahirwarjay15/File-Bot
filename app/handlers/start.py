"""Start command, Force Join gate, and single/batch deeplink delivery."""
import logging
from aiogram import Router,F
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import Message,InlineKeyboardMarkup,InlineKeyboardButton,CallbackQuery
from aiogram.exceptions import TelegramAPIError
from app.config import Settings
from app.database.files import FileRepository
from app.services.delivery import deliver_reference,deliver_batch
from app.services.permissions import is_owner_or_moderator

router=Router(name="start");log=logging.getLogger(__name__)

async def join_status(bot,user_id:int,channels:list[str])->list[str]:
    missing=[]
    for raw in channels:
        channel=raw.strip()
        if not channel:continue
        try:
            member=await bot.get_chat_member(chat_id=channel,user_id=user_id)
            if member.status not in ("creator","administrator","member") and not(member.status=="restricted" and getattr(member,"is_member",False)):missing.append(channel)
        except TelegramAPIError:
            missing.append(channel)
    return missing

async def gate_or_prompt(message:Message,key:str,settings,database,bot)->bool:
    user=message.from_user
    if not user or user.id==settings.owner_id or await is_owner_or_moderator(database.db,user.id,settings):return False
    missing=await join_status(bot,user.id,settings.force_join_channels)
    if not missing:return False
    rows=[]
    for channel in missing:
        target=channel if channel.startswith("https://") else ("https://t.me/"+channel.lstrip("@") if not channel.lstrip("-").isdigit() else None)
        if target:rows.append([InlineKeyboardButton(text="Join channel",url=target)])
    rows.append([InlineKeyboardButton(text="I Joined — Check Again",callback_data=f"forcejoin:check:{key}")])
    await message.answer("Please join the required channel(s) before receiving this file.",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    return True

@router.message(CommandStart())
async def start_command(message:Message,command:CommandObject,settings:Settings,database,bot):
    user=message.from_user
    if not user:return
    repo=FileRepository(database.db);await repo.save_user(user)
    if await repo.is_banned(user.id):return
    payload=command.args or ""
    if payload.startswith("file_") or payload.startswith("batch_"):
        kind,key=payload.split("_",1)
        if not key or len(key)>40:
            await message.answer("This link is invalid or expired.");return
        record=await (repo.get_file(key) if kind=="file" else repo.get_batch(key))
        if not record:
            await message.answer("This link is invalid or expired.");return
        if await gate_or_prompt(message,payload,settings,database,bot):return
        me=await bot.get_me();link=f"https://t.me/{me.username}?start={payload}"
        try:
            if kind=="file":await deliver_reference(bot,database.db,settings,user_id=message.chat.id,file_doc=record,deeplink=link)
            else:
                delivered,failed=await deliver_batch(bot,database.db,user_id=message.chat.id,batch=record,deeplink=link)
                if not delivered:await message.answer("None of the batch files could be delivered. The source messages may be unavailable.")
                elif failed:log.warning("Batch delivery partial: %s delivered, %s failed",delivered,failed)
        except TelegramAPIError:
            log.exception("Delivery failed for %s",payload)
            await message.answer("This file is currently unavailable. Please contact the bot owner.")
        return
    if await is_owner_or_moderator(database.db,user.id,settings):return
    cfg=await database.db.settings.find_one({"key":"start_message"})
    if cfg is None or cfg.get("enabled",True):await message.answer((cfg or {}).get("text") or "👋 Welcome! Send a valid file link to receive your file.")

@router.callback_query(F.data.startswith("forcejoin:check:"))
async def forcejoin_check(query:CallbackQuery,settings:Settings,database,bot):
    await query.answer()
    payload=query.data.split(":",2)[2]
    if not query.from_user or await FileRepository(database.db).is_banned(query.from_user.id):return
    missing=await join_status(bot,query.from_user.id,settings.force_join_channels)
    if missing:
        if query.message:await query.message.answer("You haven't joined all required channels yet.")
        return
    repo=FileRepository(database.db)
    if payload.startswith("file_"):kind,key="file",payload[5:];record=await repo.get_file(key)
    elif payload.startswith("batch_"):kind,key="batch",payload[6:];record=await repo.get_batch(key)
    else:return
    if not record:
        if query.message:await query.message.answer("This link is invalid or expired.")
        return
    link=f"https://t.me/{(await bot.get_me()).username}?start={payload}"
    try:
        if kind=="file":await deliver_reference(bot,database.db,settings,user_id=query.from_user.id,file_doc=record,deeplink=link)
        else:await deliver_batch(bot,database.db,user_id=query.from_user.id,batch=record,deeplink=link)
    except TelegramAPIError:
        log.exception("Delivery after Force Join failed")
        if query.message:await query.message.answer("File delivery failed. Contact the owner.")
