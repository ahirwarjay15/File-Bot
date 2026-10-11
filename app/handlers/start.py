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
        except TelegramAPIError:missing.append(channel)
    return missing

async def gate_or_prompt(message:Message,payload:str,settings,database,bot)->bool:
    user=message.from_user
    if not user or user.id==settings.owner_id or await is_owner_or_moderator(database.db,user.id,settings):return False
    missing=await join_status(bot,user.id,settings.force_join_channels)
    if not missing:return False
    rows=[]
    for channel in missing:
        target=channel if channel.startswith("https://") else ("https://t.me/"+channel.lstrip("@") if not channel.lstrip("-").isdigit() else None)
        if target:rows.append([InlineKeyboardButton(text="Join channel",url=target)])
    rows.append([InlineKeyboardButton(text="I Joined — Check Again",callback_data=f"forcejoin:check:{payload}")])
    await message.answer("Please join the required channel(s) before receiving this file.",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    return True

async def deliver_payload(bot,database,settings,user_id:int,payload:str,record:dict):
    me=await bot.get_me();link=f"https://t.me/{me.username}?start={payload}"
    if payload.startswith("file_"):return await deliver_reference(bot,database.db,settings,user_id=user_id,file_doc=record,deeplink=link)
    return await deliver_batch(bot,database.db,user_id=user_id,batch=record,deeplink=link)

@router.message(CommandStart())
async def start_command(message:Message,command:CommandObject,settings:Settings,database,bot):
    user=message.from_user
    if not user:return
    repo=FileRepository(database.db);await repo.save_user(user)
    if await repo.is_banned(user.id):return
    payload=command.args or ""
    if payload:
        if payload.startswith("file_"):record=await repo.get_file(payload[5:])
        elif payload.startswith("batch_"):record=await repo.get_batch(payload[6:])
        else:
            await message.answer("This link is invalid or expired.");return
        if not record or len(payload.split("_",1)[1])>40:
            await message.answer("This link is invalid or expired.");return
        if await gate_or_prompt(message,payload,settings,database,bot):return
        try:
            result=await deliver_payload(bot,database,settings,message.chat.id,payload,record)
            if payload.startswith("batch_") and result[0]==0:await message.answer("None of the batch files could be delivered. The source messages may be unavailable.")
            elif payload.startswith("batch_") and result[1]:log.warning("Batch delivery partial: %s delivered, %s failed",*result)
        except TelegramAPIError:
            log.exception("Delivery failed for %s",payload);await message.answer("This file is currently unavailable. Please contact the bot owner.")
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
    if payload.startswith("file_"):record=await repo.get_file(payload[5:])
    elif payload.startswith("batch_"):record=await repo.get_batch(payload[6:])
    else:return
    if not record:
        if query.message:await query.message.answer("This link is invalid or expired.")
        return
    try:
        result=await deliver_payload(bot,database,settings,query.from_user.id,payload,record)
        if payload.startswith("batch_") and result[0]==0 and query.message:await query.message.answer("None of the batch files could be delivered.")
    except TelegramAPIError:
        log.exception("Delivery after Force Join failed")
        if query.message:await query.message.answer("File delivery failed. Contact the owner.")

@router.callback_query(F.data=="invalid:about")
async def invalid_about(query:CallbackQuery,settings:Settings,database):
    await query.answer()
    if not query.from_user or await is_banned_for_callback(database.db,query.from_user.id):return
    cfg=await database.db.settings.find_one({"key":"invalid_post"})
    if not cfg or not cfg.get("about_enabled"):return
    if query.message:
        try:await query.message.edit_text(cfg.get("about_text") or "This bot delivers files using permanent source-channel references.")
        except TelegramAPIError:pass

async def is_banned_for_callback(db,user_id:int)->bool:
    doc=await db.users.find_one({"user_id":user_id},{"banned":1})
    return bool(doc and doc.get("banned"))
