"""Create permanent deeplinks by copying incoming messages to the source channel."""
import logging
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramAPIError

from app.config import Settings
from app.database.files import FileRepository

router = Router(name="file")
logger = logging.getLogger(__name__)


class FileStates(StatesGroup):
    waiting_for_message = State()


@router.message(Command("file"))
async def file_command(message: Message, state: FSMContext, settings: Settings, database) -> None:
    if message.from_user is None:
        return
    repo = FileRepository(database)
    if message.from_user.id != settings.owner_id:
        mod = await database.moderators.find_one({"user_id": message.from_user.id})
        if not mod:
            await message.answer("You are not allowed to create file links.")
            return
    if settings.source_channel_id is None:
        await message.answer("File storage is not configured yet. Set SOURCE_CHANNEL_ID first.")
        return
    await state.set_state(FileStates.waiting_for_message)
    await message.answer("Send one file or one supported message to generate its file link.")


@router.message(FileStates.waiting_for_message, F.text.startswith("/"))
async def file_command_while_waiting(message: Message) -> None:
    await message.answer("Please send the file/message, or use /cancel to leave this step.")


@router.message(FileStates.waiting_for_message, Command("cancel"))
async def cancel_file(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("File link creation cancelled.")


@router.message(FileStates.waiting_for_message)
async def receive_file_source(message: Message, state: FSMContext, settings: Settings, bot, database) -> None:
    if message.from_user is None or settings.source_channel_id is None:
        await state.clear()
        return
    file_name = None
    if message.document:
        file_name = message.document.file_name
    elif message.video:
        file_name = message.video.file_name
    elif message.audio:
        file_name = message.audio.file_name
    try:
        copied = await bot.copy_message(
            chat_id=settings.source_channel_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
        repo = FileRepository(database)
        record = await repo.save_file(
            source_chat_id=settings.source_channel_id,
            source_message_id=copied.message_id,
            created_by=message.from_user.id,
            file_name=file_name,
        )
        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start=file_{record['file_key']}"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="ＣＯＰＹ", copy_text={"text": link})]])
        await message.answer(link, reply_markup=keyboard, disable_web_page_preview=True)
    except TelegramAPIError:
        logger.exception("Could not copy source message to configured storage channel")
        await message.answer("Could not store this message. Check that the bot is an administrator of the source channel.")
    except Exception:
        logger.exception("Unexpected file link creation failure")
        await message.answer("Something went wrong while saving this file. Please try again.")
    finally:
        await state.clear()
