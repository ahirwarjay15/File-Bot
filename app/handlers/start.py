"""Start command, force-join gate, and file deeplink delivery."""
import logging
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError
from aiogram.filters.command import CommandObject
from app.config import Settings
from app.database.files import FileRepository
from app.services.delivery import deliver_reference
from app.services.permissions import is_owner_or_moderator

router=Router(name="start")
log=logging.getLogger(__name__)

async def join_status(bot,user_id:int,channels:list[str])->list[str]:
    missing=[]
    for raw in channels:
        channel=raw.strip()
        if not channel: continue
        try:
            member=await bot.get_chat_member(chat_id=channel,user_id=user_id)
            if member.status not in ("creator","administrator","member") and not (member.status=="restricted" and getattr(member,"is_member",False)):
                missing.append(channel)
        except TelegramAPIError:
            # Fail closed: configuration/admin-permission problems must not silently bypass the gate.
            missing.append(channel)
    return missing

@router.message(CommandStart())
async def start_command(message:Message,command:CommandObject,settings:Settings,database,bot)->None:
    user=message.from_user
    if not user: return
    repo=FileRepository(database.db)
    await repo.save_user(user)
    if await repo.is_banned(user.id): return
    payload=command.args or ""
    if payload.startswith("file_"):
        key=payload[5:]
        if not key or len(key)>40:
            await message.answer("This file link is invalid or expired."); return
        record=await repo.get_file(key)
        if not record:
            await message.answer("This file link is invalid or expired."); return
        if user.id!=settings.owner_id and not await is_owner_or_moderator(database.db,user.id,settings):
            missing=await join_status(bot,user.id,settings.force_join_channels)
            if missing:
                buttons=[]
                for channel in missing:
                    target=channel if channel.startswith("https://") else ("https://t.me/"+channel.lstrip("@") if not channel.lstrip("-").isdigit() else None)
                    if target: buttons.append([InlineKeyboardButton(text="Join channel",url=target)])
                buttons.append([InlineKeyboardButton(text="I Joined — Check Again",callback_data="forcejoin:check")])
                # Keep the requested file key attached to the verification callback.
                buttons[-1][0].callback_data=f"forcejoin:check:{key}"
                await message.answer("Please join the required channel(s) before receiving this file.",reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
                return
        try:
            me=await bot.get_me()
            link=f"https://t.me/{me.username}?start=file_{key}"
            await deliver_reference(bot,database.db,settings,user_id=message.chat.id,file_doc=record,deeplink=link)
        except TelegramAPIError:
            log.exception("File delivery failed for key %s",key)
            await message.answer("This file is currently unavailable. Please contact the bot owner.")
        return
    if await is_owner_or_moderator(database.db,user.id,settings): return
    cfg=await database.db.settings.find_one({"key":"start_message"})
    if cfg is None or cfg.get("enabled",True):
        await message.answer((cfg or {}).get("text") or "👋 Welcome! Send a valid file link to receive your file.")

from aiogram import F
from aiogram.types import CallbackQuery

@router.callback_query(F.data.startswith("forcejoin:check:"))
async def forcejoin_check(query:CallbackQuery,settings:Settings,database,bot):
    await query.answer()
    key=query.data.split(":",2)[2]
    if not query.from_user: return
    missing=await join_status(bot,query.from_user.id,settings.force_join_channels)
    if missing:
        if query.message: await query.message.answer("You haven't joined all required channels yet.")
        return
    record=await FileRepository(database.db).get_file(key)
    if not record:
        if query.message: await query.message.answer("This file link is invalid or expired.")
        return
    try:
        link=f"https://t.me/{(await bot.get_me()).username}?start=file_{key}"
        await deliver_reference(bot,database.db,settings,user_id=query.from_user.id,file_doc=record,deeplink=link)
    except TelegramAPIError:
        log.exception("Delivery after force-join failed")
        if query.message: await query.message.answer("File delivery failed. Contact the owner.")
