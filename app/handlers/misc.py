"""Normal-user invalid-post handling; commands and privileged users are ignored."""
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from app.config import Settings
from app.services.permissions import is_owner_or_moderator, is_banned

router=Router(name="misc")

@router.message()
async def invalid_post(message:Message,settings:Settings,database):
    if not message.from_user or message.text and message.text.startswith("/"):
        return
    if await is_owner_or_moderator(database.db,message.from_user.id,settings) or await is_banned(database.db,message.from_user.id):
        return
    cfg=await database.db.settings.find_one({"key":"invalid_post","enabled":True})
    if cfg:
        await message.answer(cfg.get("text") or "This is not a valid file link.")
