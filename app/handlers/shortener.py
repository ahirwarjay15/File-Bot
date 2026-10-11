from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from app.config import Settings
from app.services.permissions import is_owner_or_moderator
from app.services.links import shorten_url

router=Router(name="shortener")

@router.message(Command("shortener"))
async def shortener_command(message:Message,settings:Settings,database):
    if not message.from_user or not await is_owner_or_moderator(database.db,message.from_user.id,settings): return
    cfg=await database.db.settings.find_one({"key":"shortener","enabled":True})
    if not cfg:
        await message.answer("Shortener isn't configured. Use /setshortener API_URL API_TOKEN.")
        return
    if not message.reply_to_message or not message.reply_to_message.text:
        await message.answer("Reply to a message containing a URL with /shortener.")
        return
    import re
    urls=re.findall(r"https?://\S+",message.reply_to_message.text)
    if not urls:
        await message.answer("No http/https URL found in the replied message.")
        return
    try:
        result=await shorten_url(cfg["url"],cfg["token"],urls[0].rstrip(").,"))
        await message.answer(result)
    except Exception as exc:
        await message.answer(f"Shortener request failed: {type(exc).__name__}. Check provider API settings.")
