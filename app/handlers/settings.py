from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from app.config import Settings
from app.services.permissions import is_owner_or_moderator

router=Router(name="settings")

async def authorized(message, settings, database):
    return bool(message.from_user and await is_owner_or_moderator(database.db,message.from_user.id,settings))

async def setval(db,key,value):
    await db.settings.update_one({"key":key},{"$set":{"key":key,"value":value}},upsert=True)

@router.message(Command("setstart"))
async def setstart(m:Message,settings:Settings,database):
    if not await authorized(m,settings,database): return
    p=(m.text or "").split(maxsplit=1); enabled=len(p)>1 and p[1].lower()=="on"
    await setval(database.db,"start_message",{"enabled":enabled,"text":"Welcome! Send a file link to receive your file."})
    await m.answer(f"Start message {'enabled' if enabled else 'disabled'}.")

@router.message(Command("setstarttext"))
async def setstarttext(m:Message,settings:Settings,database):
    if not await authorized(m,settings,database): return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2: await m.answer("Usage: /setstarttext YOUR MESSAGE"); return
    current=await database.db.settings.find_one({"key":"start_message"}) or {"enabled":True}
    current.update({"key":"start_message","text":p[1]})
    await database.db.settings.update_one({"key":"start_message"},{"$set":current},upsert=True)
    await m.answer("Start message updated.")

@router.message(Command("setinvalid"))
async def setinvalid(m:Message,settings:Settings,database):
    if not await authorized(m,settings,database): return
    p=(m.text or "").split(maxsplit=1); enabled=len(p)>1 and p[1].lower()=="on"
    await setval(database.db,"invalid_post",{"enabled":enabled,"text":"This post is not a valid file link."})
    await m.answer(f"Invalid-post response {'enabled' if enabled else 'disabled'}.")

@router.message(Command("setinvalidtext"))
async def setinvalidtext(m:Message,settings:Settings,database):
    if not await authorized(m,settings,database): return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2: await m.answer("Usage: /setinvalidtext YOUR MESSAGE"); return
    cur=await database.db.settings.find_one({"key":"invalid_post"}) or {"enabled":True}
    cur.update({"key":"invalid_post","text":p[1]})
    await database.db.settings.update_one({"key":"invalid_post"},{"$set":cur},upsert=True)
    await m.answer("Invalid-post message updated.")

@router.message(Command("setautodelete"))
async def setautodelete(m:Message,settings:Settings,database):
    if not await authorized(m,settings,database): return
    p=(m.text or "").split(maxsplit=1); enabled=len(p)>1 and p[1].lower()=="on"
    cur=await database.db.settings.find_one({"key":"auto_delete"}) or {"minutes":30,"notice":"⏳ This file will be deleted automatically."}
    cur.update({"key":"auto_delete","enabled":enabled})
    await database.db.settings.update_one({"key":"auto_delete"},{"$set":cur},upsert=True)
    await m.answer(f"Auto Delete {'enabled' if enabled else 'disabled'}.")

@router.message(Command("setautodeletemin"))
async def setautodeletemin(m:Message,settings:Settings,database):
    if not await authorized(m,settings,database): return
    p=(m.text or "").split()
    if len(p)!=2 or not p[1].isdigit() or not 1<=int(p[1])<=10080: await m.answer("Usage: /setautodeletemin MINUTES (1–10080)"); return
    cur=await database.db.settings.find_one({"key":"auto_delete"}) or {"enabled":False,"notice":"⏳ This file will be deleted automatically."}
    cur.update({"key":"auto_delete","minutes":int(p[1])})
    await database.db.settings.update_one({"key":"auto_delete"},{"$set":cur},upsert=True)
    await m.answer(f"Auto-delete timer set to {p[1]} minutes.")

@router.message(Command("setafterdelete"))
async def setafterdelete(m:Message,settings:Settings,database):
    if not await authorized(m,settings,database): return
    p=(m.text or "").split(maxsplit=1); enabled=len(p)>1 and p[1].lower()=="on"
    await setval(database.db,"after_delete",{"enabled":enabled,"text":"File expired. Open the original link to request it again."})
    await m.answer(f"After Delete {'enabled' if enabled else 'disabled'}.")

@router.message(Command("setnotice"))
async def setnotice(m:Message,settings:Settings,database):
    if not await authorized(m,settings,database): return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2: await m.answer("Usage: /setnotice MESSAGE"); return
    cur=await database.db.settings.find_one({"key":"auto_delete"}) or {"enabled":False,"minutes":30}
    cur.update({"key":"auto_delete","notice":p[1]})
    await database.db.settings.update_one({"key":"auto_delete"},{"$set":cur},upsert=True)
    await m.answer("Auto-delete notice updated.")

@router.message(Command("setshortener"))
async def setshortener(m:Message,settings:Settings,database):
    if not await authorized(m,settings,database): return
    p=(m.text or "").split(maxsplit=2)
    if len(p)!=3: await m.answer("Usage: /setshortener API_URL API_TOKEN"); return
    await setval(database.db,"shortener",{"enabled":True,"url":p[1],"token":p[2]})
    await m.answer("Shortener configured. Provider response format must include short_url, shortenedUrl or shortlink.")
