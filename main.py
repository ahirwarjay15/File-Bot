"""Application entry point."""
import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from app.config import get_settings
from app.database.connection import Database
from app.handlers.start import router as start_router
from app.handlers.file import router as file_router
from app.handlers.batch import router as batch_router
from app.handlers.admin import router as admin_router
from app.handlers.settings import router as settings_router
from app.handlers.broadcast import router as broadcast_router
from app.handlers.shortener import router as shortener_router
from app.handlers.misc import router as misc_router
from app.services.delivery import run_task_worker

async def main():
    settings=get_settings()
    logging.basicConfig(level=getattr(logging,settings.log_level.upper(),logging.INFO),format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",stream=sys.stdout)
    bot=Bot(token=settings.bot_token.get_secret_value(),default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    database=Database(settings)
    worker=None
    try:
        await database.connect()
        dp=Dispatcher(storage=MemoryStorage())
        dp["settings"]=settings
        dp["database"]=database
        for router in (start_router,file_router,batch_router,admin_router,settings_router,broadcast_router,shortener_router,misc_router):
            dp.include_router(router)
        await bot.delete_webhook(drop_pending_updates=False)
        worker=asyncio.create_task(run_task_worker(bot,database.db),name="delivery-task-worker")
        logging.getLogger(__name__).info("Polling started")
        await dp.start_polling(bot,allowed_updates=dp.resolve_used_update_types())
    finally:
        if worker:
            worker.cancel()
            try: await worker
            except asyncio.CancelledError: pass
        await database.close()
        await bot.session.close()

if __name__=="__main__":
    try: asyncio.run(main())
    except (KeyboardInterrupt,SystemExit): pass
