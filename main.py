"""Application entry point."""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import get_settings
from app.database.connection import Database
from app.handlers.start import router as start_router
from app.handlers.file import router as file_router


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    database = Database(settings)
    try:
        await database.connect()
        dispatcher = Dispatcher()
        dispatcher["settings"] = settings
        dispatcher["database"] = database.db
        dispatcher.include_router(start_router)
        dispatcher.include_router(file_router)
        await bot.delete_webhook(drop_pending_updates=False)
        logging.getLogger(__name__).info("Bot polling started")
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await database.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
