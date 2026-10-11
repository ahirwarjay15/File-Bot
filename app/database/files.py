"""Persistence helpers for Telegram source-channel references."""
from datetime import datetime, timezone
from secrets import token_urlsafe
from pymongo import ReturnDocument


class FileRepository:
    def __init__(self, db):
        self.db = db

    async def save_file(self, *, source_chat_id: int, source_message_id: int, created_by: int, file_name: str | None = None) -> dict:
        # Collision-resistant key; a unique MongoDB index is the final guard.
        for _ in range(5):
            key = token_urlsafe(9).replace("-", "").replace("_", "")[:12]
            doc = {
                "file_key": key,
                "source_chat_id": source_chat_id,
                "source_message_id": source_message_id,
                "created_by": created_by,
                "file_name": file_name,
                "created_at": datetime.now(timezone.utc),
                "kind": "file",
            }
            try:
                await self.db.files.insert_one(doc)
                return doc
            except Exception as exc:
                if getattr(exc, "code", None) != 11000:
                    raise
        raise RuntimeError("Could not allocate a unique file key")

    async def get_file(self, key: str) -> dict | None:
        return await self.db.files.find_one({"file_key": key, "kind": "file"})

    async def save_user(self, user) -> None:
        if user is None:
            return
        await self.db.users.update_one(
            {"user_id": user.id},
            {"$set": {"first_name": user.first_name, "username": user.username, "last_seen": datetime.now(timezone.utc)}, "$setOnInsert": {"created_at": datetime.now(timezone.utc), "banned": False}},
            upsert=True,
        )

    async def is_banned(self, user_id: int) -> bool:
        user = await self.db.users.find_one({"user_id": user_id}, {"banned": 1})
        return bool(user and user.get("banned", False))

    async def get_setting(self, key: str, default=None):
        item = await self.db.settings.find_one({"key": key}, {"value": 1})
        return item.get("value", default) if item else default

    async def set_setting(self, key: str, value) -> None:
        await self.db.settings.update_one({"key": key}, {"$set": {"value": value}}, upsert=True)
