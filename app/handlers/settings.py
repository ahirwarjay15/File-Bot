"""Owner/moderator configuration commands; settings are persisted in MongoDB."""
from urllib.parse import urlparse
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from app.config import Settings
from app.services.permissions import is_owner_or_moderator
router=Router(name="settings")
AUTO_DELETE_MINUTES=(2,5,15,30,60,180,360,720,1440)

async def allowed(m,settings,database):
    return bool(m.from_user and await is_owner_or_moderator(database.db,m.from_user.id,settings))

async def patch(db,key,values,defaults=None):
    update={"$set":{"key":key,**values}}
    if defaults:update["$setOnInsert"]=defaults
    await db.settings.update_one({"key":key},update,upsert=True)

@router.message(Command("settings"))
async def menu(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database):return
    await m.answer("Settings:\n/setstart on|off\n/setstarttext TEXT\n/setinvalid on|off\n/setinvalidtext TEXT\n/setinvalidbutton TEXT URL\n/setinvalidabout on|off\n/setinvalidabouttext TEXT\n/setautodelete on|off\n/setautodeletemin 2|5|15|30|60|180|360|720|1440\n/setnotice TEXT\n/setafterdelete on|off\n/setafterdeletetext TEXT\n/setafterdeletebutton TEXT\n/setshortener API_URL API_TOKEN")

@router.message(Command("setstart"))
async def setstart(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database):return
    p=(m.text or "").split(maxsplit=1)
    if len(p)!=2 or p[1].lower() not in ("on","off"):await m.answer("Usage: /setstart on|off");return
    await patch(database.db,"start_message",{"enabled":p[1].lower()=="on"},{"text":"👋 Welcome! Send a valid file link to receive your file."})
    await m.answer("Start message setting updated.")

@router.message(Command("setstarttext"))
async def setstarttext(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database):return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2:await m.answer("Usage: /setstarttext TEXT");return
    await patch(database.db,"start_message",{"text":p[1]},{"enabled":True})
    await m.answer("Start message text updated.")

@router.message(Command("setinvalid"))
async def setinvalid(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database):return
    p=(m.text or "").split(maxsplit=1)
    if len(p)!=2 or p[1].lower() not in ("on","off"):await m.answer("Usage: /setinvalid on|off");return
    await patch(database.db,"invalid_post",{"enabled":p[1].lower()=="on"},{"text":"Hi {mention}, this bot is used to deliver files. Please use a valid file link."})
    await m.answer("Invalid-post setting updated.")

@router.message(Command("setinvalidtext"))
async def setinvalidtext(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database):return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2:await m.answer("Usage: /setinvalidtext TEXT");return
    await patch(database.db,"invalid_post",{"text":p[1],"enabled":True},{"about_enabled":False})
    await m.answer("Invalid-post text updated.")

@router.message(Command("setinvalidbutton"))
async def setinvalidbutton(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database):return
    p=(m.text or "").split(maxsplit=2)
    if len(p)!=3:await m.answer("Usage: /setinvalidbutton BUTTON_TEXT https://example.com");return
    parsed=urlparse(p[2])
    if parsed.scheme not in ("https","http") or not parsed.netloc:await m.answer("Button URL must be a valid http/https URL.");return
    await patch(database.db,"invalid_post",{"button_text":p[1],"button_url":p[2]},{"enabled":False})
    await m.answer("Invalid-post button updated.")

@router.message(Command("setinvalidabout"))
async def setinvalidabout(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database):return
    p=(m.text or "").split(maxsplit=1)
    if len(p)!=2 or p[1].lower() not in ("on","off"):await m.answer("Usage: /setinvalidabout on|off");return
    await patch(database.db,"invalid_post",{"about_enabled":p[1].lower()=="on"},{"enabled":False})
    await m.answer("Invalid About button updated.")

@router.message(Command("setinvalidabouttext"))
async def setinvalidabouttext(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database):return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2:await m.answer("Usage: /setinvalidabouttext TEXT");return
    await patch(database.db,"invalid_post",{"about_text":p[1]},{"enabled":False,"about_enabled":True})
    await m.answer("Invalid About text updated.")

@router.message(Command("setautodelete"))
async def setautodelete(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database):return
    p=(m.text or "").split(maxsplit=1)
    if len(p)!=2 or p[1].lower() not in ("on","off"):await m.answer("Usage: /setautodelete on|off");return
    await patch(database.db,"auto_delete",{"enabled":p[1].lower()=="on"},{"minutes":30,"notice":"Your files will be automatically deleted after 30 minutes."})
    await m.answer("Auto Delete setting updated. Only delivered file messages and the auto-delete notice are affected.")

@router.message(Command("setautodeletemin"))
async def setautodeletemin(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database):return
    p=(m.text or "").split()
    if len(p)!=2 or not p[1].isdigit() or int(p[1]) not in AUTO_DELETE_MINUTES:
        await m.answer("Choose one: 2, 5, 15, 30, 60, 180, 360, 720, or 1440 minutes.");return
    await patch(database.db,"auto_delete",{"minutes":int(p[1])},{"enabled":False,"notice":"Your files will be automatically deleted after 30 minutes."})
    await m.answer(f"Auto-delete time changed to {p[1]} minutes.")

@router.message(Command("setnotice"))
async def setnotice(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database):return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2:await m.answer("Usage: /setnotice TEXT");return
    await patch(database.db,"auto_delete",{"notice":p[1]},{"enabled":False,"minutes":30})
    await m.answer("Auto-delete message updated.")

@router.message(Command("setafterdelete"))
async def setafterdelete(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database):return
    p=(m.text or "").split(maxsplit=1)
    if len(p)!=2 or p[1].lower() not in ("on","off"):await m.answer("Usage: /setafterdelete on|off");return
    await patch(database.db,"after_delete",{"enabled":p[1].lower()=="on"},{"text":"Your Video / File Is Successfully Deleted.","button_text":"Get your files again"})
    await m.answer("After Delete setting updated. It only runs when Auto Delete is enabled.")

@router.message(Command("setafterdeletetext"))
async def setafterdeletetext(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database):return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2:await m.answer("Usage: /setafterdeletetext TEXT");return
    await patch(database.db,"after_delete",{"text":p[1]},{"enabled":False,"button_text":"Get your files again"})
    await m.answer("After-delete text updated.")

@router.message(Command("setafterdeletebutton"))
async def setafterdeletebutton(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database):return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2:await m.answer("Usage: /setafterdeletebutton BUTTON_TEXT");return
    await patch(database.db,"after_delete",{"button_text":p[1]},{"enabled":False,"text":"Your Video / File Is Successfully Deleted."})
    await m.answer("After-delete button text updated.")

@router.message(Command("setshortener"))
async def setshortener(m:Message,settings:Settings,database):
    if not await allowed(m,settings,database):return
    p=(m.text or "").split(maxsplit=2)
    if len(p)!=3:await m.answer("Usage: /setshortener API_URL API_TOKEN");return
    parsed=urlparse(p[1])
    if parsed.scheme not in ("https","http") or not parsed.netloc:await m.answer("API URL must be a valid http/https URL.");return
    await patch(database.db,"shortener",{"enabled":True,"url":p[1],"token":p[2]})
    host=parsed.netloc
    await m.answer(f"Shortener provider configured: {host}. API token is stored privately and will not be displayed.")
