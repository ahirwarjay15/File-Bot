"""Moderator settings commands. Values are stored as top-level fields per setting."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from app.config import Settings
from app.services.permissions import is_owner_or_moderator

router=Router(name="settings")

async def allowed(m,settings,database):
    return bool(m.from_user and await is_owner_or_moderator(database.db,m.from_user.id,settings))

@router.message(Command("settings"))
async def menu(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database): return
    await m.answer("Settings commands:\n/setstart on|off\n/setstarttext TEXT\n/setinvalid on|off\n/setinvalidtext TEXT\n/setautodelete on|off\n/setautodeletemin MINUTES\n/setafterdelete on|off\n/setnotice TEXT\n/setshortener API_URL API_TOKEN")

@router.message(Command("setstart"))
async def setstart(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database): return
    p=(m.text or "").split(maxsplit=1); enabled=len(p)>1 and p[1].lower()=="on"
    await database.db.settings.update_one({"key":"start_message"},{"$set":{"key":"start_message","enabled":enabled}},upsert=True)
    await m.answer(f"Start message {'enabled' if enabled else 'disabled'}.")

@router.message(Command("setstarttext"))
async def setstarttext(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database): return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2: await m.answer("Usage: /setstarttext TEXT"); return
    await database.db.settings.update_one({"key":"start_message"},{"$set":{"key":"start_message","text":p[1]},"$setOnInsert":{"enabled":True}},upsert=True)
    await m.answer("Start message updated.")

@router.message(Command("setinvalid"))
async def setinvalid(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database): return
    p=(m.text or "").split(maxsplit=1); enabled=len(p)>1 and p[1].lower()=="on"
    await database.db.settings.update_one({"key":"invalid_post"},{"$set":{"key":"invalid_post","enabled":enabled}},upsert=True)
    await m.answer(f"Invalid-post response {'enabled' if enabled else 'disabled'}.")

@router.message(Command("setinvalidtext"))
async def setinvalidtext(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database): return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2: await m.answer("Usage: /setinvalidtext TEXT"); return
    await database.db.settings.update_one({"key":"invalid_post"},{"$set":{"key":"invalid_post","text":p[1],"enabled":True}},upsert=True)
    await m.answer("Invalid-post text updated and enabled.")

@router.message(Command("setautodelete"))
async def setautodelete(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database): return
    p=(m.text or "").split(maxsplit=1); enabled=len(p)>1 and p[1].lower()=="on"
    await database.db.settings.update_one({"key":"auto_delete"},{"$set":{"key":"auto_delete","enabled":enabled},"$setOnInsert":{"minutes":30,"notice":"⏳ This file will be deleted automatically."}},upsert=True)
    await m.answer(f"Auto Delete {'enabled' if enabled else 'disabled'}. Source-channel originals are never deleted.")

@router.message(Command("setautodeletemin"))
async def setautodeletemin(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database): return
    p=(m.text or "").split()
    if len(p)!=2 or not p[1].isdigit() or not 1<=int(p[1])<=10080:
        await m.answer("Usage: /setautodeletemin MINUTES (1–10080)"); return
    await database.db.settings.update_one({"key":"auto_delete"},{"$set":{"key":"auto_delete","minutes":int(p[1])},"$setOnInsert":{"enabled":False}},upsert=True)
    await m.answer("Auto-delete timer updated.")

@router.message(Command("setafterdelete"))
async def setafterdelete(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database): return
    p=(m.text or "").split(maxsplit=1); enabled=len(p)>1 and p[1].lower()=="on"
    await database.db.settings.update_one({"key":"after_delete"},{"$set":{"key":"after_delete","enabled":enabled,"text":"File expired. Use the original link to request it again."}},upsert=True)
    await m.answer(f"After Delete {'enabled' if enabled else 'disabled'}. It only runs after Auto Delete.")

@router.message(Command("setnotice"))
async def setnotice(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database): return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2: await m.answer("Usage: /setnotice TEXT"); return
    await database.db.settings.update_one({"key":"auto_delete"},{"$set":{"key":"auto_delete","notice":p[1]},"$setOnInsert":{"enabled":False,"minutes":30}},upsert=True)
    await m.answer("Auto-delete notice updated.")

@router.message(Command("setshortener"))
async def setshortener(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database): return
    p=(m.text or "").split(maxsplit=2)
    if len(p)!=3: await m.answer("Usage: /setshortener API_URL API_TOKEN"); return
    await database.db.settings.update_one({"key":"shortener"},{"$set":{"key":"shortener","enabled":True,"url":p[1],"token":p[2]}},upsert=True)
    await m.answer("Shortener configured. Provider must accept JSON url/token and return short_url, shortenedUrl, or shortlink.")
