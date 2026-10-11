"""Invalid-post response for ordinary user messages only."""
from html import escape
from aiogram import Router
from aiogram.types import Message,InlineKeyboardMarkup,InlineKeyboardButton
from app.config import Settings
from app.services.permissions import is_owner_or_moderator,is_banned
from app.database.files import FileRepository
router=Router(name="misc")

@router.message()
async def invalid_post(message:Message,settings:Settings,database):
    user=message.from_user
    if not user or (message.text and message.text.startswith("/")):return
    await FileRepository(database.db).save_user(user)
    if await is_banned(database.db,user.id) or await is_owner_or_moderator(database.db,user.id,settings):return
    cfg=await database.db.settings.find_one({"key":"invalid_post","enabled":True})
    if not cfg:return
    text=cfg.get("text") or "Hi {mention}, this bot is used to deliver files. Please use a valid file link."
    mention=f'<a href="tg://user?id={user.id}">{escape(user.first_name or "there")}</a>'
    text=text.replace("{first_name}",escape(user.first_name or "")).replace("{last_name}",escape(user.last_name or "")).replace("{mention}",mention)
    rows=[]
    if cfg.get("button_text") and cfg.get("button_url"):
        rows.append([InlineKeyboardButton(text=cfg["button_text"],url=cfg["button_url"])])
    if cfg.get("about_enabled"):
        rows.append([InlineKeyboardButton(text=cfg.get("about_button_text","About"),callback_data="invalid:about")])
    try:
        if cfg.get("poster_file_id"):
            await message.answer_animation(cfg["poster_file_id"],caption=text,reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None)
        elif cfg.get("poster_photo_id"):
            await message.answer_photo(cfg["poster_photo_id"],caption=text,reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None)
        else:
            await message.answer(text,reply_markup=InlineKeyboardMarkup(inline_keyboard=rows) if rows else None)
    except Exception:
        # Fall back to plain text if a stale poster ID or invalid optional button is configured.
        await message.answer(text)
