"""Start command and file-deeplink delivery."""
import logging
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.exceptions import TelegramAPIError

from app.config import Settings
from app.database.files import FileRepository

router = Router(name="start")
logger = logging.getLogger(__name__)


@router.message(CommandStart())
async def start_command(message: Message, command, settings: Settings, database, bot) -> None:
    user = message.from_user
    if user is None:
        return
    repo = FileRepository(database)
    await repo.save_user(user)
    if await repo.is_banned(user.id):
        return

    payload = command.args or ""
    if payload.startswith("file_"):
        key = payload[5:]
        if not key or len(key) > 40:
            await message.answer("This file link is invalid or expired.")
            return
        record = await repo.get_file(key)
        if not record:
            await message.answer("This file link is invalid or expired.")
            return
        # Force-join checks are a separate feature and must be added before production.
        try:
            await bot.copy_message(
                chat_id=message.chat.id,
                from_chat_id=record["source_chat_id"],
                message_id=record["source_message_id"],
            )
        except TelegramAPIError:
            logger.exception("File delivery failed for key %s", key)
            await message.answer("This file is currently unavailable. Please contact the bot owner.")
        return

    if user.id == settings.owner_id or await database.moderators.find_one({"user_id": user.id}):
        return
    enabled = await repo.get_setting("start_message_enabled", True)
    if enabled:
        text = await repo.get_setting("start_message_text", "👋 Welcome! Send a valid file link to receive your file.")
        await message.answer(text)
