"""Owner/moderator commands and compact configuration controls."""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from app.config import Settings
from app.services.permissions import is_owner_or_moderator

router = Router(name="admin")

@router.message(Command("ban"))
async def ban_user(message: Message, settings: Settings, database):
    if not message.from_user or not await is_owner_or_moderator(database.db, message.from_user.id, settings): return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /ban TELEGRAM_USER_ID"); return
    uid = int(parts[1])
    if uid == settings.owner_id or await database.db.moderators.find_one({"user_id":uid}):
        await message.answer("Owner/moderators cannot be banned."); return
    await database.db.users.update_one({"user_id":uid}, {"$set":{"banned":True}}, upsert=True)
    await message.answer(f"User {uid} banned.")

@router.message(Command("unban"))
async def unban_user(message: Message, settings: Settings, database):
    if not message.from_user or not await is_owner_or_moderator(database.db, message.from_user.id, settings): return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /unban TELEGRAM_USER_ID"); return
    await database.db.users.update_one({"user_id":int(parts[1])}, {"$set":{"banned":False}}, upsert=True)
    await message.answer("User unbanned.")

@router.message(Command("addmod"))
async def add_mod(message: Message, settings: Settings, database):
    if not message.from_user or message.from_user.id != settings.owner_id: return
    parts = (message.text or "").split()
    if len(parts)!=2 or not parts[1].isdigit(): await message.answer("Usage: /addmod TELEGRAM_USER_ID"); return
    uid=int(parts[1])
    if uid == settings.owner_id: await message.answer("Owner is not stored as a moderator."); return
    if await database.db.moderators.count_documents({}) >= 3 and not await database.db.moderators.find_one({"user_id":uid}):
        await message.answer("Maximum 3 moderators allowed."); return
    await database.db.moderators.update_one({"user_id":uid},{"$setOnInsert":{"user_id":uid}},upsert=True)
    await message.answer(f"Moderator {uid} added.")

@router.message(Command("delmod"))
async def del_mod(message: Message, settings: Settings, database):
    if not message.from_user or message.from_user.id != settings.owner_id: return
    parts=(message.text or "").split()
    if len(parts)!=2 or not parts[1].isdigit(): await message.answer("Usage: /delmod TELEGRAM_USER_ID"); return
    await database.db.moderators.delete_one({"user_id":int(parts[1])})
    await message.answer("Moderator removed.")

@router.message(Command("stats"))
async def stats(message: Message, settings: Settings, database):
    if not message.from_user or not await is_owner_or_moderator(database.db,message.from_user.id,settings): return
    total=await database.db.users.count_documents({})
    banned=await database.db.users.count_documents({"banned":True})
    files=await database.db.files.count_documents({})
    mods=await database.db.moderators.count_documents({})
    await message.answer(f"📊 Bot stats\nUsers tracked: {total}\nBanned users: {banned}\nStored file links: {files}\nModerators: {mods}\nBlocked/unreachable count cannot be known exactly until Telegram reports delivery failures.")

@router.message(Command("settings"))
async def settings_menu(message: Message, settings: Settings, database):
    if not message.from_user or not await is_owner_or_moderator(database.db,message.from_user.id,settings): return
    await message.answer("Settings: use /setstart on|off, /setinvalid on|off, /setautodelete on|off, /setautodeletemin MINUTES, /setafterdelete on|off, /setnotice TEXT, /setinvalidtext TEXT, /setshortener URL TOKEN")
