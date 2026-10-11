"""Create permanent deeplinks by copying messages into the source channel."""
import logging
from aiogram import F,Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State,StatesGroup
from aiogram.types import Message,InlineKeyboardMarkup,InlineKeyboardButton,CopyTextButton
from aiogram.exceptions import TelegramAPIError
from app.config import Settings
from app.database.files import FileRepository
from app.services.permissions import is_owner_or_moderator
router=Router(name="file");log=logging.getLogger(__name__)
class FileStates(StatesGroup):waiting_for_message=State()

@router.message(Command("file"))
async def file_command(message:Message,state:FSMContext,settings:Settings,database):
    if not message.from_user or not await is_owner_or_moderator(database.db,message.from_user.id,settings):return
    if not settings.source_channel_id:await message.answer("Storage isn't configured. Set SOURCE_CHANNEL_ID first.");return
    await state.set_state(FileStates.waiting_for_message);await message.answer("Send me the files you want to store. Send one message for this /file link, or use /cancel to stop.")

@router.message(FileStates.waiting_for_message,Command("cancel"))
async def cancel_file(message:Message,state:FSMContext):
    await state.clear();await message.answer("File link creation cancelled.")

@router.message(FileStates.waiting_for_message,F.text.startswith("/"))
async def waiting_command(message:Message):
    await message.answer("Send the message to store, or use /cancel.")

@router.message(FileStates.waiting_for_message)
async def receive_file(message:Message,state:FSMContext,settings:Settings,database):
    if not message.from_user:return
    try:
        copied=await message.bot.copy_message(chat_id=settings.source_channel_id,from_chat_id=message.chat.id,message_id=message.message_id)
        name=message.document.file_name if message.document else None
        record=await FileRepository(database.db).save_file(source_chat_id=settings.source_channel_id,source_message_id=copied.message_id,created_by=message.from_user.id,file_name=name)
        me=await message.bot.get_me();link=f"https://t.me/{me.username}?start=file_{record['file_key']}"
        keyboard=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="COPY",copy_text=CopyTextButton(text=link))]])
        await message.answer(link,reply_markup=keyboard)
    except TelegramAPIError:
        log.exception("Could not create file link");await message.answer("Couldn't store this message. Ensure the bot is an administrator in the private source channel.")
    except Exception:
        log.exception("File link creation failed");await message.answer("Unexpected error while saving this link. Check bot logs.")
    finally:await state.clear()
