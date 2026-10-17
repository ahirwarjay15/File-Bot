"""Main control plane for managing isolated File-Bot worker bots."""
import asyncio
import copy
import json
import logging
import os
from types import SimpleNamespace
from contextlib import suppress
from datetime import datetime, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand, BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)
from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from app.config import Settings
from app.database.connection import Database
from app.handlers.start import router as start_router
from app.handlers.file import router as file_router
from app.handlers.batch import router as batch_router
from app.handlers.admin import router as admin_router
from app.handlers.broadcast import router as broadcast_router
from app.handlers.shortener import router as shortener_router
from app.handlers.misc import router as misc_router

log = logging.getLogger(__name__)
router = Router(name="main_control_plane")


class AddWorker(StatesGroup):
    token = State()
    storage_channel = State()


def _cipher() -> Fernet:
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY must be configured for the control plane")
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY must be a valid Fernet key") from exc


def _owner_id() -> int:
    value = os.getenv("OWNER_ID", "").strip()
    if not value.isdigit() or int(value) <= 0:
        raise RuntimeError("OWNER_ID must be a positive Telegram user ID")
    return int(value)


def _pool_uri(index: int) -> str:
    return os.getenv(f"WORKER_MONGODB_URI_{index}", "").strip()


def _keyboard(rows):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=data) for label, data in row]
        for row in rows
    ])


async def _is_owner(user) -> bool:
    return bool(user and user.id == _owner_id())


async def _worker_docs(db):
    return await db.managed_bots.find({}).sort("created_at", 1).to_list(length=200)


def _worker_label(doc):
    username = doc.get("username")
    return f"@{username}" if username else doc.get("display_name") or str(doc.get("bot_id"))


async def _home(message_or_query, db):
    docs = await _worker_docs(db)
    rows = []
    for doc in docs:
        status = "🟢" if doc.get("status", "active") == "active" else "⏸"
        rows.append([(f"{status} {_worker_label(doc)}", f"worker:{doc['bot_id']}")])
    rows.append([("➕ Add Worker Bot", "add_worker")])
    rows.append([("📦 Backup All Bots", "backup_all")])
    text = "<b>Main Bot · Worker Control Center</b>\n\nChoose a worker to manage its status, storage, and settings."
    if isinstance(message_or_query, Message):
        await message_or_query.answer(text, reply_markup=_keyboard(rows), parse_mode="HTML")
    elif message_or_query.message:
        await message_or_query.message.edit_text(text, reply_markup=_keyboard(rows), parse_mode="HTML")


async def _set_commands(bot):
    await bot.set_my_commands([
        BotCommand(command="start", description="Start bot"),
        BotCommand(command="file", description="Create a file link"),
        BotCommand(command="batch", description="Create a batch link"),
        BotCommand(command="shortener", description="Shorten a URL"),
        BotCommand(command="broadcast", description="Broadcast to users"),
        BotCommand(command="stats", description="View bot statistics"),
        BotCommand(command="ban", description="Ban a user"),
        BotCommand(command="unban", description="Unban a user"),
        BotCommand(command="cancel", description="Cancel current action"),
    ])


class WorkerManager:
    def __init__(self, control_db, owner_id, cipher):
        self.control_db = control_db
        self.owner_id = owner_id
        self.cipher = cipher
        self.instances = {}
        self.lock = asyncio.Lock()

    async def start_worker(self, doc):
        bot_id = int(doc["bot_id"])
        if bot_id in self.instances or doc.get("status", "active") != "active":
            return
        token = self.cipher.decrypt(doc["token_enc"].encode()).decode()
        uri = _pool_uri(int(doc["pool_index"]))
        if not uri:
            log.error("Worker %s has no configured database pool %s", bot_id, doc.get("pool_index"))
            return
        settings = Settings(
            BOT_TOKEN=token,
            OWNER_ID=self.owner_id,
            MONGODB_URI=uri,
            MONGODB_DB_NAME=doc.get("database_name", "file_bot"),
            SOURCE_CHANNEL_ID=int(doc["source_channel_id"]),
        )
        bot = Bot(token=token, default=DefaultBotProperties(link_preview_is_disabled=True))
        database = Database(settings)
        try:
            await database.connect()
            dp = Dispatcher(storage=MemoryStorage())
            dp["settings"] = settings
            dp["database"] = database
            # Worker bots do not register the settings router: configuration is controlled by Main Bot.
            guard = Router(name="worker_settings_guard")
            @guard.message(Command("settings"))
            async def settings_redirect(message: Message):
                await message.answer("Worker settings are managed from the Main Bot. Open Main Bot → /settings.")
            for item in (start_router, file_router, batch_router, admin_router, broadcast_router, shortener_router, guard, misc_router):
                dp.include_router(copy.deepcopy(item))
            await _set_commands(bot)
            await bot.delete_webhook(drop_pending_updates=False)
            task = asyncio.create_task(
                dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), handle_signals=False),
                name=f"worker-poll-{bot_id}",
            )
            self.instances[bot_id] = {
                "bot": bot, "dp": dp, "database": database, "task": task,
                "username": doc.get("username"), "pool_index": doc.get("pool_index"),
            }
            await self.control_db.managed_bots.update_one(
                {"bot_id": bot_id},
                {"$set": {"runtime_status": "running", "last_started_at": datetime.now(timezone.utc), "last_error": None}},
            )
            log.info("Worker started: bot_id=%s pool=%s", bot_id, doc.get("pool_index"))
        except Exception as exc:
            await database.close()
            await bot.session.close()
            log.exception("Worker startup failed for bot_id=%s", bot_id)
            await self.control_db.managed_bots.update_one(
                {"bot_id": bot_id},
                {"$set": {"runtime_status": "error", "last_error": type(exc).__name__}},
            )

    async def stop_worker(self, bot_id):
        instance = self.instances.pop(int(bot_id), None)
        if not instance:
            return
        with suppress(Exception):
            await instance["dp"].stop_polling()
        instance["task"].cancel()
        with suppress(asyncio.CancelledError, Exception):
            await instance["task"]
        await instance["database"].close()
        await instance["bot"].session.close()
        await self.control_db.managed_bots.update_one(
            {"bot_id": int(bot_id)}, {"$set": {"runtime_status": "stopped"}}
        )

    async def reconcile(self):
        async with self.lock:
            docs = await _worker_docs(self.control_db)
            wanted = {int(d["bot_id"]): d for d in docs if d.get("status", "active") == "active"}
            for bot_id in list(self.instances):
                if bot_id not in wanted:
                    await self.stop_worker(bot_id)
            for bot_id, doc in wanted.items():
                if bot_id not in self.instances:
                    await self.start_worker(doc)

    async def shutdown(self):
        for bot_id in list(self.instances):
            await self.stop_worker(bot_id)


def _runtime_db(manager, bot_id):
    instance = manager.instances.get(int(bot_id))
    return instance["database"].db if instance else None


@router.message(Command("start"))
async def start_main(message: Message, database):
    if await _is_owner(message.from_user):
        await message.answer("Main Bot is online. Use /settings to manage Worker Bots.")


@router.message(Command("settings"))
async def settings_main(message: Message, database):
    if not await _is_owner(message.from_user):
        return
    await _home(message, database.db)


@router.callback_query(F.data == "add_worker")
async def add_worker_start(query: CallbackQuery, state: FSMContext):
    if not await _is_owner(query.from_user):
        await query.answer("Not authorized", show_alert=True)
        return
    await state.set_state(AddWorker.token)
    await query.message.answer("Send the Worker Bot API token from BotFather. It will be encrypted before storage.")
    await query.answer()


@router.message(StateFilter(AddWorker.token))
async def add_worker_token(message: Message, state: FSMContext):
    if not await _is_owner(message.from_user):
        await state.clear()
        return
    token = (message.text or "").strip()
    if not token or ":" not in token or len(token) < 30:
        await message.answer("That token format looks invalid. Send the full token from BotFather, or /cancel.")
        return
    test_bot = Bot(token=token)
    try:
        me = await test_bot.get_me()
        if not me.is_bot or not me.username:
            await message.answer("Telegram did not return a valid bot account. Check the token.")
            return
        existing = await message.bot.get_me()
        # The manager rejects duplicate bot IDs in the control database when saving.
        await state.update_data(token=token, bot_id=me.id, username=me.username, display_name=me.full_name)
        await state.set_state(AddWorker.storage_channel)
        await message.answer(
            f"Validated @{me.username}.\nNow send its private storage channel ID (usually starts with -100). "
            "Add this worker bot as channel administrator first.\n\nMain bot: @{existing.username}"
        )
    except Exception:
        await message.answer("Telegram rejected this token or the API is temporarily unavailable. Check the token and try again.")
    finally:
        await test_bot.session.close()


@router.message(StateFilter(AddWorker.storage_channel))
async def add_worker_channel(message: Message, state: FSMContext, database):
    if not await _is_owner(message.from_user):
        await state.clear()
        return
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer("Send a numeric channel ID (example format: -1001234567890), or /cancel.")
        return
    channel_id = int(raw)
    data = await state.get_data()
    token = data.get("token")
    if not token:
        await state.clear()
        await message.answer("Setup expired. Start again with /settings → Add Worker Bot.")
        return
    test_bot = Bot(token=token)
    try:
        chat = await test_bot.get_chat(channel_id)
        member = await test_bot.get_chat_member(channel_id, (await test_bot.get_me()).id)
        if member.status not in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR):
            await message.answer("The worker bot must be an administrator in that storage channel before continuing.")
            return
        await state.update_data(source_channel_id=channel_id, channel_title=chat.title or str(channel_id))
        assigned = {int(x["pool_index"]) for x in await _worker_docs(database.db)}
        pool_rows = []
        for i in range(1, 16):
            if _pool_uri(i) and i not in assigned:
                pool_rows.append([(f"Database pool {i}", f"addpool:{i}")])
        if not pool_rows:
            await message.answer("No unused WORKER_MONGODB_URI_1…15 is configured. Add the 15 worker database URIs to the Main Bot service environment first.")
            return
        await message.answer("Channel verified. Select an unused, isolated database pool:", reply_markup=_keyboard(pool_rows))
    except Exception:
        await message.answer("Could not verify that storage channel. Ensure the worker bot is in the channel as admin and the ID is correct.")
    finally:
        await test_bot.session.close()


@router.callback_query(F.data.startswith("addpool:"))
async def add_worker_pool(query: CallbackQuery, state: FSMContext, database, manager: WorkerManager):
    if not await _is_owner(query.from_user):
        await query.answer("Not authorized", show_alert=True)
        return
    index = int(query.data.split(":", 1)[1])
    if index < 1 or index > 15 or not _pool_uri(index):
        await query.answer("Database pool is not configured", show_alert=True)
        return
    data = await state.get_data()
    if not data.get("token") or not data.get("source_channel_id"):
        await state.clear()
        await query.answer("Setup expired. Start again.", show_alert=True)
        return
    if await database.db.managed_bots.find_one({"bot_id": data["bot_id"]}):
        await state.clear()
        await query.message.answer("This bot is already registered.")
        await query.answer()
        return
    if await database.db.managed_bots.find_one({"pool_index": index}):
        await query.answer("That database pool is already assigned", show_alert=True)
        return
    doc = {
        "bot_id": int(data["bot_id"]),
        "username": data["username"],
        "display_name": data.get("display_name"),
        "token_enc": manager.cipher.encrypt(data["token"].encode()).decode(),
        "pool_index": index,
        "database_name": "file_bot",
        "source_channel_id": int(data["source_channel_id"]),
        "source_channel_title": data.get("channel_title"),
        "status": "active",
        "runtime_status": "starting",
        "created_at": datetime.now(timezone.utc),
    }
    await database.db.managed_bots.insert_one(doc)
    await state.clear()
    await query.message.edit_text(f"Added @{doc['username']} to isolated database pool {index}. Starting worker…")
    await query.answer("Worker registered")
    await manager.reconcile()


@router.callback_query(F.data.startswith("worker:"))
async def worker_details(query: CallbackQuery, database, manager: WorkerManager):
    if not await _is_owner(query.from_user):
        await query.answer("Not authorized", show_alert=True)
        return
    bot_id = int(query.data.split(":", 1)[1])
    doc = await database.db.managed_bots.find_one({"bot_id": bot_id})
    if not doc:
        await query.answer("Worker not found", show_alert=True)
        return
    status = doc.get("status", "active")
    rows = [
        [("⚙️ Worker Settings", f"cfg:{bot_id}")],
        [("⏸ Pause" if status == "active" else "▶️ Resume", f"toggle:{bot_id}")],
        [("📦 Backup Data", f"backup:{bot_id}")],
        [("🗑 Remove Worker", f"remove:{bot_id}")],
        [("← Back", "home")],
    ]
    text = (
        f"<b>{_worker_label(doc)}</b>\n"
        f"Bot ID: <code>{bot_id}</code>\n"
        f"Runtime: <b>{doc.get('runtime_status', 'pending')}</b>\n"
        f"Status: {status}\n"
        f"Database pool: {doc.get('pool_index')}\n"
        f"Storage: {doc.get('source_channel_title') or doc.get('source_channel_id')}"
    )
    await query.message.edit_text(text, reply_markup=_keyboard(rows), parse_mode="HTML")
    await query.answer()


@router.callback_query(F.data.startswith("toggle:"))
async def toggle_worker(query: CallbackQuery, database, manager: WorkerManager):
    if not await _is_owner(query.from_user):
        await query.answer("Not authorized", show_alert=True)
        return
    bot_id = int(query.data.split(":", 1)[1])
    doc = await database.db.managed_bots.find_one({"bot_id": bot_id})
    if not doc:
        await query.answer("Worker not found", show_alert=True)
        return
    new_status = "paused" if doc.get("status", "active") == "active" else "active"
    await database.db.managed_bots.update_one({"bot_id": bot_id}, {"$set": {"status": new_status}})
    await manager.reconcile()
    await query.answer(f"Worker {new_status}")
    await worker_details_refresh(query, database.db, bot_id)


async def worker_details_refresh(query, db, bot_id):
    doc = await db.managed_bots.find_one({"bot_id": int(bot_id)})
    if not doc or not query.message:
        return
    status = doc.get("status", "active")
    await query.message.edit_text(
        f"<b>{_worker_label(doc)}</b>\nBot ID: <code>{bot_id}</code>\n"
        f"Runtime: <b>{doc.get('runtime_status', 'pending')}</b>\nStatus: {status}\n"
        f"Database pool: {doc.get('pool_index')}\nStorage: {doc.get('source_channel_title') or doc.get('source_channel_id')}",
        reply_markup=_keyboard([
            [("⚙️ Worker Settings", f"cfg:{bot_id}")],
            [("⏸ Pause" if status == "active" else "▶️ Resume", f"toggle:{bot_id}")],
            [("📦 Backup Data", f"backup:{bot_id}")],
            [("🗑 Remove Worker", f"remove:{bot_id}")],
            [("← Back", "home")],
        ]),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("remove:"))
async def remove_worker(query: CallbackQuery, database, manager: WorkerManager):
    if not await _is_owner(query.from_user):
        await query.answer("Not authorized", show_alert=True)
        return
    bot_id = int(query.data.split(":", 1)[1])
    doc = await database.db.managed_bots.find_one({"bot_id": bot_id})
    if not doc:
        await query.answer("Worker not found", show_alert=True)
        return
    await database.db.managed_bots.delete_one({"bot_id": bot_id})
    await manager.stop_worker(bot_id)
    await query.answer("Worker removed from Main Bot")
    await _home(query, database.db)


@router.callback_query(F.data.startswith("cfg:"))
async def worker_settings(query: CallbackQuery, database, manager: WorkerManager):
    if not await _is_owner(query.from_user):
        await query.answer("Not authorized", show_alert=True)
        return
    bot_id = int(query.data.split(":", 1)[1])
    doc = await database.db.managed_bots.find_one({"bot_id": bot_id})
    worker_db = _runtime_db(manager, bot_id)
    if not doc or worker_db is None:
        await query.answer("Worker is not running; start it before editing settings.", show_alert=True)
        return
    start = await worker_db.settings.find_one({"key": "start_message"}) or {"enabled": True}
    force = await worker_db.settings.find_one({"key": "force_join"}) or {"enabled": False}
    auto = await worker_db.settings.find_one({"key": "auto_delete"}) or {"enabled": False, "minutes": 30}
    short = await worker_db.settings.find_one({"key": "shortener"}) or {"enabled": False}
    await query.message.edit_text(
        f"<b>Settings · {_worker_label(doc)}</b>\n\n"
        f"Start message: {'ON' if start.get('enabled', True) else 'OFF'}\n"
        f"Force Join: {'ON' if force.get('enabled', False) else 'OFF'}\n"
        f"Auto Delete: {'ON' if auto.get('enabled', False) else 'OFF'} ({auto.get('minutes', 30)} min)\n"
        f"Shortener: {'ON' if short.get('enabled', False) else 'OFF'}",
        reply_markup=_keyboard([
            [("Toggle Start Message", f"set:{bot_id}:start_message")],
            [("Toggle Force Join", f"set:{bot_id}:force_join")],
            [("Toggle Auto Delete", f"set:{bot_id}:auto_delete")],
            [("Toggle Shortener", f"set:{bot_id}:shortener")],
            [("← Worker", f"worker:{bot_id}")],
        ]),
        parse_mode="HTML",
    )
    await query.answer()


@router.callback_query(F.data.startswith("set:"))
async def set_worker_setting(query: CallbackQuery, manager: WorkerManager):
    if not await _is_owner(query.from_user):
        await query.answer("Not authorized", show_alert=True)
        return
    _, raw_id, key = query.data.split(":", 2)
    bot_id = int(raw_id)
    worker_db = _runtime_db(manager, bot_id)
    if worker_db is None:
        await query.answer("Worker is not running", show_alert=True)
        return
    defaults = {
        "start_message": {"enabled": True, "text": "<b>Hey {user_mention}✨</b>\n\n<i>Welcome to the fastest and most secure file store bot!</i>"},
        "force_join": {"enabled": False, "channels": []},
        "auto_delete": {"enabled": False, "minutes": 30},
        "shortener": {"enabled": False},
    }
    if key not in defaults:
        await query.answer("Unknown setting", show_alert=True)
        return
    current = await worker_db.settings.find_one({"key": key}) or defaults[key]
    await worker_db.settings.update_one(
        {"key": key},
        {"$set": {"key": key, "enabled": not bool(current.get("enabled", defaults[key]["enabled"]))},
         "$setOnInsert": defaults[key]},
        upsert=True,
    )
    await query.answer("Setting updated")
    # Refresh the settings panel through the existing callback handler.
    query.data = f"cfg:{bot_id}"
    await worker_settings(query, database=SimpleNamespace(db=manager.control_db), manager=manager)


@router.callback_query(F.data == "home")
async def back_home(query: CallbackQuery, database):
    if not await _is_owner(query.from_user):
        await query.answer("Not authorized", show_alert=True)
        return
    await _home(query, database.db)
    await query.answer()



async def _export_db(db, label):
    lines = [f"FILE BOT BACKUP: {label}", f"Created: {datetime.now(timezone.utc).isoformat()}", ""]
    for name in sorted(await db.list_collection_names()):
        lines.append(f"\\n===== COLLECTION: {name} =====")
        cursor = db[name].find({})
        async for document in cursor:
            if name == "managed_bots":
                document.pop("token_enc", None)
            lines.append(json.dumps(document, ensure_ascii=False, default=str, separators=(",", ":")))
    return "\\n".join(lines)


async def _send_backup(message_or_query, database, manager, bot_id=None):
    chunks = []
    chunks.append(await _export_db(database.db, "Main database / bot registry"))
    docs = await _worker_docs(database.db)
    selected = [d for d in docs if bot_id is None or int(d["bot_id"]) == int(bot_id)]
    for doc in selected:
        runtime = manager.instances.get(int(doc["bot_id"]))
        if runtime:
            chunks.append(await _export_db(runtime["database"].db, _worker_label(doc)))
        else:
            chunks.append(f"Worker {_worker_label(doc)} (pool {doc.get('pool_index')}) is not running; its live database was not exported.")
    payload = "\\n\\n".join(chunks)
    if len(payload.encode("utf-8")) > 45 * 1024 * 1024:
        target = message_or_query.message if isinstance(message_or_query, CallbackQuery) else message_or_query
        await target.answer("Backup exceeds Telegram's single-file upload limit. Use a server-side export for this dataset.")
        return
    filename = "filebot_all_bots_backup.txt" if bot_id is None else f"filebot_worker_{bot_id}_backup.txt"
    target = message_or_query.message if isinstance(message_or_query, CallbackQuery) else message_or_query
    await target.answer_document(
        BufferedInputFile(payload.encode("utf-8"), filename=filename),
        caption="Backup complete. Worker bot tokens are excluded from the export."
    )


@router.callback_query(F.data == "backup_all")
async def backup_all(query: CallbackQuery, database, manager: WorkerManager):
    if not await _is_owner(query.from_user):
        await query.answer("Not authorized", show_alert=True)
        return
    await query.answer("Preparing backup…")
    await _send_backup(query, database, manager)


@router.callback_query(F.data.startswith("backup:"))
async def backup_worker(query: CallbackQuery, database, manager: WorkerManager):
    if not await _is_owner(query.from_user):
        await query.answer("Not authorized", show_alert=True)
        return
    bot_id = int(query.data.split(":", 1)[1])
    await query.answer("Preparing worker backup…")
    await _send_backup(query, database, manager, bot_id=bot_id)


@router.message(Command("backup"))
async def backup_command(message: Message, database, manager: WorkerManager):
    if not await _is_owner(message.from_user):
        return
    await _send_backup(message, database, manager)


async def run_control_plane():
    owner_id = _owner_id()
    cipher = _cipher()
    main_token = os.getenv("MAIN_BOT_TOKEN", "").strip()
    main_uri = os.getenv("MAIN_MONGODB_URI", "").strip()
    if not main_token or not main_uri:
        raise RuntimeError("MAIN_BOT_TOKEN and MAIN_MONGODB_URI must be configured")
    settings = Settings(BOT_TOKEN=main_token, OWNER_ID=owner_id, MONGODB_URI=main_uri, MONGODB_DB_NAME="file_bot")
    bot = Bot(token=main_token, default=DefaultBotProperties(link_preview_is_disabled=True))
    database = Database(settings)
    manager = None
    try:
        await database.connect()
        await database.db.managed_bots.create_index("bot_id", unique=True)
        await database.db.managed_bots.create_index("pool_index", unique=True)
        manager = WorkerManager(database.db, owner_id, cipher)
        dp = Dispatcher(storage=MemoryStorage())
        dp["settings"] = settings
        dp["database"] = database
        dp["manager"] = manager
        dp.include_router(router)
        await bot.delete_webhook(drop_pending_updates=False)
        await bot.set_my_commands([
            BotCommand(command="start", description="Main control center"),
            BotCommand(command="settings", description="Manage worker bots"),
        ])
        await manager.reconcile()
        reconciler = asyncio.create_task(_reconcile_forever(manager), name="worker-reconciler")
        log.info("Main control plane polling started")
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), handle_signals=False)
        finally:
            reconciler.cancel()
            with suppress(asyncio.CancelledError):
                await reconciler
    finally:
        if manager:
            await manager.shutdown()
        await database.close()
        await bot.session.close()


async def _reconcile_forever(manager):
    while True:
        await asyncio.sleep(10)
        try:
            await manager.reconcile()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Worker reconciliation failed")
