"""Start command, Force Join gate, and single/batch deeplink delivery."""
import logging
import hashlib
import html
import asyncio
from urllib.parse import urlparse
from datetime import datetime, timezone
from aiogram import Router,F
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import Message,InlineKeyboardMarkup,InlineKeyboardButton,CallbackQuery
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from app.config import Settings
from app.database.files import FileRepository
from app.services.delivery import deliver_reference,deliver_batch,claim_delivery_request,finish_delivery_request
from app.services.permissions import is_owner_or_moderator
from app.services.text_format import normalize_telegram_text
router=Router(name="start");log=logging.getLogger(__name__)

def render_common_variables(raw_text, user, bot):
    """Render shared message variables as Telegram HTML without nesting links."""
    text = str(raw_text or "")
    username = getattr(bot, "username", None)
    bot_name = html.escape(getattr(bot, "full_name", None) or getattr(bot, "first_name", None) or "Bot")
    bot_mention = f'<a href="https://t.me/{html.escape(username)}">{bot_name}</a>' if username else bot_name
    values = {
        "{bot_mention}": bot_mention,
        "{bot}": bot_mention,
        "{user_mention}": user.mention_html(),
        "{user}": user.mention_html(),
        "{first_name}": html.escape(user.first_name or ""),
        "{last_name}": html.escape(user.last_name or ""),
        "{owner}": '<a href="https://t.me/lexxiowner">Lexi</a>',
        "{anime}": '<a href="https://t.me/lexianime">Lexi Anime</a>',
        "{hindi_anime}": '<a href="https://t.me/lexianimehindi">Lexi Anime Hindi</a>',
        "{mention}": user.mention_html(),
    }
    for token, replacement in values.items():
        text = text.replace(token, replacement)
    return text


async def effective_force_join_channels(database, settings) -> list[str]:
    cfg = await database.db.settings.find_one({"key": "force_join"})
    raw_channels = cfg.get("channels", []) if cfg is not None and isinstance(cfg.get("channels"), list) else settings.force_join_channels
    channels = []
    for raw in raw_channels:
        channel = str(raw).strip()
        if channel.lower().startswith(("https://t.me/", "http://t.me/", "https://telegram.me/", "http://telegram.me/", "t.me/", "telegram.me/")):
            parsed_channel = urlparse(channel if "://" in channel else "https://" + channel)
            channel = "@" + parsed_channel.path.strip("/").split("/", 1)[0].lstrip("@")
        elif channel.startswith("@"):
            channel = channel.split("/", 1)[0]
        elif channel.startswith("tg://resolve?domain="):
            channel = "@" + channel.split("domain=", 1)[1].split("&", 1)[0]
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

def force_join_button_label(channel_cfg: dict, position: int) -> str:
    """Custom text overrides the default; its slot still consumes its number."""
    custom = str(channel_cfg.get("button_text") or "").strip()
    return (custom or f"Join {position}")[:64]


async def join_status(bot,user_id:int,channels:list[str],db=None)->list[str]:
    missing=[]
    for raw in channels:
        channel=raw.strip()
        if not channel:continue
        try:
            chat_arg = int(channel) if channel.lstrip("-").isdigit() else channel
            chat = await bot.get_chat(chat_arg)
            member=await bot.get_chat_member(chat_id=chat.id,user_id=user_id)
            verified = member.status in ("creator","administrator","member") or (member.status=="restricted" and getattr(member,"is_member",False))
            channel_cfg = await db.settings.find_one({"key": "force_join_channel", "channel": channel}) if db is not None else None
            mode = (channel_cfg or {}).get("mode", "join_request")
            if not verified and mode == "join_request" and db is not None:
                pending = await db.pending_join_requests.find_one({"chat_id": chat.id, "user_id": user_id})
                verified = bool(pending)
            if not verified: missing.append(channel)
        except TelegramAPIError:
            missing.append(channel)
    return missing

# Active text-animation tasks are process-local; file/gate state itself remains in MongoDB.
_gate_animation_tasks: dict[tuple[int, str], tuple[asyncio.Task, int | None]] = {}


async def _cancel_gate_animation(bot, user_id: int, payload: str,
                               delete_separate: bool = True) -> int | None:
    entry = _gate_animation_tasks.pop((user_id, payload), None)
    if not entry:
        return None
    task, separate_message_id = entry
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    if separate_message_id and delete_separate:
        try:
            await bot.delete_message(user_id, separate_message_id)
        except TelegramAPIError:
            pass
    return separate_message_id


async def _animate_gate(bot, user_id: int, payload: str, gate_message: Message,
                        base_text: str, markup: InlineKeyboardMarkup, cfg: dict,
                        separate_message_id: int | None, animation_only: bool = False):
    frames = cfg.get("frames")
    if not isinstance(frames, list) or len(frames) != 3:
        frames = [".", "..", "..."]
    prefix = html.escape(str(cfg.get("prefix") or "Checking.."))
    try:
        speed = float(cfg.get("speed", 0.10))
    except (TypeError, ValueError):
        speed = 0.10
    speed = min(1.0, max(0.10, speed))
    mode = cfg.get("mode", "force_join_poster")
    target_id = separate_message_id if mode == "new_message" else gate_message.message_id
    while True:
        for frame in frames:
            animated = f"{prefix} {html.escape(str(frame))}"
            try:
                if mode == "new_message":
                    await bot.edit_message_text(
                        chat_id=user_id, message_id=target_id, text=animated,
                    )
                else:
                    content = f"<i>{animated}</i>" if animation_only else f"{base_text}\n\n<i>{animated}</i>"
                    if gate_message.photo or gate_message.animation or gate_message.document:
                        await bot.edit_message_caption(
                            chat_id=user_id, message_id=target_id, caption=content,
                            parse_mode="HTML", reply_markup=markup,
                        )
                    else:
                        await bot.edit_message_text(
                            chat_id=user_id, message_id=target_id, text=content,
                            parse_mode="HTML", reply_markup=markup,
                        )
            except TelegramBadRequest as exc:
                # Telegram reports an unchanged edit when a frame repeats; keep the loop alive.
                if "message is not modified" not in str(exc).lower():
                    log.debug("Force Join animation edit rejected", exc_info=True)
                    return
            except TelegramRetryAfter as exc:
                await asyncio.sleep(max(speed, float(exc.retry_after)))
                continue
            except TelegramAPIError:
                log.debug("Force Join animation stopped because its message could not be edited", exc_info=True)
                return
            await asyncio.sleep(speed)


async def _start_gate_animation(bot, user_id: int, payload: str, gate_message: Message,
                                base_text: str, markup: InlineKeyboardMarkup, cfg: dict,
                                animation_only: bool = False):
    if not cfg.get("enabled"):
        return
    await _cancel_gate_animation(bot, user_id, payload)
    mode = cfg.get("mode", "force_join_poster")
    separate_id = None
    if mode == "new_message":
        first = f"{html.escape(str(cfg.get('prefix') or 'Checking..'))} {html.escape(str((cfg.get('frames') or ['.', '..', '...'])[0]))}"
        try:
            animation_message = await bot.send_message(user_id, first)
            separate_id = animation_message.message_id
        except TelegramAPIError:
            log.warning("Could not send separate Force Join animation", exc_info=True)
            return
    task = asyncio.create_task(
        _animate_gate(bot, user_id, payload, gate_message, base_text, markup, cfg, separate_id, animation_only)
    )
    _gate_animation_tasks[(user_id, payload)] = (task, separate_id)


async def gate_or_prompt(message:Message,payload:str,settings,database,bot)->bool:
    user=message.from_user
    if not user or user.id==settings.owner_id or await is_owner_or_moderator(database.db,user.id,settings):
        return False
    cfg = await database.db.settings.find_one({"key": "force_join"}) or {}
    if not cfg.get("enabled", False):
        return False
    channels = await effective_force_join_channels(database, settings)
    if not channels:
        return False

    animation_cfg = await database.db.settings.find_one({"key": "animation"}) or {}
    animation_enabled = bool(animation_cfg.get("enabled"))
    animation_mode = animation_cfg.get("mode", "force_join_poster")
    animation_post = None

    # Deeplink entry performs a membership check too, so show the configured
    # animation during that check rather than only after the user taps Verify.
    if animation_enabled:
        if animation_mode == "new_message":
            await _start_gate_animation(bot, user.id, payload, message, "", InlineKeyboardMarkup(inline_keyboard=[]), animation_cfg)
        else:
            frames = animation_cfg.get("frames")
            if not isinstance(frames, list) or len(frames) != 3:
                frames = [".", "..", "..."]
            first = f"{html.escape(str(animation_cfg.get('prefix') or 'Checking..'))} {html.escape(str(frames[0]))}"
            try:
                if cfg.get("poster_file_id"):
                    animation_post = await bot.send_animation(user.id, cfg["poster_file_id"], caption=f"<i>{first}</i>", parse_mode="HTML")
                elif cfg.get("poster_photo_id"):
                    animation_post = await bot.send_photo(user.id, cfg["poster_photo_id"], caption=f"<i>{first}</i>", parse_mode="HTML")
                else:
                    animation_post = await bot.send_message(user.id, f"<i>{first}</i>", parse_mode="HTML")
                await _start_gate_animation(bot, user.id, payload, animation_post, "", InlineKeyboardMarkup(inline_keyboard=[]), animation_cfg, animation_only=True)
            except TelegramAPIError:
                log.warning("Could not create Force Join animation poster during deeplink check", exc_info=True)
                animation_post = None

    missing = await join_status(bot, user.id, channels, database.db)
    if animation_enabled:
        # Let at least one complete frame cycle become visible even when Telegram
        # answers membership checks very quickly.
        frames_for_wait = animation_cfg.get("frames")
        if not isinstance(frames_for_wait, list) or len(frames_for_wait) != 3:
            frames_for_wait = [".", "..", "..."]
        try:
            frame_speed = min(1.0, max(0.10, float(animation_cfg.get("speed", 0.10))))
        except (TypeError, ValueError):
            frame_speed = 0.10
        await asyncio.sleep(max(0.8, frame_speed * len(frames_for_wait)))
    if not missing:
        await _cancel_gate_animation(bot, user.id, payload)
        if animation_post:
            try:
                await animation_post.delete()
            except TelegramAPIError:
                pass
        await _mark_verified(database.db, user.id, channels)
        return False

    join_buttons = []
    for index, channel in enumerate(missing):
        channel_cfg = await database.db.settings.find_one({"key": "force_join_channel", "channel": channel}) or {}
        target = channel_cfg.get("button_url") or (channel if channel.startswith("https://") else (f"https://t.me/{channel.lstrip('@')}" if not channel.lstrip("-").isdigit() else None))
        if target:
            label = force_join_button_label(channel_cfg, index + 1)
            join_buttons.append(InlineKeyboardButton(text=label, url=target))
    rows = [join_buttons[i:i+2] for i in range(0, len(join_buttons), 2)]
    rows.append([InlineKeyboardButton(text=cfg.get("verify_text") or "ɪ ᴊᴏɪɴᴇᴅ — ᴄʜᴇᴄᴋ ᴀɢᴀɪɴ",callback_data=f"forcejoin:check:{payload}")])
    raw_text = cfg.get("message") or "Hey {user_mention}! Please join my {remaining_count} remaining channel(s) to use me."
    me = await bot.get_me()
    rendered = render_common_variables(raw_text, user, me).replace("{remaining_count}", str(len(missing)))
    markup = InlineKeyboardMarkup(inline_keyboard=rows)

    separate_animation_id = None
    if animation_enabled:
        # Keep New Message animation visible until the replacement Force Join post
        # has actually been sent; delete it immediately afterwards.
        separate_animation_id = await _cancel_gate_animation(
            bot, user.id, payload, delete_separate=(animation_mode != "new_message")
        )
    if animation_enabled and animation_mode == "force_join_poster" and animation_post:
        # Stop the loop and turn its poster into the Force Join prompt.
        try:
            if animation_post.photo or animation_post.animation or animation_post.document:
                await bot.edit_message_caption(chat_id=user.id, message_id=animation_post.message_id, caption=rendered, parse_mode="HTML", reply_markup=markup)
            else:
                await bot.edit_message_text(chat_id=user.id, message_id=animation_post.message_id, text=rendered, parse_mode="HTML", reply_markup=markup)
        except TelegramAPIError:
            log.warning("Could not convert animation poster to Force Join prompt", exc_info=True)
            await _send_force_join_post(bot, user.id, cfg, rendered, markup)
            try:
                await animation_post.delete()
            except TelegramAPIError:
                pass
    else:
        new_post = await _send_force_join_post(bot, user.id, cfg, rendered, markup)
        if separate_animation_id:
            try:
                await bot.delete_message(chat_id=user.id, message_id=separate_animation_id)
            except TelegramAPIError:
                pass
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
    cfg=await database.db.settings.find_one({"key":"start_message"}) or {}
    if cfg.get("enabled", True):
        rows = []
        button1_url = cfg.get("button1_url", cfg.get("button_url", "http://t.me/lexiAnime"))
        button1_text = cfg.get("button1_text", cfg.get("button_text", "📟 UPDATE CHANNEL"))
        parsed1 = urlparse(button1_url)
        configured_buttons = []
        if cfg.get("button1_enabled", cfg.get("button_enabled", True)) and button1_text and parsed1.scheme in ("http", "https") and parsed1.netloc:
            configured_buttons.append(InlineKeyboardButton(text=button1_text, url=button1_url))
        button2_url = cfg.get("button2_url", "")
        button2_text = cfg.get("button2_text", "")
        parsed2 = urlparse(button2_url)
        if cfg.get("button2_enabled", False) and button2_text and parsed2.scheme in ("http", "https") and parsed2.netloc:
            configured_buttons.append(InlineKeyboardButton(text=button2_text, url=button2_url))
        if configured_buttons:
            rows.append(configured_buttons)
        if cfg.get("about_enabled", True):
            rows.append([InlineKeyboardButton(text=cfg.get("about_button_text", "ᴀʙᴏᴜᴛ"), callback_data="start:about")])
        markup = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
        raw_text = normalize_telegram_text(cfg.get("text") or "<b>Hey {user_mention}✨</b>\\n\\n<i>Welcome to the fastest and most secure file store bot!</i>")
        me = await message.bot.get_me()
        text = render_common_variables(raw_text, user, me)
        if cfg.get("poster_file_id"):
            await message.answer_animation(cfg["poster_file_id"], caption=text, reply_markup=markup, parse_mode="HTML")
        elif cfg.get("poster_photo_id"):
            await message.answer_photo(cfg["poster_photo_id"], caption=text, reply_markup=markup, parse_mode="HTML")
        else:
            await message.answer(text, reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data == "start:about")
async def start_about(query: CallbackQuery, database):
    await query.answer()
    if not query.from_user or await FileRepository(database.db).is_banned(query.from_user.id):
        return
    cfg = await database.db.settings.find_one({"key": "start_message"}) or {}
    if not cfg.get("enabled", True) or not cfg.get("about_enabled", True) or not query.message:
        return
    me = await query.bot.get_me()
    about_text = cfg.get("about_text") or "<b>✦ About {bot_mention}</b>\n\n<blockquote>A simple and reliable way to access files. 📂</blockquote>\n\n<b>⚡ Features</b>\n<blockquote>• Fast file delivery • One-tap access • Easy to use</blockquote>\n\n<b>✦ Made by: {owner}</b>"
    rendered = render_common_variables(about_text, query.from_user, me).replace("{bot_name}", render_common_variables("{bot_mention}", query.from_user, me))
    # Replace the longer phrase first via a placeholder so the "Lexi" link
    # cannot be nested inside the "Lexi Anime" anchor.
    rendered = rendered.replace("Lexi Anime", "__LEXI_ANIME_LINK__")
    rendered = rendered.replace("Lexi", '<a href="https://t.me/lexxiowner">Lexi</a>')
    rendered = rendered.replace("__LEXI_ANIME_LINK__", '<a href="https://t.me/lexiAnime">Lexi Anime</a>')
    back_markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="《 BACK", callback_data="start:about_back")]])
    try:
        if query.message.photo or query.message.animation:
            await query.message.edit_caption(caption=rendered, parse_mode="HTML", reply_markup=back_markup)
        else:
            await query.message.edit_text(rendered, parse_mode="HTML", reply_markup=back_markup)
    except TelegramAPIError:
        pass

@router.callback_query(F.data == "start:about_back")
async def start_about_back(query: CallbackQuery, settings: Settings, database):
    await query.answer()
    user = query.from_user
    msg = query.message
    if not user or not msg or await FileRepository(database.db).is_banned(user.id):
        return
    cfg = await database.db.settings.find_one({"key": "start_message"}) or {}
    if not cfg.get("enabled", True):
        return
    me = await query.bot.get_me()
    rows = []
    url = cfg.get("button1_url", cfg.get("button_url", "http://t.me/lexiAnime"))
    label = cfg.get("button1_text", cfg.get("button_text", "📟 UPDATE CHANNEL"))
    parsed = urlparse(url)
    configured_buttons = []
    if cfg.get("button1_enabled", cfg.get("button_enabled", True)) and label and parsed.scheme in ("http", "https") and parsed.netloc:
        configured_buttons.append(InlineKeyboardButton(text=label, url=url))
    url2 = cfg.get("button2_url", "")
    label2 = cfg.get("button2_text", "")
    parsed2 = urlparse(url2)
    if cfg.get("button2_enabled", False) and label2 and parsed2.scheme in ("http", "https") and parsed2.netloc:
        configured_buttons.append(InlineKeyboardButton(text=label2, url=url2))
    if configured_buttons:
        rows.append(configured_buttons)
    if cfg.get("about_enabled", True):
        rows.append([InlineKeyboardButton(text=cfg.get("about_button_text", "ᴀʙᴏᴜᴛ"), callback_data="start:about")])
    markup = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    raw = cfg.get("text") or '<b>Hey {user_mention}✨</b>\n\n<i>Welcome to the fastest and most secure file store bot!.</i>'
    rendered = render_common_variables(raw, user, me)
    try:
        if msg.photo:
            await msg.edit_caption(caption=rendered, parse_mode="HTML", reply_markup=markup)
        elif msg.animation:
            await msg.edit_caption(caption=rendered, parse_mode="HTML", reply_markup=markup)
        else:
            await msg.edit_text(rendered, parse_mode="HTML", reply_markup=markup)
    except TelegramAPIError:
        pass

@router.chat_join_request()
async def remember_pending_join_request(event, database):
    # Telegram emits this only when the bot has the appropriate channel admin rights.
    await database.db.pending_join_requests.update_one(
        {"chat_id": event.chat.id, "user_id": event.from_user.id},
        {"$set": {"chat_id": event.chat.id, "user_id": event.from_user.id,
                  "requested_at": datetime.now(timezone.utc)}},
        upsert=True,
    )

async def _send_force_join_post(bot, user_id: int, cfg: dict, text: str, markup: InlineKeyboardMarkup):
    """Send a replacement Force Join post before removing the previous one."""
    try:
        if cfg.get("poster_file_id"):
            return await bot.send_animation(user_id, cfg["poster_file_id"], caption=text, reply_markup=markup, parse_mode="HTML")
        if cfg.get("poster_photo_id"):
            return await bot.send_photo(user_id, cfg["poster_photo_id"], caption=text, reply_markup=markup, parse_mode="HTML")
        return await bot.send_message(user_id, text, reply_markup=markup, parse_mode="HTML")
    except TelegramAPIError:
        log.warning("Configured Force Join poster could not be sent; using text post", exc_info=True)
        return await bot.send_message(user_id, text, reply_markup=markup, parse_mode="HTML")


@router.callback_query(F.data.startswith("forcejoin:check:"))
async def forcejoin_check(query:CallbackQuery,settings:Settings,database,bot):
    await query.answer()
    payload=query.data.split(":",2)[2]
    if not query.from_user or await FileRepository(database.db).is_banned(query.from_user.id):
        return

    user_id = query.from_user.id
    old_post = query.message
    await _cancel_gate_animation(bot, user_id, payload)
    force_cfg = await database.db.settings.find_one({"key": "force_join"}) or {}
    channels = await effective_force_join_channels(database, settings) if force_cfg.get("enabled", False) else []
    animation_cfg = await database.db.settings.find_one({"key": "animation"}) or {}
    animation_enabled = bool(animation_cfg.get("enabled"))
    animation_mode = animation_cfg.get("mode", "force_join_poster")
    animation_post = None

    # Start the selected animation before checking memberships so it remains visible
    # while Telegram membership checks are in progress.
    if old_post and animation_enabled:
        if animation_mode == "new_message":
            await _start_gate_animation(bot, user_id, payload, old_post, "", InlineKeyboardMarkup(inline_keyboard=[]), animation_cfg)
        else:
            frames = animation_cfg.get("frames")
            if not isinstance(frames, list) or len(frames) != 3:
                frames = [".", "..", "..."]
            first = f"{html.escape(str(animation_cfg.get('prefix') or 'Checking..'))} {html.escape(str(frames[0]))}"
            try:
                if force_cfg.get("poster_file_id"):
                    animation_post = await bot.send_animation(user_id, force_cfg["poster_file_id"], caption=f"<i>{first}</i>", parse_mode="HTML")
                elif force_cfg.get("poster_photo_id"):
                    animation_post = await bot.send_photo(user_id, force_cfg["poster_photo_id"], caption=f"<i>{first}</i>", parse_mode="HTML")
                else:
                    animation_post = await bot.send_message(user_id, f"<i>{first}</i>", parse_mode="HTML")
                await _start_gate_animation(bot, user_id, payload, animation_post, "", InlineKeyboardMarkup(inline_keyboard=[]), animation_cfg, animation_only=True)
                # Keep the old Force Join post visible throughout the animation.
                # It is deleted only after the replacement post is ready.
            except TelegramAPIError:
                log.warning("Could not create Force Join animation poster", exc_info=True)
                animation_post = None

    missing=[] if await is_owner_or_moderator(database.db, user_id, settings) else await join_status(bot,user_id,channels,database.db)
    if animation_enabled:
        # Keep the verification animation alive for a visible frame cycle before
        # stopping it and publishing the updated remaining-channel post.
        frames_for_wait = animation_cfg.get("frames")
        if not isinstance(frames_for_wait, list) or len(frames_for_wait) != 3:
            frames_for_wait = [".", "..", "..."]
        try:
            frame_speed = min(1.0, max(0.10, float(animation_cfg.get("speed", 0.10))))
        except (TypeError, ValueError):
            frame_speed = 0.10
        await asyncio.sleep(max(0.8, frame_speed * len(frames_for_wait)))
    if missing:
        join_buttons = []
        for index, channel in enumerate(missing):
            channel_cfg = await database.db.settings.find_one({"key": "force_join_channel", "channel": channel}) or {}
            target = channel_cfg.get("button_url")
            # Older entries and public chats stored as numeric IDs may not have
            # a usable URL on their config record. Resolve the current chat to
            # recover its public username/link before omitting a Join button.
            chat = None
            try:
                chat_arg = int(channel) if channel.lstrip("-").isdigit() else channel
                chat = await bot.get_chat(chat_arg)
            except (TelegramAPIError, ValueError):
                pass
            if not target and chat and chat.username:
                target = f"https://t.me/{chat.username}"
            if not target and channel.startswith(("https://t.me/", "http://t.me/")):
                target = channel
            if not target and not channel.lstrip("-").isdigit():
                target = f"https://t.me/{channel.lstrip('@')}"
            if target:
                label = force_join_button_label(channel_cfg, index + 1)
                join_buttons.append(InlineKeyboardButton(text=label, url=target))
        rows = [join_buttons[i:i+2] for i in range(0, len(join_buttons), 2)]
        rows.append([InlineKeyboardButton(text=force_cfg.get("verify_text") or "ɪ ᴊᴏɪɴᴇᴅ — ᴄʜᴇᴄᴋ ᴀɢᴀɪɴ", callback_data=f"forcejoin:check:{payload}")])
        me = await bot.get_me()
        raw_text = str(force_cfg.get("message") or "Hey {mention}\nPlease Join My {remaining_count} Channel's To Use Me!")
        rendered = render_common_variables(raw_text, query.from_user, me).replace("{remaining_count}", str(len(missing)))
        markup = InlineKeyboardMarkup(inline_keyboard=rows)

        if animation_enabled and animation_mode == "force_join_poster" and animation_post:
            # Stop the animation, then turn its poster into the updated prompt.
            # The old Force Join post remains until this replacement is ready.
            await _cancel_gate_animation(bot, user_id, payload)
            try:
                if animation_post.photo or animation_post.animation or animation_post.document:
                    await bot.edit_message_caption(chat_id=user_id, message_id=animation_post.message_id, caption=rendered, parse_mode="HTML", reply_markup=markup)
                else:
                    await bot.edit_message_text(chat_id=user_id, message_id=animation_post.message_id, text=rendered, parse_mode="HTML", reply_markup=markup)
            except TelegramAPIError:
                log.warning("Could not restore Force Join text on animation post", exc_info=True)
                animation_post = await _send_force_join_post(bot, user_id, force_cfg, rendered, markup)
            if old_post and animation_post.message_id != old_post.message_id:
                try:
                    await old_post.delete()
                except TelegramAPIError:
                    pass
        else:
            # Publish the replacement first, then instantly remove the temporary
            # New Message animation and the previous Force Join post.
            separate_animation_id = None
            if animation_enabled and animation_mode == "new_message":
                separate_animation_id = await _cancel_gate_animation(
                    bot, user_id, payload, delete_separate=False
                )
            else:
                await _cancel_gate_animation(bot, user_id, payload)
            new_post = await _send_force_join_post(bot, user_id, force_cfg, rendered, markup)
            if separate_animation_id:
                try:
                    await bot.delete_message(chat_id=user_id, message_id=separate_animation_id)
                except TelegramAPIError:
                    pass
            if old_post and new_post.message_id != old_post.message_id:
                try:
                    await old_post.delete()
                except TelegramAPIError:
                    pass
        return

    # Verification succeeded: remove both the old Force Join post and any temporary
    # animation/poster before delivering the requested file or batch.
    await _cancel_gate_animation(bot, user_id, payload)
    if animation_post and animation_post.message_id != (old_post.message_id if old_post else None):
        try:
            await animation_post.delete()
        except TelegramAPIError:
            pass
    repo=FileRepository(database.db)
    if payload.startswith("file_"):record=await repo.get_file(payload[5:])
    elif payload.startswith("batch_"):record=await repo.get_batch(payload[6:])
    else:return
    if not record:
        if old_post:
            try: await old_post.delete()
            except TelegramAPIError: pass
        await bot.send_message(user_id,"This link is invalid or expired.")
        return
    request_anchor = old_post.message_id if old_post else query.id
    request_key = f"forcejoin:{user_id}:{request_anchor}:{payload}"
    if not await claim_delivery_request(database.db, request_key, user_id, payload):
        return
    await _mark_verified(database.db, user_id, channels)
    if old_post:
        try: await old_post.delete()
        except TelegramAPIError: pass
    success = False
    try:
        result=await deliver_payload(bot,database,settings,user_id,payload,record,request_key=request_key)
        if payload.startswith("batch_") and result[0]==0:
            await bot.send_message(user_id,"None of the batch files could be delivered.")
        elif payload.startswith("file_") and result[0] == 0:
            await bot.send_message(user_id,"This file is currently unavailable. The source message may have been deleted or become inaccessible.")
        success = result[0] > 0
    except TelegramAPIError:
        log.exception("Delivery after Force Join failed")
        await bot.send_message(user_id,"File delivery failed. Contact the owner.")
    except Exception:
        log.exception("Unexpected delivery failure after Force Join")
        await bot.send_message(user_id,"Delivery failed due to a temporary error.")
    finally:
        try: await finish_delivery_request(database.db, request_key, success)
        except Exception: log.exception("Could not update Force Join delivery request status")

