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
            # Most settings are singleton documents keyed by "key", but Force Join
            # stores one document per channel using the same key. The old unique
            # key-only index silently prevented a second channel from being added.
            settings_indexes = await self.db.settings.index_information()
            await self.db.settings.create_index(
                [("key", ASCENDING), ("channel", ASCENDING)],
                unique=True,
                name="key_channel_unique",
            )
            for index_name, index_info in settings_indexes.items():
                if (
                    index_name != "_id_"
                    and index_info.get("key") == [("key", ASCENDING)]
                    and index_info.get("unique")
                ):
                    await self.db.settings.drop_index(index_name)
            await self.db.moderators.create_index([("user_id",ASCENDING)],unique=True)
            await self.db.tasks.create_index([("status",ASCENDING),("deadline",ASCENDING)])
            await self.db.tasks.create_index([("request_key",ASCENDING)],unique=True,sparse=True)
            await self.db.delivery_requests.create_index([("request_key",ASCENDING)],unique=True)
            await self.db.delivery_requests.create_index([("status",ASCENDING),("updated_at",ASCENDING)])
            await self.db.batches.create_index([("batch_id",ASCENDING)],unique=True,sparse=True)
            await self.db.deeplink_codes.create_index([("code",ASCENDING)],unique=True)
            # Backfill every currently known code so deleted/old records cannot
            # accidentally make an already-issued code reusable after upgrades.
            async for old_file in self.db.files.find({"file_key": {"$type": "string"}}, {"file_key": 1}):
                await self.db.deeplink_codes.update_one(
                    {"code": old_file["file_key"]},
                    {"$setOnInsert": {"code": old_file["file_key"], "kind": "legacy-file"}},
                    upsert=True,
                )
            async for old_batch in self.db.batches.find({"batch_id": {"$type": "string"}}, {"batch_id": 1}):
                await self.db.deeplink_codes.update_one(
                    {"code": old_batch["batch_id"]},
                    {"$setOnInsert": {"code": old_batch["batch_id"], "kind": "legacy-batch"}},
                    upsert=True,
                )
            await self.db.broadcast_drafts.create_index([("admin_id",ASCENDING)],unique=True)
            await self.db.broadcast_jobs.create_index([("draft_id",ASCENDING)],unique=True)
            await self.db.broadcast_jobs.create_index([("status",ASCENDING),("created_at",ASCENDING)])
            await self.db.broadcast_recipients.create_index([("job_id",ASCENDING),("user_id",ASCENDING)],unique=True)
            await self.db.broadcast_recipients.create_index([("job_id",ASCENDING),("status",ASCENDING)])
            await self.db.batch_sessions.create_index([("admin_id",ASCENDING)],unique=True)
            await self.db.batch_deliveries.create_index([("request_key",ASCENDING)],unique=True)
            await self.db.batch_deliveries.create_index([("status",ASCENDING),("created_at",ASCENDING)])
            await self.db.batch_sessions.create_index([("status",ASCENDING),("last_activity_ts",ASCENDING)])
            await self.db.users.create_index([("blocked",ASCENDING)])
            # Re-queue jobs interrupted while the process was down.
            await self.db.tasks.update_many({"status":"processing"},{"$set":{"status":"pending"}})
            await self.db.batch_deliveries.update_many({"status":"processing"},{"$set":{"status":"pending"}})
            logger.info("MongoDB ready; interrupted delete tasks and batch deliveries recovered")
        except Exception:
            await self.close()
            logger.exception("MongoDB startup check failed")
            raise

    async def close(self):
        if self.client is not None:
            await self.client.close()
            self.client=None
            self.db=None
