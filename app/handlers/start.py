"""Start command, Force Join gate, and single/batch deeplink delivery."""
import logging
import hashlib
from datetime import datetime, timezone
from aiogram import Router,F
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import Message,InlineKeyboardMarkup,InlineKeyboardButton,CallbackQuery
from aiogram.exceptions import TelegramAPIError
from app.config import Settings
from app.database.files import FileRepository
from app.services.delivery import deliver_reference,deliver_batch,claim_delivery_request,finish_delivery_request
from app.services.permissions import is_owner_or_moderator
router=Router(name="start");log=logging.getLogger(__name__)

async def effective_force_join_channels(database, settings) -> list[str]:
    cfg = await database.db.settings.find_one({"key": "force_join"})
    raw_channels = cfg.get("channels", []) if cfg is not None and isinstance(cfg.get("channels"), list) else settings.force_join_channels
    channels = []
    for raw in raw_channels:
        channel = str(raw).strip()
        if channel.startswith("https://t.me/"):
            channel = "@" + channel.removeprefix("https://t.me/").strip("/").split("/", 1)[0].lstrip("@")
        if channel:
            channels.append(channel)
    return channels

def _join_signature(channels: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(c.strip() for c in channels if c.strip())).encode()).hexdigest()

async def _is_verified(db, user_id: int, channels: list[str]) -> bool:
    if not channels:
        return True
    user = await db.users.find_one({"user_id": user_id}, {"force_join_signature": 1})
    return bool(user and user.get("force_join_signature") == _join_signature(channels))

async def _mark_verified(db, user_id: int, channels: list[str]):
    await db.users.update_one(
        {"user_id": user_id},
        {"$set": {"force_join_signature": _join_signature(channels), "force_join_verified_at": datetime.now(timezone.utc)}},
    )

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
    channels = await effective_force_join_channels(database, settings)
    if await _is_verified(database.db, user.id, channels): return False
    missing=await join_status(bot,user.id,channels)
    if not missing:
        await _mark_verified(database.db, user.id, channels)
        return False
    rows=[]
    for channel in missing:
        target=channel if channel.startswith("https://") else ("https://t.me/"+channel.lstrip("@") if not channel.lstrip("-").isdigit() else None)
        if target:rows.append([InlineKeyboardButton(text="Join channel",url=target)])
    rows.append([InlineKeyboardButton(text="I Joined — Check Again",callback_data=f"forcejoin:check:{payload}")])
    await message.answer("Please join the required channel(s) before receiving this file.",reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    return True

async def deliver_payload(bot,database,settings,user_id:int,payload:str,record:dict,request_key:str|None=None):
    me=await bot.get_me();link=f"https://t.me/{me.username}?start={payload}"
    if payload.startswith("file_"):return await deliver_reference(bot,database.db,settings,user_id=user_id,file_doc=record,deeplink=link,request_key=request_key)
    return await deliver_batch(bot,database.db,user_id=user_id,batch=record,deeplink=link,request_key=request_key)

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
        request_key = f"start:{user.id}:{message.message_id}"
        if not await claim_delivery_request(database.db, request_key, user.id, payload):
            return
        success = False
        try:
            result=await deliver_payload(bot,database,settings,message.chat.id,payload,record,request_key=request_key)
            if payload.startswith("batch_") and result[0]==0:
                await message.answer("None of the batch files could be delivered. The source messages may be unavailable.")
            elif payload.startswith("batch_") and result[1]:
                log.warning("Batch delivery partial: %s delivered, %s failed",*result)
            elif payload.startswith("file_") and result[0] == 0:
                await message.answer("This file is currently unavailable. The source message may have been deleted or become inaccessible.")
            success = result[0] > 0
        except TelegramAPIError:
            log.exception("Delivery failed for %s",payload);await message.answer("This file is currently unavailable. Please contact the bot owner.")
        except Exception:
            log.exception("Unexpected delivery failure for %s", payload)
            await message.answer("Delivery failed due to a temporary error. Please try the link again.")
        finally:
            try: await finish_delivery_request(database.db, request_key, success)
            except Exception: log.exception("Could not update delivery request status")
        return
    if await is_owner_or_moderator(database.db,user.id,settings):return
    cfg=await database.db.settings.find_one({"key":"start_message"})
    if cfg is None or cfg.get("enabled",True):
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=cfg.get("about_button_text", "ABOUT"), callback_data="start:about")
        ]]) if cfg and cfg.get("about_enabled", False) else None
        await message.answer((cfg or {}).get("text") or "👋 Welcome! Send a valid file link to receive your file.", reply_markup=markup)

@router.callback_query(F.data == "start:about")
async def start_about(query: CallbackQuery, database):
    await query.answer()
    if not query.from_user or await FileRepository(database.db).is_banned(query.from_user.id):
        return
    cfg = await database.db.settings.find_one({"key": "start_message"}) or {}
    if not cfg.get("enabled", True) or not cfg.get("about_enabled", False) or not query.message:
        return
    about_text = cfg.get("about_text") or "This bot delivers files using permanent source-channel references."
    try:
        await query.message.edit_text(about_text)
    except TelegramAPIError:
        pass

@router.callback_query(F.data.startswith("forcejoin:check:"))
async def forcejoin_check(query:CallbackQuery,settings:Settings,database,bot):
    await query.answer()
    payload=query.data.split(":",2)[2]
    if not query.from_user or await FileRepository(database.db).is_banned(query.from_user.id):return
    channels = await effective_force_join_channels(database, settings)
    missing=[] if await is_owner_or_moderator(database.db, query.from_user.id, settings) else await join_status(bot,query.from_user.id,channels)
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
    request_anchor = query.message.message_id if query.message else query.id
    request_key = f"forcejoin:{query.from_user.id}:{request_anchor}:{payload}"
    if not await claim_delivery_request(database.db, request_key, query.from_user.id, payload):
        return
    await _mark_verified(database.db, query.from_user.id, channels)
    if query.message:
        try: await query.message.delete()
        except TelegramAPIError: pass
    animation_message = None
    success = False
    try:
        animation_cfg = await database.db.settings.find_one({"key": "force_join_animation"})
        if channels and animation_cfg and animation_cfg.get("file_id") and not await is_owner_or_moderator(database.db, query.from_user.id, settings):
            animation_message = await bot.send_animation(query.from_user.id, animation_cfg["file_id"])
        result=await deliver_payload(bot,database,settings,query.from_user.id,payload,record,request_key=request_key)
        if payload.startswith("batch_") and result[0]==0:
            await bot.send_message(query.from_user.id,"None of the batch files could be delivered.")
        elif payload.startswith("file_") and result[0] == 0:
            await bot.send_message(query.from_user.id,"This file is currently unavailable. The source message may have been deleted or become inaccessible.")
        success = result[0] > 0
    except TelegramAPIError:
        log.exception("Delivery after Force Join failed")
        await bot.send_message(query.from_user.id,"File delivery failed. Contact the owner.")
    except Exception:
        log.exception("Unexpected delivery failure after Force Join")
        await bot.send_message(query.from_user.id,"Delivery failed due to a temporary error.")
    finally:
        try: await finish_delivery_request(database.db, request_key, success)
        except Exception: log.exception("Could not update Force Join delivery request status")
        if animation_message:
            try: await bot.delete_message(query.from_user.id, animation_message.message_id)
            except TelegramAPIError: pass

@router.callback_query(F.data=="invalid:about")
async def invalid_about(query:CallbackQuery,settings:Settings,database):
    await query.answer()
    if not query.from_user or await is_banned_for_callback(database.db,query.from_user.id):return
    cfg=await database.db.settings.find_one({"key":"invalid_post"})
    if not cfg or not cfg.get("about_enabled"):return
    if query.message:
        text = cfg.get("about_text") or "This bot delivers files using permanent source-channel references."
        try:
            if query.message.photo or query.message.animation or query.message.document:
                await query.message.edit_caption(caption=text)
            else:
                await query.message.edit_text(text)
        except TelegramAPIError:
            pass

async def is_banned_for_callback(db,user_id:int)->bool:
    doc=await db.users.find_one({"user_id":user_id},{"banned":1})
    return bool(doc and doc.get("banned"))
