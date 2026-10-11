"""Blueprint-aligned inline settings pages with persistent MongoDB values."""
from urllib.parse import urlparse
from datetime import datetime, timezone
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError
from aiogram.dispatcher.event.bases import SkipHandler
from app.config import Settings
from app.services.permissions import is_owner_or_moderator
from app.services.links import shorten_url
from app.handlers.start import effective_force_join_channels

router = Router(name="settings")
def unicode_buttons(value: str) -> str:
    table = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ")
    return "".join(ch.translate(table) if ch.isascii() and ch.isalpha() else ch for ch in str(value))
AUTO_DELETE_MINUTES = (2, 5, 15, 30, 60, 180, 360, 720, 1440)
DEFAULT_NOTICE = "Your files will be automatically deleted after {auto_delete_time}."
DEFAULT_START_TEXT = "Hey {mention} ✨Welcome to the fastest and most secure file store bot!\n\nBy: Lexi Anime\n\nDeveloper: Lexi"
DEFAULT_AFTER_TEXT = "Yᴏᴜʀ Vɪᴅᴇᴏ / Fɪʟᴇ Iꜱ Sᴜᴄᴄᴇꜱꜱꜰᴜʟʟʏ Dᴇʟᴇᴛᴇᴅ ✅"
DEFAULT_AFTER_BUTTON = "Gᴇᴛ ʏᴏᴜʀ ꜰɪʟᴇꜱ ᴀɢᴀɪɴ"
DEFAULT_INVALID = "Hi {mention}, this bot is used to deliver files. Please use a valid file link."

class SettingInput(StatesGroup):
    waiting = State()

async def allowed(m, settings, database):
    return bool(m.from_user and await is_owner_or_moderator(database.db, m.from_user.id, settings))

async def patch(db, key, values, defaults=None):
    update = {"$set": {"key": key, **values}}
    if defaults:
        update["$setOnInsert"] = defaults
    await db.settings.update_one({"key": key}, update, upsert=True)

def time_label(minutes: int) -> str:
    return f"{minutes // 60}h" if minutes >= 60 else f"{minutes}m"

def time_words(minutes: int) -> str:
    if minutes >= 60 and minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    return f"{minutes} minutes"

def kb(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=unicode_buttons(label), callback_data=data) for label, data in row]
        for row in rows
    ])

async def edit_page(query, text, keyboard):
    if not query.message:
        return
    try:
        await query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except TelegramAPIError:
        await query.message.answer(text, reply_markup=keyboard, parse_mode="HTML")

async def render_home(query):
    name = query.from_user.mention_html() if query.from_user else "User"
    await edit_page(query, f"<b><u>C̲U̲S̲T̲O̲M̲I̲Z̲E̲</u></b>\n\nName: {name}\n\n<i>Configure Your Bot Settings Using the Buttons Below.</i>", kb([
        [("START MSG", "settings:start"), ("FORCE JOIN", "settings:forcejoin")],
        [("ANIMATION", "settings:forcejoin_animation"), ("AUTO DELETE", "settings:auto")],
        [("INVALID", "settings:invalid"), ("SHORTENER", "settings:shortener")],
        [("MODERATORS", "settings:mods"), ("STATS", "settings:stats")],
        [("《 BACK", "settings:home_back")],
    ]))

async def render_forcejoin(query, db, settings):
    channels = await effective_force_join_channels(type("DatabaseView", (), {"db": db})(), settings)
    cfg = await db.settings.find_one({"key": "force_join"}) or {}
    other_links = cfg.get("other_links", []) if isinstance(cfg.get("other_links", []), list) else []
    rows = []
    for i, channel in enumerate(channels[:10]):
        cfg = await db.settings.find_one({"key": "force_join_channel", "channel": channel}) or {}
        label = cfg.get("button_text") or f"Join {i + 1}"
        rows.append([(label, f"settings:forcejoin_channel:{i}")])
    for i, item in enumerate(other_links[:10]):
        rows.append([(item.get("button_text") or f"Join {len(channels)+i+1}", f"settings:forcejoin_other_settings:{i}")])
    if len(channels) + len(other_links) < 10:
        rows.append([("✚ ADD", "settings:forcejoin_add")])
    rows.extend([
        [("FORCE JOIN MESSAGE", "settings:forcejoin_message"), ("FORCE JOIN MEDIA", "settings:forcejoin_media")],
        [("VERIFY", "settings:forcejoin_verify_text")],
        [("《 BACK", "settings:home")],
    ])
    text = ("F̲O̲R̲C̲E̲ ̲J̲O̲I̲N̲\n\nUsers must verify the required Join Request channels before receiving files.\n\n"
            "Join Request channels accept membership or a pending join request.\n\n"
            "Other links are treated as verified when all required Join Request channels are verified.\n\n"
            "You can add up to 10 force-join channels.")
    await edit_page(query, text, kb(rows))

async def render_start(query, db):
    cfg = await db.settings.find_one({"key": "start_message"}) or {}
    await edit_page(query, f"S̲T̲A̲R̲T̲ ̲M̲E̲S̲S̲A̲G̲E̲\n\nCustomize your bot's start message using the following options.\n\nStatus: {'ENABLED' if cfg.get('enabled', True) else 'DISABLED'}", kb([
        [("DISABLE / ENABLE", "settings:start_toggle")],
        [("BUTTON", "settings:start_button"), ("START TEXT", "settings:start_text")],
        [("START POSTER", "settings:start_poster"), ("ABOUT BUTTON", "settings:start_about")],
        [("BACK", "settings:home")],
    ]))

async def render_start_text(query):
    await edit_page(query, "S̲T̲A̲R̲T̲ ̲T̲E̲X̲T̲\n\nCustomize your bot's start message.", kb([
        [("EDIT", "settings:start_text_edit"), ("SEE", "settings:start_text_see")],
        [("DEFAULT", "settings:start_text_default")],
        [("BACK", "settings:start")],
    ]))

async def render_start_button(query):
    await edit_page(query, "S̲T̲A̲R̲T̲ ̲B̲U̲T̲T̲O̲N̲\n\nCustomize the button shown with your start message.", kb([
        [("BUTTON TEXT", "settings:start_button_text"), ("BUTTON LINK", "settings:start_button_link")],
        [("BACK", "settings:start")],
    ]))

async def render_start_poster(query):
    await edit_page(query, "S̲T̲A̲R̲T̲ ̲M̲E̲D̲I̲A̲\n\nInclude an image or GIF with your start message.", kb([
        [("ADD", "settings:start_poster_add"), ("REMOVE", "settings:start_poster_remove")],
        [("BACK", "settings:start")],
    ]))

async def render_animation(query, db):
    cfg = await db.settings.find_one({"key": "animation"}) or {}
    await edit_page(query, f"<b><u>A̲N̲I̲M̲A̲T̲I̲O̲N̲</u></b>\\n\\n<i>Add a custom animation for the verification process.</i>\\n\\nPrefix: {cfg.get('prefix', 'Checking..')}\\nFrames: {'3 configured' if len(cfg.get('frames', [])) == 3 else 'Not configured'}\\nSupported speed: 0.10 to 1.00 seconds per frame.\\nStatus: {'ENABLED' if cfg.get('enabled', False) else 'DISABLED'}", kb([
        [("PREFIX", "settings:animation_prefix"), ("FRAMES", "settings:animation_frames")],
        [("ENABLE / DISABLE", "settings:animation_toggle"), ("SPEED", "settings:animation_speed")],
        [("MODE", "settings:animation_mode")],
        [("《 BACK", "settings:home")],
    ]))

async def render_auto(query, db):
    cfg = await db.settings.find_one({"key": "auto_delete"}) or {}
    after = await db.settings.find_one({"key": "after_delete"}) or {}
    minutes = int(cfg.get("minutes", 30))
    status = "ENABLED" if cfg.get("enabled", False) else "DISABLED"
    after_status = "ENABLED" if after.get("enabled", False) and cfg.get("enabled", False) else "DISABLED"
    await edit_page(query, f"AUTO DELETE\nAutomatically delete delivered files and the auto-delete message after {time_label(minutes)}.\nStatus: {status}", kb([
        [("ENABLE / DISABLE", "settings:auto_toggle")],
        [("TIME", "settings:auto_time"), ("MESSAGE", "settings:auto_message")],
        [(f"AFTER DELETE ({after_status})", "settings:after")],
        [("BACK", "settings:home")],
    ]))

async def render_auto_time(query, db):
    cfg = await db.settings.find_one({"key": "auto_delete"}) or {}
    minutes = int(cfg.get("minutes", 30))
    label = time_label(minutes)
    await edit_page(query, f"AUTO DELETE TIME\nCurrent time: {label}\nTap below to change the auto-delete time.", kb([
        [("CHANGE TIME", "settings:auto_time_change")],
        [("BACK", "settings:auto")],
    ]))

async def render_auto_message(query, db):
    cfg = await db.settings.find_one({"key": "auto_delete"}) or {}
    await edit_page(query, "AUTO DELETE MESSAGE\nCustomize the message sent after file delivery.", kb([
        [("EDIT", "settings:auto_message_edit"), ("SEE", "settings:auto_message_see")],
        [("DEFAULT", "settings:auto_message_default")],
        [("BACK", "settings:auto")],
    ]))

async def render_after(query, db):
    auto = await db.settings.find_one({"key": "auto_delete"}) or {}
    after = await db.settings.find_one({"key": "after_delete"}) or {}
    enabled = bool(after.get("enabled", False) and auto.get("enabled", False))
    await edit_page(query, f"AFTER DELETE\nCustomize the message and button shown after delivered files are deleted.\nStatus: {'ENABLED' if enabled else 'DISABLED'}", kb([
        [("ENABLE / DISABLE", "settings:after_toggle")],
        [("TEXT", "settings:after_text")],
        [("BACK", "settings:auto")],
    ]))

async def render_after_text(query):
    await edit_page(query, "AFTER DELETE TEXT\nCustomize the message and button text shown after file deletion.", kb([
        [("MESSAGE TEXT", "settings:after_text_message")],
        [("BUTTON TEXT", "settings:after_text_button")],
        [("BACK", "settings:after")],
    ]))

async def render_invalid(query, db):
    cfg = await db.settings.find_one({"key": "invalid_post"}) or {}
    await edit_page(query, f"INVALID POST\nSet a response for users who send normal messages to the bot.\nStatus: {'ENABLED' if cfg.get('enabled', False) else 'DISABLED'}", kb([
        [("ENABLE / DISABLE", "settings:invalid_toggle")],
        [("TEXT", "settings:invalid_text"), ("BUTTON", "settings:invalid_button")],
        [("POSTER", "settings:invalid_poster"), ("ABOUT BUTTON", "settings:invalid_about")],
        [("BACK", "settings:home")],
    ]))

async def render_invalid_button(query):
    await edit_page(query, "INVALID BUTTON\nSelect an option below.", kb([
        [("BUTTON TEXT", "settings:invalid_button_text")],
        [("BUTTON LINK", "settings:invalid_button_link")],
        [("BACK", "settings:invalid")],
    ]))

async def render_poster(query):
    await edit_page(query, "INVALID POSTER\nAdd an image or GIF to your invalid post.", kb([
        [("ADD", "settings:poster_add"), ("REMOVE", "settings:poster_remove")],
        [("BACK", "settings:invalid")],
    ]))

async def render_about(query, db):
    cfg = await db.settings.find_one({"key": "invalid_post"}) or {}
    await edit_page(query, f"A̲B̲O̲U̲T̲ ̲B̲U̲T̲T̲O̲N̲\\n\\nChoose whether to show the About button with invalid posts.\\n\\nStatus: {'ENABLED' if cfg.get('about_enabled', False) else 'DISABLED'}", kb([
        [("ENABLE / DISABLE", "settings:invalid_about_toggle")],
        [("《 BACK", "settings:invalid")],
    ]))

async def render_shortener(query, db):
    cfg = await db.settings.find_one({"key": "shortener", "enabled": True})
    if not cfg:
        await edit_page(query, "LINK SHORTENER\nAdd a shortener provider to shorten links.", kb([
            [("✚ ADD", "settings:shortener_add")], [("BACK", "settings:home")],
        ]))
        return
    host = urlparse(cfg.get("url", "")).netloc or "Configured provider"
    token = cfg.get("token", "")
    masked = (token[:2] + "••••••" + token[-2:]) if len(token) > 4 else "••••••"
    await edit_page(query, f"LINK SHORTENER\nShortener: {host}\nShortener API: {masked}\nYou can now use /shortener to shorten links.", kb([
        [("REMOVE", "settings:shortener_remove")], [("BACK", "settings:home")],
    ]))

async def render_mods(query, db):
    mods = await db.moderators.find({}).sort("user_id", 1).to_list(length=3)
    lines = [f"• {m.get('first_name') or ('User ' + str(m['user_id']))} — {m['user_id']}" for m in mods]
    rows = []
    if len(mods) < 3:
        rows.append([("✚ ADD", "settings:mod_add")])
    if mods:
        rows.append([("REMOVE", "settings:mod_remove")])
    rows.append([("BACK", "settings:home")])
    await edit_page(query, "MODERATORS\nModerators can manage bot features, including broadcasting.\n\nModerators List\n" + ("\n".join(lines) if lines else "No moderators added."), kb(rows))

@router.message(Command("settings"))
async def settings_command(message: Message, settings: Settings, database):
    if not await allowed(message, settings, database):
        return
    name = message.from_user.mention_html() if message.from_user else "User"
    await message.answer(f"<b><u>C̲U̲S̲T̲O̲M̲I̲Z̲E̲</u></b>\n\nName: {name}\n\n<i>Configure Your Bot Settings Using the Buttons Below.</i>", parse_mode="HTML", reply_markup=kb([
        [("START MSG", "settings:start"), ("FORCE JOIN", "settings:forcejoin")],
        [("ANIMATION", "settings:forcejoin_animation"), ("AUTO DELETE", "settings:auto")],
        [("INVALID", "settings:invalid"), ("SHORTENER", "settings:shortener")],
        [("MODERATORS", "settings:mods"), ("STATS", "settings:stats")],
        [("《 BACK", "settings:home_back")],
    ]))

@router.callback_query(F.data.startswith("settings:"))
async def settings_callbacks(query: CallbackQuery, state: FSMContext, settings: Settings, database):
    if not query.from_user or not await is_owner_or_moderator(database.db, query.from_user.id, settings):
        await query.answer("Not authorized.", show_alert=True)
        return
    action = query.data.split(":", 1)[1]
    db = database.db
    # Navigation/back actions always cancel an outstanding input flow without
    # changing saved settings. Choice actions (SEE/DEFAULT, mode selection, etc.)
    # are intentionally excluded so their pending data can be used.
    if action in {"home", "home_back", "start", "start_text", "start_button", "start_poster", "start_about",
                  "auto", "auto_time", "auto_message", "after", "after_text", "invalid", "invalid_text",
                  "invalid_button", "invalid_poster", "invalid_about", "forcejoin", "forcejoin_add",
                  "forcejoin_message", "forcejoin_media", "forcejoin_animation", "animation_mode",
                  "mods", "shortener"}:
        await state.clear()
    if action in {"home", "home_back"}: await render_home(query)
    elif action == "forcejoin": await render_forcejoin(query, db, settings)
    elif action == "forcejoin_add":
        await edit_page(query, "A̲D̲D̲ ̲C̲H̲A̲N̲N̲E̲L̲\\n\\nSelect a verification mode.\\n\\nJoin Request: Verify membership or a pending join request.\\n\\nOther: Add an external platform link.", kb([
            [("OTHER", "settings:forcejoin_other"), ("JOIN REQUEST", "settings:forcejoin_join_request")],
            [("《 BACK", "settings:forcejoin")],
        ]))
    elif action == "forcejoin_other":
        await state.set_state(SettingInput.waiting); await state.update_data(field="forcejoin_other_url")
        if query.message: await query.message.answer("Send the link of any platform. Example: Facebook, Instagram or YouTube.")
    elif action.startswith("forcejoin_other_settings:"):
        cfg = await db.settings.find_one({"key": "force_join"}) or {}
        links = cfg.get("other_links", [])
        index = int(action.split(":", 1)[1])
        if 0 <= index < len(links):
            item = links[index]
            await edit_page(query, f"C̲H̲A̲N̲N̲E̲L̲ ̲S̲E̲T̲T̲I̲N̲G̲S̲\\n\\n{item.get('url', '')}\\n\\nSelect an option below.", kb([
                [("BUTTON TEXT", f"settings:forcejoin_other_label:{index}"), ("REMOVE", f"settings:forcejoin_other_remove:{index}")],
                [("《 BACK", "settings:forcejoin")],
            ]))
    elif action.startswith("forcejoin_other_label:"):
        index = int(action.split(":", 1)[1])
        cfg = await db.settings.find_one({"key": "force_join"}) or {}
        links = cfg.get("other_links", [])
        if 0 <= index < len(links):
            await state.set_state(SettingInput.waiting)
            await state.update_data(field="forcejoin_existing_other_label", other_index=index)
            if query.message: await query.message.answer("Send new button text for force-join channel button.")
    elif action.startswith("forcejoin_other_remove:"):
        index = int(action.split(":", 1)[1])
        cfg = await db.settings.find_one({"key": "force_join"}) or {}
        links = cfg.get("other_links", [])
        if 0 <= index < len(links):
            links.pop(index)
            await patch(db, "force_join", {"other_links": links})
        await render_forcejoin(query, db, settings)
    elif action == "forcejoin_other_default":
        data = await state.get_data()
        url = data.get("pending_url")
        if not url:
            await state.clear()
            if query.message: await query.message.answer("Add process expired. Please start again.")
            return
        channels = await effective_force_join_channels(database, settings)
        if len(channels) >= 10:
            await state.clear()
            if query.message: await query.message.answer("Maximum 10 force-join channels allowed.")
            return
        key = f"other:{datetime.now(timezone.utc).timestamp():.0f}"
        await patch(db, "force_join", {"other_links": (await db.settings.find_one({"key": "force_join"}) or {}).get("other_links", []) + [{"key": key, "url": url, "button_text": f"Join {len(channels)+1}"}]})
        await state.clear()
        if query.message: await query.message.answer(f"✨ Successfully added {urlparse(url).netloc} as your force-join channel.")
        await render_forcejoin(query, db, settings)
        return
    elif action == "forcejoin_other_custom":
        data = await state.get_data()
        if not data.get("pending_url"):
            await state.clear()
            if query.message: await query.message.answer("Add process expired. Please start again.")
            return
        await state.set_state(SettingInput.waiting)
        await state.update_data(field="forcejoin_other_label")
        if query.message: await query.message.answer("Send custom button text for force-join channel button.")
    elif action == "forcejoin_join_request":
        await state.set_state(SettingInput.waiting); await state.update_data(field="forcejoin_channel")
        if query.message: await query.message.answer("Send a public channel username or forward a message from the channel. Make sure the bot is an administrator in the selected channel.")
    elif action.startswith("forcejoin_channel:"):
        channels = await effective_force_join_channels(database, settings)
        index = int(action.split(":", 1)[1])
        if index < len(channels):
            channel = channels[index]
            cfg = await db.settings.find_one({"key": "force_join_channel", "channel": channel}) or {}
            await edit_page(query, f"C̲H̲A̲N̲N̲E̲L̲ ̲S̲E̲T̲T̲I̲N̲G̲S̲\\n\\n{channel}\\n\\nSelect an option below.", kb([
                [("BUTTON TEXT", f"settings:forcejoin_label:{index}"), ("REMOVE", f"settings:forcejoin_remove_one:{index}")],
                [("《 BACK", "settings:forcejoin")],
            ]))
    elif action.startswith("forcejoin_label:"):
        channels = await effective_force_join_channels(database, settings)
        index = int(action.split(":", 1)[1])
        if index < len(channels):
            await state.set_state(SettingInput.waiting); await state.update_data(field="forcejoin_label", channel=channels[index])
            if query.message: await query.message.answer("Send new button text for force-join channel button.")
    elif action.startswith("forcejoin_remove_one:"):
        channels = await effective_force_join_channels(database, settings)
        index = int(action.split(":", 1)[1])
        if index < len(channels):
            channel = channels.pop(index)
            await patch(db, "force_join", {"channels": channels})
            await db.settings.delete_one({"key": "force_join_channel", "channel": channel})
        await render_forcejoin(query, db, settings)
    elif action == "forcejoin_message":
        await state.set_state(SettingInput.waiting); await state.update_data(field="forcejoin_message")
        if query.message: await query.message.answer("Send your bot's new force-join message. Variables: {first_name}, {last_name}, {mention}, {remaining_count}.")
    elif action == "forcejoin_media":
        await edit_page(query, "F̲O̲R̲C̲E̲ ̲J̲O̲I̲N̲ ̲M̲E̲D̲I̲A̲\n\nAdd or remove the image/GIF shown with the Force Join message.", kb([
            [("ADD", "settings:forcejoin_media_add"), ("REMOVE", "settings:forcejoin_media_remove")],
            [("《 BACK", "settings:forcejoin")],
        ]))
    elif action == "forcejoin_media_add":
        await state.set_state(SettingInput.waiting); await state.update_data(field="forcejoin_media")
        if query.message: await query.message.answer("Only GIFs and images are supported. Send the new force-join poster here.")
    elif action == "forcejoin_media_remove":
        await db.settings.update_one({"key": "force_join"}, {"$unset": {"poster_file_id": "", "poster_photo_id": ""}}, upsert=True)
        if query.message: await query.message.answer("✨ Force-join poster removed successfully.")
        await render_forcejoin(query, db, settings)
    elif action == "forcejoin_verify_text":
        await state.set_state(SettingInput.waiting); await state.update_data(field="forcejoin_verify_text")
        if query.message: await query.message.answer("Send your new verification button text.")
    elif action == "forcejoin_remove":
        channels = await effective_force_join_channels(database, settings)
        rows = [[(channel, f"settings:forcejoin_del:{i}")] for i, channel in enumerate(channels)]
        rows.append([("BACK", "settings:forcejoin")])
        await edit_page(query, "REMOVE FORCE JOIN CHANNEL\nSelect a channel to remove.", kb(rows))
    elif action.startswith("forcejoin_del:"):
        channels = await effective_force_join_channels(database, settings)
        index = int(action.split(":", 1)[1])
        if 0 <= index < len(channels):
            channels.pop(index)
            await patch(db, "force_join", {"channels": channels})
        await render_forcejoin(query, db, settings)
    elif action == "start": await render_start(query, db)
    elif action == "start_toggle":
        cfg = await db.settings.find_one({"key": "start_message"}) or {}
        await patch(db, "start_message", {"enabled": not cfg.get("enabled", True)}, {"text": DEFAULT_START_TEXT})
        await render_start(query, db)
    elif action == "start_text": await render_start_text(query)
    elif action == "start_text_edit":
        await state.set_state(SettingInput.waiting); await state.update_data(field="start_text")
        if query.message: await query.message.answer("Variables:\n{first_name} — User first name\n{last_name} — User last name\n{mention} — Clickable mention of the user\n\nNow send your new start message text.")
    elif action == "start_text_see":
        cfg = await db.settings.find_one({"key": "start_message"}) or {}
        me = await query.bot.get_me()
        await query.answer(f"{me.full_name}\n\n{cfg.get('text') or DEFAULT_START_TEXT}", show_alert=True)
        return
    elif action == "start_text_default":
        await patch(db, "start_message", {"text": DEFAULT_START_TEXT}, {"enabled": True})
        me = await query.bot.get_me()
        await query.answer(f"{me.full_name}\n\n{DEFAULT_START_TEXT}", show_alert=True)
        await render_start_text(query)
        return
    elif action == "start_button": await render_start_button(query)
    elif action in ("start_button_text", "start_button_link"):
        await state.set_state(SettingInput.waiting); await state.update_data(field=action)
        if query.message:
            await query.message.answer("Send new button text for the start message." if action == "start_button_text" else "Send the new button link for the start message.")
    elif action == "start_poster": await render_start_poster(query)
    elif action == "start_poster_add":
        await state.set_state(SettingInput.waiting); await state.update_data(field="start_poster")
        if query.message: await query.message.answer("Only GIFs and images are supported. Send the new start message poster here.")
    elif action == "start_poster_remove":
        await db.settings.update_one({"key": "start_message"}, {"$unset": {"poster_file_id": "", "poster_photo_id": ""}}, upsert=True)
        if query.message: await query.message.answer("✨ Successfully removed your bot start poster.")
        await render_start_poster(query)
    elif action == "start_about":
        cfg = await db.settings.find_one({"key": "start_message"}) or {}
        await edit_page(query, f"START ABOUT BUTTON\nStatus: {'ENABLED' if cfg.get('about_enabled', False) else 'DISABLED'}", kb([
            [("ENABLE / DISABLE", "settings:start_about_toggle")],
            [("EDIT ABOUT TEXT", "settings:start_about_text")],
            [("BACK", "settings:start")],
        ]))
    elif action == "start_about_toggle":
        cfg = await db.settings.find_one({"key": "start_message"}) or {}
        await patch(db, "start_message", {"about_enabled": not cfg.get("about_enabled", True)}, {"enabled": True, "text": DEFAULT_START_TEXT})
        await render_start(query, db)
    elif action == "start_about_text":
        await state.set_state(SettingInput.waiting); await state.update_data(field="start_about_text")
        if query.message: await query.message.answer("Send the About text to show when the Start Message About button is tapped.")
    elif action == "auto": await render_auto(query, db)
    elif action == "auto_toggle":
        cfg = await db.settings.find_one({"key": "auto_delete"}) or {}
        turning_on = not cfg.get("enabled", False)
        await patch(db, "auto_delete", {"enabled": turning_on}, {"minutes": 30, "notice": DEFAULT_NOTICE})
        # Keep the After Delete preference saved; it is functionally inactive while Auto Delete is off.
        await render_auto(query, db)
    elif action == "auto_time": await render_auto_time(query, db)
    elif action == "auto_time_change":
        cfg = await db.settings.find_one({"key": "auto_delete"}) or {}
        current = int(cfg.get("minutes", 30))
        next_value = AUTO_DELETE_MINUTES[(AUTO_DELETE_MINUTES.index(current) + 1) % len(AUTO_DELETE_MINUTES)] if current in AUTO_DELETE_MINUTES else 2
        await patch(db, "auto_delete", {"minutes": next_value}, {"enabled": False, "notice": DEFAULT_NOTICE})
        if query.message: await query.message.answer(f"✨ Auto-delete time changed to {time_label(next_value)}.")
        await render_auto_time(query, db)
    elif action == "auto_message": await render_auto_message(query, db)
    elif action == "auto_message_edit":
        await state.set_state(SettingInput.waiting); await state.update_data(field="auto_notice")
        if query.message: await query.message.answer("Send your new auto-delete message. Use {auto_delete_time} to insert the timer.")
    elif action == "auto_message_see":
        cfg = await db.settings.find_one({"key": "auto_delete"}) or {}
        me = await query.bot.get_me()
        saved = (cfg.get("notice") or DEFAULT_NOTICE).replace("{auto_delete_time}", time_words(int(cfg.get("minutes", 30))))
        await query.answer(f"{me.full_name}\n\n{saved}", show_alert=True)
        return
    elif action == "auto_message_default":
        await patch(db, "auto_delete", {"notice": DEFAULT_NOTICE}, {"enabled": False, "minutes": 30})
        cfg = await db.settings.find_one({"key": "auto_delete"}) or {}
        me = await query.bot.get_me()
        default_text = DEFAULT_NOTICE.replace("{auto_delete_time}", time_words(int(cfg.get("minutes", 30))))
        await query.answer(f"{me.full_name}\n\n{default_text}", show_alert=True)
        await render_auto_message(query, db)
        return
    elif action == "after": await render_after(query, db)
    elif action == "after_toggle":
        auto = await db.settings.find_one({"key": "auto_delete", "enabled": True})
        if not auto:
            await patch(db, "after_delete", {"enabled": False}, {"text": DEFAULT_AFTER_TEXT, "button_text": DEFAULT_AFTER_BUTTON})
            if query.message: await query.message.answer("After Delete only works when Auto Delete is enabled.")
            await render_after(query, db)
            return
        cfg = await db.settings.find_one({"key": "after_delete"}) or {}
        await patch(db, "after_delete", {"enabled": not cfg.get("enabled", False)}, {"text": DEFAULT_AFTER_TEXT, "button_text": DEFAULT_AFTER_BUTTON})
        await render_after(query, db)
    elif action == "after_text": await render_after_text(query)
    elif action in ("after_text_message", "after_text_button"):
        await state.set_state(SettingInput.waiting); await state.update_data(field=action)
        if query.message: await query.message.answer("Send the new after-delete message text." if action == "after_text_message" else "Send new button text for the after-delete message.")
    elif action == "invalid": await render_invalid(query, db)
    elif action == "invalid_toggle":
        cfg = await db.settings.find_one({"key": "invalid_post"}) or {}
        await patch(db, "invalid_post", {"enabled": not cfg.get("enabled", False)}, {"text": DEFAULT_INVALID, "about_enabled": False})
        await render_invalid(query, db)
    elif action == "invalid_text":
        await state.set_state(SettingInput.waiting); await state.update_data(field="invalid_text")
        if query.message: await query.message.answer("Now send your new invalid message text. Variables: {first_name}, {last_name}, {mention}.")
    elif action == "invalid_button": await render_invalid_button(query)
    elif action in ("invalid_button_text", "invalid_button_link"):
        await state.set_state(SettingInput.waiting); await state.update_data(field=action)
        if query.message: await query.message.answer("Send new button text for the invalid post." if action == "invalid_button_text" else "Send new button link for the invalid post.")
    elif action == "invalid_poster": await render_poster(query)
    elif action == "poster_add":
        await state.set_state(SettingInput.waiting); await state.update_data(field="poster")
        if query.message: await query.message.answer("Only GIFs and images are supported. Send the new invalid-post poster here.")
    elif action == "poster_remove":
        await db.settings.update_one({"key": "invalid_post"}, {"$unset": {"poster_file_id": "", "poster_photo_id": ""}}, upsert=True)
        if query.message: await query.message.answer("✨ Invalid-post poster removed successfully.")
        await render_poster(query)
    elif action == "invalid_about": await render_about(query, db)
    elif action == "invalid_about_toggle":
        cfg = await db.settings.find_one({"key": "invalid_post"}) or {}
        await patch(db, "invalid_post", {"about_enabled": not cfg.get("about_enabled", False)}, {"enabled": False})
        await render_about(query, db)
    elif action == "invalid_about_text":
        await state.set_state(SettingInput.waiting); await state.update_data(field="invalid_about_text")
        if query.message: await query.message.answer("Send the About text to show when the About button is tapped.")
    elif action == "forcejoin_animation":
        cfg = await db.settings.find_one({"key": "animation"}) or {}
        await edit_page(query, f"A̲N̲I̲M̲A̲T̲I̲O̲N̲\\n\\nAdd a custom animation for the verification process.\\n\\nPrefix: {cfg.get('prefix', 'Checking..')}\\nFrames: {'3 configured' if len(cfg.get('frames', [])) == 3 else 'Not configured'}\\nSupported speed: 0.10 to 1.00 seconds per frame.\\nStatus: {'ENABLED' if cfg.get('enabled', False) else 'DISABLED'}", kb([
            [("PREFIX", "settings:animation_prefix"), ("FRAMES", "settings:animation_frames")],
            [("ENABLE / DISABLE", "settings:animation_toggle"), ("SPEED", "settings:animation_speed")],
            [("MODE", "settings:animation_mode")],
            [("《 BACK", "settings:home")],
        ]))
    elif action == "animation_prefix":
        await state.set_state(SettingInput.waiting); await state.update_data(field="animation_prefix")
        if query.message: await query.message.answer("Send new prefix text for the loop animation.")
    elif action == "animation_frames":
        await state.set_state(SettingInput.waiting); await state.update_data(field="animation_frame_1", pending_frames=[])
        if query.message: await query.message.answer("Send the first frame for the loop animation.")
    elif action == "animation_toggle":
        cfg = await db.settings.find_one({"key": "animation"}) or {}
        await patch(db, "animation", {"enabled": not cfg.get("enabled", False)}, {"prefix": "Checking..", "frames": [], "speed": 0.10, "mode": "new_message"})
        await render_animation(query, db)
    elif action == "animation_speed":
        cfg = await db.settings.find_one({"key": "animation"}) or {}
        speed = float(cfg.get("speed", 0.10))
        next_speed = round(0.10 + ((round((speed - 0.10) / 0.05) + 1) % 19) * 0.05, 2)
        await patch(db, "animation", {"speed": next_speed}, {"enabled": False, "prefix": "Checking..", "frames": [], "mode": "new_message"})
        await render_animation(query, db)
    elif action == "animation_mode":
        cfg = await db.settings.find_one({"key": "animation"}) or {}
        await edit_page(query, f"M̲O̲D̲E̲\\n\\nNew Message: Run the animation in a separate message.\\n\\nForce Join Poster: Run the animation on the force-join poster.\\n\\nCurrent mode: {cfg.get('mode', 'new_message')}", kb([
            [("NEW MESSAGE", "settings:animation_mode_new"), ("FORCE JOIN POSTER", "settings:animation_mode_poster")],
            [("《 BACK", "settings:forcejoin_animation")],
        ]))
    elif action in ("animation_mode_new", "animation_mode_poster"):
        await patch(db, "animation", {"mode": "new_message" if action.endswith("_new") else "force_join_poster"}, {"enabled": False, "prefix": "Checking..", "frames": [], "speed": 0.10})
        await render_animation(query, db)
    elif action == "shortener": await render_shortener(query, db)
    elif action == "shortener_add":
        await state.set_state(SettingInput.waiting); await state.update_data(field="shortener_url")
        if query.message: await query.message.answer("Send your shortener website URL here (for example https://gplinks.com). Compatible provider API endpoints are also accepted.")
    elif action == "shortener_remove":
        await db.settings.update_one({"key": "shortener"}, {"$set": {"enabled": False}, "$unset": {"token": ""}})
        await render_shortener(query, db)
    elif action == "mods": await render_mods(query, db)
    elif action == "mod_add":
        if query.from_user.id != settings.owner_id:
            await query.answer("Only the owner can add moderators.", show_alert=True); return
        if await db.moderators.count_documents({}) >= 3:
            await query.answer("Maximum 3 moderators allowed.", show_alert=True); return
        await state.set_state(SettingInput.waiting); await state.update_data(field="mod_id")
        if query.message: await query.message.answer("Please send the Telegram user ID of the new moderator.")
    elif action == "mod_remove":
        if query.from_user.id != settings.owner_id:
            await query.answer("Only the owner can remove moderators.", show_alert=True); return
        mods = await db.moderators.find({}).sort("user_id", 1).to_list(length=3)
        rows = [[(m.get("first_name") or f"User {m['user_id']}", f"settings:mod_del:{m['user_id']}")] for m in mods]
        rows.append([("BACK", "settings:mods")])
        await edit_page(query, "REMOVE MODERATOR\nSelect the moderator you want to remove.", kb(rows))
    elif action.startswith("mod_del:"):
        if query.from_user.id != settings.owner_id:
            await query.answer("Only the owner can remove moderators.", show_alert=True); return
        uid = int(action.split(":", 1)[1])
        result = await db.moderators.delete_one({"user_id": uid})
        if query.message: await query.message.answer("✨ Successfully removed moderator." if result.deleted_count else "Moderator not found.")
        await render_mods(query, db)
    elif action == "stats":
        total = await db.users.count_documents({})
        blocked = await db.users.count_documents({"blocked": True})
        me = await query.bot.get_me()
        await query.answer(f"{me.full_name}\n\nUSERS: {total}\n\nBLOCKED: {blocked}", show_alert=True)
        return
    await query.answer()

@router.message(SettingInput.waiting, Command("cancel"))
async def cancel_setting_input(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Setting change cancelled.")

@router.message(SettingInput.waiting)
async def receive_setting_input(message: Message, state: FSMContext, settings: Settings, database):
    if message.text and message.text.startswith("/"):
        raise SkipHandler
    if not message.from_user or not await is_owner_or_moderator(database.db, message.from_user.id, settings):
        return
    data = await state.get_data()
    field = data.get("field")
    db = database.db
    value = (message.text or "").strip()
    if field == "animation_prefix":
        await patch(db, "animation", {"prefix": value}, {"enabled": False, "frames": [], "speed": 0.10, "mode": "new_message"})
        await state.clear()
        await message.answer("✨ Animation prefix updated successfully.")
        return
    if field in ("animation_frame_1", "animation_frame_2", "animation_frame_3"):
        frames = list(data.get("pending_frames", []))
        frames.append(value)
        if len(frames) < 3:
            next_field = f"animation_frame_{len(frames)+1}"
            await state.update_data(field=next_field, pending_frames=frames)
            prompt = "Now send the middle frame." if len(frames) == 1 else "Send the last frame."
            await message.answer(prompt)
            return
        await patch(db, "animation", {"frames": frames}, {"enabled": False, "prefix": "Checking..", "speed": 0.10, "mode": "new_message"})
        await state.clear()
        await message.answer("✨ Animation frames updated successfully.")
        return
    if field == "forcejoin_other_url":
        parsed = urlparse(value)
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            await message.answer("Please send a valid http/https platform link.")
            return
        channels = await effective_force_join_channels(database, settings)
        if len(channels) >= 10:
            await message.answer("Maximum 10 force-join channels allowed.")
            await state.clear()
            return
        existing_other = await db.settings.find_one({"key": "force_join_channel", "url": value})
        if existing_other:
            await message.answer("That link is already configured.")
            return
        await state.update_data(field="forcejoin_other_label", pending_url=value)
        await message.answer("Use the default button text or set a custom button text.", reply_markup=kb([
            [("DEFAULT", "settings:forcejoin_other_default"), ("CUSTOM", "settings:forcejoin_other_custom")],
            [("《 BACK", "settings:forcejoin")],
        ]))
        return
    if field == "forcejoin_other_label":
        prev = await state.get_data()
        cfg = await db.settings.find_one({"key": "force_join"}) or {}
        channels = await effective_force_join_channels(database, settings)
        other_links = list(cfg.get("other_links", []))
        if len(channels) + len(other_links) >= 10:
            await message.answer("Maximum 10 force-join channels allowed.")
            await state.clear()
            return
        url = prev.get("pending_url")
        if not url:
            await message.answer("Add process expired. Please start again.")
            await state.clear()
            return
        channel_key = f"other:{len(other_links)+1}"
        other_links.append({"key": channel_key, "url": url, "button_text": value})
        await patch(db, "force_join", {"other_links": other_links})
        await state.clear()
        await message.answer(f"✨ Successfully added {urlparse(url).netloc} as your force-join channel.")
        return
    if field == "forcejoin_existing_other_label":
        prev = await state.get_data()
        cfg = await db.settings.find_one({"key": "force_join"}) or {}
        links = cfg.get("other_links", [])
        index = int(prev.get("other_index", -1))
        if 0 <= index < len(links):
            links[index]["button_text"] = value
            await patch(db, "force_join", {"other_links": links})
            await message.answer("✨ Successfully updated force-join button text.")
        else:
            await message.answer("Channel setting expired. Please reopen it.")
        await state.clear()
        return
    if field == "forcejoin_label":
        prev = await state.get_data()
        channel = prev.get("channel")
        if not channel:
            await message.answer("Channel setting expired. Please reopen it.")
            await state.clear()
            return
        await patch(db, "force_join_channel", {"channel": channel, "button_text": value})
        await state.clear()
        await message.answer(f"✨ Successfully updated button text for {channel} force-join button.")
        return
    if field == "forcejoin_message":
        await patch(db, "force_join", {"message": value})
        await state.clear()
        await message.answer("✨ Successfully updated force-join message.")
        return
    if field == "forcejoin_verify_text":
        await patch(db, "force_join", {"verify_text": value})
        await state.clear()
        await message.answer("✨ Successfully updated verification button text.")
        return
    if field == "forcejoin_media":
        if message.animation:
            await patch(db, "force_join", {"poster_file_id": message.animation.file_id, "poster_photo_id": None})
        elif message.photo:
            await patch(db, "force_join", {"poster_photo_id": message.photo[-1].file_id, "poster_file_id": None})
        else:
            await message.answer("Only GIFs and images are supported. Send a photo or GIF.")
            return
        await state.clear()
        await message.answer("✨ Force-join poster updated successfully.")
        return
    if field == "forcejoin_channel":
        channel = value.strip()
        if channel.startswith("https://t.me/"):
            channel = "@" + channel.removeprefix("https://t.me/").strip("/").split("/", 1)[0].lstrip("@")
        if not channel.startswith("@") or len(channel) < 6 or not channel[1:].replace("_", "").isalnum():
            await message.answer("Send a public channel username such as @mychannel.")
            return
        try:
            chat = await message.bot.get_chat(channel)
            if chat.type not in ("channel", "supergroup"):
                await message.answer("Force Join target must be a channel or supergroup.")
                return
            me = await message.bot.get_me()
            bot_member = await message.bot.get_chat_member(chat.id, me.id)
            if bot_member.status not in ("administrator", "creator"):
                await message.answer("Make the bot an administrator in that channel before adding it to Force Join.")
                return
        except TelegramAPIError:
            await message.answer("The bot cannot access that channel. Check the public username and bot permissions.")
            return
        channels = await effective_force_join_channels(database, settings)
        if channel in channels:
            await message.answer("That Force Join channel is already configured.")
            await state.clear()
            return
        channels.append(channel)
        await patch(db, "force_join", {"channels": channels})
        await state.clear()
        await message.answer(f"Force Join channel {channel} added.")
        return
    if field == "forcejoin_animation":
        if not message.animation:
            await message.answer("Send a GIF animation to use after Force Join verification.")
            return
        await patch(db, "force_join_animation", {"file_id": message.animation.file_id})
        await state.clear()
        await message.answer("Force Join animation updated successfully.")
        return
    if field == "start_poster":
        if message.animation:
            await patch(db, "start_message", {"poster_file_id": message.animation.file_id, "poster_photo_id": None}, {"enabled": True})
        elif message.photo:
            await patch(db, "start_message", {"poster_photo_id": message.photo[-1].file_id, "poster_file_id": None}, {"enabled": True})
        else:
            await message.answer("Only GIFs and images are supported. Send a photo or GIF.")
            return
        await state.clear(); await message.answer("✨ Start poster updated successfully."); return
    if field == "poster":
        if message.animation:
            await patch(db, "invalid_post", {"poster_file_id": message.animation.file_id, "poster_photo_id": None}, {"enabled": False})
        elif message.photo:
            await patch(db, "invalid_post", {"poster_photo_id": message.photo[-1].file_id, "poster_file_id": None}, {"enabled": False})
        else:
            await message.answer("Only GIFs and images are supported. Send a photo or GIF.")
            return
        await state.clear(); await message.answer("✨ Invalid-post poster updated successfully."); return
    if not value:
        await message.answer("Please send a non-empty value.")
        return
    if field == "start_text":
        await patch(db, "start_message", {"text": value}, {"enabled": True})
        await message.answer("✨ Successfully updated your start message text.")
    elif field == "start_button_text":
        await patch(db, "start_message", {"button_text": value, "button_enabled": True}, {"enabled": True, "text": DEFAULT_START_TEXT, "button_url": "http://t.me/lexiAnime", "about_enabled": True})
        await message.answer("✨ Successfully updated start message button text.")
    elif field == "start_button_link":
        parsed = urlparse(value)
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            await message.answer("Button link must be a valid http/https URL.")
            return
        await patch(db, "start_message", {"button_url": value, "button_enabled": True}, {"enabled": True, "button_text": "📟 UPDATE CHANNEL", "button_url": "http://t.me/lexiAnime"})
        await message.answer("✨ Successfully updated start message button link.")
    elif field == "auto_notice":
        await patch(db, "auto_delete", {"notice": value}, {"enabled": False, "minutes": 30})
        await message.answer("✨ Auto-delete message updated successfully.")
    elif field == "after_text_message":
        await patch(db, "after_delete", {"text": value}, {"enabled": False, "button_text": DEFAULT_AFTER_BUTTON})
        await message.answer("✨ After-delete message text updated successfully.")
    elif field == "after_text_button":
        await patch(db, "after_delete", {"button_text": value}, {"enabled": False, "text": DEFAULT_AFTER_TEXT})
        await message.answer("✨ After-delete button text updated successfully.")
    elif field == "invalid_text":
        await patch(db, "invalid_post", {"text": value}, {"enabled": False, "about_enabled": False})
        await message.answer("✨ Successfully updated your bot's invalid message text.")
    elif field == "invalid_button_text":
        await state.update_data(button_text=value, field="invalid_button_link")
        await message.answer("Send new button link for the invalid post.")
        return
    elif field == "invalid_button_link":
        parsed = urlparse(value)
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            await message.answer("Button link must be a valid http/https URL.")
            return
        prev = await state.get_data()
        values = {"button_url": value}
        if prev.get("button_text"): values["button_text"] = prev["button_text"]
        await patch(db, "invalid_post", values, {"enabled": False})
        await message.answer("✨ Successfully updated invalid post button link.")
    elif field == "invalid_about_text":
        await patch(db, "invalid_post", {"about_text": value}, {"enabled": False, "about_enabled": True})
        await message.answer("Invalid About text updated.")
    elif field == "shortener_url":
        parsed = urlparse(value)
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            await message.answer("Please send a valid http/https shortener URL.")
            return
        await state.update_data(shortener_url=value, field="shortener_token")
        await message.answer("Send your API token. It will be masked in settings and never logged.")
        return
    elif field == "shortener_token":
        prev = await state.get_data()
        try:
            await shorten_url(prev["shortener_url"], value, "https://example.com")
        except Exception:
            await message.answer("Provider validation failed. Check the API URL/token and try again.")
            return
        await patch(db, "shortener", {"enabled": True, "url": prev["shortener_url"], "token": value})
        await message.answer(f"✨ Successfully added {urlparse(prev['shortener_url']).netloc} as your link shortener provider.")
    elif field == "mod_id":
        if not value.isdigit() or int(value) <= 0:
            await message.answer("Please send a valid numeric Telegram user ID.")
            return
        uid = int(value)
        if uid == settings.owner_id:
            await message.answer("Owner is not stored as a moderator.")
            return
        if await db.users.find_one({"user_id": uid, "banned": True}):
            await message.answer("Unban this user before adding them as a moderator.")
            await state.clear(); return
        if await db.moderators.find_one({"user_id": uid}):
            await message.answer("This user is already a moderator.")
            await state.clear(); return
        if await db.moderators.count_documents({}) >= 3:
            await message.answer("Maximum 3 moderators allowed.")
            await state.clear(); return
        user = await db.users.find_one({"user_id": uid}) or {}
        name = user.get("first_name") or f"User {uid}"
        await db.moderators.insert_one({"user_id": uid, "first_name": name, "username": user.get("username")})
        await message.answer(f"✨ Successfully added {name} as moderator.")
    else:
        await message.answer("Unknown setting. Open /settings to try again.")
    await state.clear()

# Backwards-compatible command aliases for owners/moderators who prefer commands.
@router.message(Command("setstart"))
async def setstart(m: Message, settings: Settings, database):
    if not await allowed(m, settings, database): return
    p=(m.text or "").split(maxsplit=1)
    if len(p)!=2 or p[1].lower() not in ("on","off"): await m.answer("Usage: /setstart on|off"); return
    await patch(database.db, "start_message", {"enabled": p[1].lower()=="on"}, {"text":"👋 Welcome! Send a valid file link to receive your file."})
    await m.answer("Start message setting updated.")

@router.message(Command("setstarttext"))
async def setstarttext(m: Message, settings: Settings, database):
    if not await allowed(m, settings, database): return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2: await m.answer("Usage: /setstarttext TEXT"); return
    await patch(database.db, "start_message", {"text":p[1]}, {"enabled":True})
    await m.answer("Start message text updated.")

@router.message(Command("setinvalid"))
async def setinvalid(m: Message, settings: Settings, database):
    if not await allowed(m, settings, database): return
    p=(m.text or "").split(maxsplit=1)
    if len(p)!=2 or p[1].lower() not in ("on","off"): await m.answer("Usage: /setinvalid on|off"); return
    await patch(database.db, "invalid_post", {"enabled":p[1].lower()=="on"}, {"text":DEFAULT_INVALID})
    await m.answer("Invalid-post setting updated.")

@router.message(Command("setinvalidtext"))
async def setinvalidtext(m: Message, settings: Settings, database):
    if not await allowed(m, settings, database): return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2: await m.answer("Usage: /setinvalidtext TEXT"); return
    await patch(database.db, "invalid_post", {"text":p[1]}, {"enabled":False})
    await m.answer("✨ Successfully updated your bot's invalid message text.")

@router.message(Command("setautodelete"))
async def setautodelete(m: Message, settings: Settings, database):
    if not await allowed(m, settings, database): return
    p=(m.text or "").split(maxsplit=1)
    if len(p)!=2 or p[1].lower() not in ("on","off"): await m.answer("Usage: /setautodelete on|off"); return
    await patch(database.db, "auto_delete", {"enabled":p[1].lower()=="on"}, {"minutes":30,"notice":DEFAULT_NOTICE})
    await m.answer("Auto Delete setting updated.")

@router.message(Command("setautodeletemin"))
async def setautodeletemin(m: Message, settings: Settings, database):
    if not await allowed(m, settings, database): return
    p=(m.text or "").split()
    if len(p)!=2 or not p[1].isdigit() or int(p[1]) not in AUTO_DELETE_MINUTES:
        await m.answer("Choose one: 2, 5, 15, 30, 60, 180, 360, 720, or 1440 minutes."); return
    await patch(database.db, "auto_delete", {"minutes":int(p[1])}, {"enabled":False,"notice":DEFAULT_NOTICE})
    await m.answer(f"✨ Auto-delete time changed to {time_label(int(p[1]))}.")

@router.message(Command("setnotice"))
async def setnotice(m: Message, settings: Settings, database):
    if not await allowed(m, settings, database): return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2: await m.answer("Usage: /setnotice TEXT"); return
    await patch(database.db, "auto_delete", {"notice":p[1]}, {"enabled":False,"minutes":30})
    await m.answer("✨ Auto-delete message updated successfully.")

@router.message(Command("setafterdelete"))
async def setafterdelete(m: Message, settings: Settings, database):
    if not await allowed(m, settings, database): return
    p=(m.text or "").split(maxsplit=1)
    if len(p)!=2 or p[1].lower() not in ("on","off"): await m.answer("Usage: /setafterdelete on|off"); return
    await patch(database.db, "after_delete", {"enabled":p[1].lower()=="on"}, {"text":DEFAULT_AFTER_TEXT,"button_text":DEFAULT_AFTER_BUTTON})
    await m.answer("After Delete setting updated.")

@router.message(Command("setafterdeletetext"))
async def setafterdeletetext(m: Message, settings: Settings, database):
    if not await allowed(m, settings, database): return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2: await m.answer("Usage: /setafterdeletetext TEXT"); return
    await patch(database.db, "after_delete", {"text":p[1]}, {"enabled":False,"button_text":DEFAULT_AFTER_BUTTON})
    await m.answer("✨ After-delete message text updated successfully.")

@router.message(Command("setafterdeletebutton"))
async def setafterdeletebutton(m: Message, settings: Settings, database):
    if not await allowed(m, settings, database): return
    p=(m.text or "").split(maxsplit=1)
    if len(p)<2: await m.answer("Usage: /setafterdeletebutton BUTTON_TEXT"); return
    await patch(database.db, "after_delete", {"button_text":p[1]}, {"enabled":False,"text":DEFAULT_AFTER_TEXT})
    await m.answer("✨ After-delete button text updated successfully.")

@router.message(Command("setshortener"))
async def setshortener(m: Message, settings: Settings, database):
    if not await allowed(m, settings, database): return
    p=(m.text or "").split(maxsplit=2)
    if len(p)!=3: await m.answer("Usage: /setshortener API_URL API_TOKEN"); return
    parsed=urlparse(p[1])
    if parsed.scheme not in ("https","http") or not parsed.netloc: await m.answer("API URL must be a valid http/https URL."); return
    try:
        await shorten_url(p[1], p[2], "https://example.com")
    except Exception:
        await m.answer("Provider validation failed. Check the API URL/token and try again.")
        return
    await patch(database.db, "shortener", {"enabled":True,"url":p[1],"token":p[2]})
    await m.answer(f"Shortener provider configured: {parsed.netloc}. API token is stored privately.")

@router.message(Command("setforcejoinanimation"))
async def setforcejoinanimation(message: Message, state: FSMContext, settings: Settings, database):
    if not await allowed(message, settings, database):
        return
    await state.set_state(SettingInput.waiting)
    await state.update_data(field="forcejoin_animation")
    await message.answer("Send the GIF animation to show after Force Join verification. It will be removed after delivery and is not part of Auto Delete.")

@router.message(Command("removeforcejoinanimation"))
async def removeforcejoinanimation(message: Message, settings: Settings, database):
    if not await allowed(message, settings, database):
        return
    await database.db.settings.update_one({"key": "force_join_animation"}, {"$unset": {"file_id": ""}}, upsert=True)
    await message.answer("Force Join animation removed.")
