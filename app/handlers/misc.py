"""Invalid-post response and in-place About view for ordinary user messages."""
from html import escape
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError
from app.config import Settings
from app.services.permissions import is_owner_or_moderator, is_banned
from app.database.files import FileRepository

router = Router(name="misc")
DEFAULT_INVALID = "Hi {mention}, this bot is used to deliver files. Please use a valid file link."
DEFAULT_ABOUT = (
    "✨ ᴀʙᴏᴜᴛ ᴍᴇ\n\n"
    "✰ ᴍʏ ɴᴀᴍᴇ: {bot_name}\n\n"
    "✰ creator: Lexi\n\n"
    "✰ ᴍʏ ᴏᴡɴᴇʀ: Lexi\n\n"
    "✰ made for: Lexi Anime\n\n"
    "✰ ᴠᴇʀsɪᴏɴ: [V 0.1]"
)


def _mention(user):
    return f'<a href="tg://user?id={user.id}">{escape(user.first_name or "there")}</a>'


def _render_user_text(raw, user, bot):
    text = str(raw or DEFAULT_INVALID)
    username = getattr(bot, "username", None)
    bot_name = escape(getattr(bot, "full_name", None) or getattr(bot, "first_name", None) or "Bot")
    bot_mention = f'<a href="https://t.me/{escape(username)}">{bot_name}</a>' if username else bot_name
    values = {
        "{bot_mention}": bot_mention,
        "{bot}": bot_mention,
        "{user_mention}": _mention(user),
        "{user}": _mention(user),
        "{first_name}": escape(user.first_name or ""),
        "{last_name}": escape(user.last_name or ""),
        "{owner}": '<a href="https://t.me/lexxiowner">Lexi</a>',
        "{anime}": '<a href="https://t.me/lexianime">Lexi Anime</a>',
        "{hindi_anime}": '<a href="https://t.me/lexianimehindi">Lexi Anime</a>',
        "{mention}": _mention(user),
    }
    for token, replacement in values.items():
        text = text.replace(token, replacement)
    return text


def _about_markup():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="《 BACK", callback_data="invalid:about_back")
    ]])


def _invalid_markup(cfg):
    rows = []
    if cfg.get("button_text") and cfg.get("button_url"):
        rows.append([InlineKeyboardButton(text=cfg["button_text"], url=cfg["button_url"])])
    if cfg.get("about_enabled"):
        rows.append([InlineKeyboardButton(
            text=cfg.get("about_button_text", "ᴀʙᴏᴜᴛ"), callback_data="invalid:about"
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def _edit_same_post(message, text, markup):
    try:
        if message.photo or message.animation:
            await message.edit_caption(caption=text, parse_mode="HTML", reply_markup=markup)
        else:
            await message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except TelegramAPIError:
        # The callback still acknowledges; an inaccessible/stale post is not recreated
        # because the blueprint requires About to edit the original post in place.
        return


@router.message()
async def invalid_post(message: Message, settings: Settings, database):
    user = message.from_user
    if not user or (message.text and message.text.startswith("/")):
        return
    await FileRepository(database.db).save_user(user)
    if await is_banned(database.db, user.id) or await is_owner_or_moderator(database.db, user.id, settings):
        return
    cfg = await database.db.settings.find_one({"key": "invalid_post", "enabled": True})
    if not cfg:
        return
    me = await message.bot.get_me()\n    text = _render_user_text(cfg.get("text") or DEFAULT_INVALID, user, me)
    markup = _invalid_markup(cfg)
    try:
        if cfg.get("poster_file_id"):
            await message.answer_animation(cfg["poster_file_id"], caption=text, parse_mode="HTML", reply_markup=markup)
        elif cfg.get("poster_photo_id"):
            await message.answer_photo(cfg["poster_photo_id"], caption=text, parse_mode="HTML", reply_markup=markup)
        else:
            await message.answer(text, parse_mode="HTML", reply_markup=markup)
    except TelegramAPIError:
        # A stale optional poster should not disable the invalid-post response.
        try:
            await message.answer(text, parse_mode="HTML", reply_markup=markup)
        except TelegramAPIError:
            return


@router.callback_query(F.data == "invalid:about")
async def invalid_about(query: CallbackQuery, database, bot):
    await query.answer()
    user, message = query.from_user, query.message
    if not user or not message or await is_banned(database.db, user.id):
        return
    cfg = await database.db.settings.find_one({"key": "invalid_post"}) or {}
    if not cfg.get("about_enabled", False):
        return
    me = await bot.get_me()
    raw = cfg.get("about_text") or DEFAULT_ABOUT
    rendered = str(raw).replace("{bot_name}", escape(me.full_name))
    rendered = rendered.replace("Lexi Anime", "__LEXI_ANIME_LINK__")
    rendered = rendered.replace("Lexi", '<a href="https://t.me/lexxiowner">Lexi</a>')
    rendered = rendered.replace("__LEXI_ANIME_LINK__", '<a href="https://t.me/lexiAnime">Lexi Anime</a>')
    await _edit_same_post(message, rendered, _about_markup())


@router.callback_query(F.data == "invalid:about_back")
async def invalid_about_back(query: CallbackQuery, settings: Settings, database):
    await query.answer()
    user, message = query.from_user, query.message
    if not user or not message or await is_banned(database.db, user.id):
        return
    if await is_owner_or_moderator(database.db, user.id, settings):
        return
    cfg = await database.db.settings.find_one({"key": "invalid_post", "enabled": True})
    if not cfg:
        return
    await _edit_same_post(message, _render_user_text(cfg.get("text") or DEFAULT_INVALID, user), _invalid_markup(cfg))
