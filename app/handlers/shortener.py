"""Manual URL shortening through the configured provider adapter."""
import re
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CopyTextButton
from app.config import Settings
from app.services.permissions import is_owner_or_moderator
from app.services.links import shorten_url

router = Router(name="shortener")

@router.message(Command("shortener"))
async def shortener_command(message: Message, settings: Settings, database):
    if not message.from_user or not await is_owner_or_moderator(database.db, message.from_user.id, settings):
        return
    cfg = await database.db.settings.find_one({"key": "shortener", "enabled": True})
    if not cfg:
        await message.answer("Shortener isn't configured. Open /settings → Link Shortener → ADD.")
        return
    source = (message.text or "").partition(" ")[2].strip()
    if not source and message.reply_to_message:
        source = message.reply_to_message.text or message.reply_to_message.caption or ""
    urls = re.findall(r"https?://[^\s<>]+", source)
    if not urls:
        await message.answer("Usage: /shortener https://example.com — or reply to a message containing a URL with /shortener.")
        return
    target = urls[0].rstrip(").,;]")
    try:
        result = await shorten_url(cfg["url"], cfg["token"], target)
        await message.answer(result, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="ᴄᴏᴘʏ", copy_text=CopyTextButton(text=result))
        ]]))
    except Exception as exc:
        await message.answer(f"Shortener request failed: {type(exc).__name__}. Check provider API settings.")
