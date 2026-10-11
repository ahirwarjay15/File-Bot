import logging
from pymongo import ASCENDING, AsyncMongoClient
from app.config import Settings

logger=logging.getLogger(__name__)

class Database:
    def __init__(self,settings:Settings):
        self.settings=settings
        self.client=None
        self.db=None

    async def connect(self):
        self.client=AsyncMongoClient(self.settings.mongodb_uri.get_secret_value(),appname="File-Bot",serverSelectionTimeoutMS=8000,connectTimeoutMS=8000,retryWrites=True)
        try:
            await self.client.admin.command("ping")
            self.db=self.client[self.settings.mongodb_db_name]
            await self.db.users.create_index([("user_id",ASCENDING)],unique=True)
            await self.db.files.create_index([("file_key",ASCENDING)],unique=True)
            await self.db.settings.create_index([("key",ASCENDING)],unique=True)
            await self.db.moderators.create_index([("user_id",ASCENDING)],unique=True)
            await self.db.tasks.create_index([("status",ASCENDING),("deadline",ASCENDING)])
            await self.db.batches.create_index([("batch_id",ASCENDING)],unique=True,sparse=True)
            await self.db.broadcast_drafts.create_index([("admin_id",ASCENDING)],unique=True)
            logger.info("MongoDB ready")
        except Exception:
            await self.close()
            logger.exception("MongoDB startup check failed")
            raise

    async def close(self):
        if self.client is not None:
            await self.client.close()
            self.client=None
            self.db=None
