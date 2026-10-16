"""Application entry point with explicit main/worker process roles."""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import get_settings
from app.database.connection import Database
from app.handlers.start import router as start_router, run_pending_join_request_cleanup_worker
from app.handlers.file import router as file_router
from app.handlers.batch import router as batch_router, run_batch_session_worker
from app.handlers.admin import router as admin_router
from app.handlers.settings import router as settings_router
from app.handlers.broadcast import router as broadcast_router, run_broadcast_worker
from app.handlers.shortener import router as shortener_router
from app.handlers.misc import router as misc_router
from app.services.delivery import run_task_worker, run_batch_delivery_worker


def build_dispatcher(settings, database) -> Dispatcher:
    """Build the Telegram update dispatcher for the main bot only."""
    dp = Dispatcher(storage=MemoryStorage())
    dp["settings"] = settings
    dp["database"] = database
    # Keep the catch-all invalid-post handler last so specific handlers run first.
    for router in (
        start_router, file_router, batch_router, admin_router,
        settings_router, broadcast_router, shortener_router, misc_router,
    ):
        dp.include_router(router)
    return dp


async def supervise_worker(worker, *args, name: str, restart_delay: float = 5.0):
    """Restart a background worker after an unexpected exception."""
    log = logging.getLogger(__name__)
    while True:
        try:
            await worker(*args)
            log.error("Background worker %s exited unexpectedly; restarting", name)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(
                "Background worker %s crashed; restarting in %.1f seconds",
                name, restart_delay,
            )
        await asyncio.sleep(restart_delay)


async def run_background_workers(bot, db):
    """Run queue/maintenance workers; this role never polls Telegram updates."""
    workers = (
        (run_task_worker, "delivery-task-worker"),
        (run_batch_session_worker, "batch-session-worker"),
        (run_batch_delivery_worker, "batch-delivery-worker"),
        (run_broadcast_worker, "broadcast-worker"),
        (run_pending_join_request_cleanup_worker, "pending-join-request-cleanup-worker"),
    )
    tasks = [
        asyncio.create_task(
            supervise_worker(worker, *( [bot, db] if worker is not run_pending_join_request_cleanup_worker else [db] ),
                             name=name),
            name=name,
        )
        for worker, name in workers
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def main():
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        stream=sys.stdout,
    )
    log = logging.getLogger(__name__)
    # Keep the default parse mode unset: saved messages can contain arbitrary text.
    bot = Bot(
        token=settings.bot_token.get_secret_value(),
        default=DefaultBotProperties(link_preview_is_disabled=True),
    )
    database = Database(settings)
    try:
        await database.connect()
        if settings.app_role in ("worker", "all"):
            worker_task = asyncio.create_task(
                run_background_workers(bot, database.db), name="background-workers"
            )
        else:
            worker_task = None

        if settings.app_role in ("main", "all"):
            dp = build_dispatcher(settings, database)
            # Only the main polling process may manage the webhook/polling lifecycle.
            await bot.delete_webhook(drop_pending_updates=False)
            log.info("Telegram polling starting (APP_ROLE=%s)", settings.app_role)
            try:
                await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
            finally:
                if worker_task:
                    worker_task.cancel()
                    await asyncio.gather(worker_task, return_exceptions=True)
        else:
            log.info("Worker-only process started (APP_ROLE=worker); polling is disabled")
            await worker_task
    finally:
        await database.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
