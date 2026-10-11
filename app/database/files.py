"""MongoDB persistence for file references, users, and batches."""
from datetime import datetime, timezone
from secrets import token_urlsafe

class FileRepository:
    def __init__(self,db): self.db=db

    async def save_file(self,*,source_chat_id:int,source_message_id:int,created_by:int,file_name:str|None=None)->dict:
        for _ in range(8):
            key=token_urlsafe(9).replace("-","").replace("_","")[:12]
            doc={"file_key":key,"source_chat_id":source_chat_id,"source_message_id":source_message_id,"created_by":created_by,"file_name":file_name,"created_at":datetime.now(timezone.utc),"kind":"file"}
            try:
                await self.db.files.insert_one(doc); return doc
            except Exception as exc:
                if getattr(exc,"code",None)!=11000: raise
        raise RuntimeError("Could not allocate a unique file key")

    async def get_file(self,key:str)->dict|None:
        return await self.db.files.find_one({"file_key":key,"kind":"file"})

    async def save_batch(self,items:list[dict],created_by:int)->dict:
        if not items or len(items)>100: raise ValueError("A batch must contain 1 to 100 files")
        for _ in range(8):
            batch_id=token_urlsafe(9).replace("-","").replace("_","")[:12]
            doc={"batch_id":batch_id,"items":items,"created_by":created_by,"created_at":datetime.now(timezone.utc),"kind":"batch"}
            try:
                await self.db.batches.insert_one(doc); return doc
            except Exception as exc:
                if getattr(exc,"code",None)!=11000: raise
        raise RuntimeError("Could not allocate a unique batch key")

    async def get_batch(self,batch_id:str)->dict|None:
        return await self.db.batches.find_one({"batch_id":batch_id,"kind":"batch"})

    async def save_user(self,user)->None:
        if user is None:return
        now=datetime.now(timezone.utc)
        await self.db.users.update_one({"user_id":user.id},{"$set":{"first_name":user.first_name,"last_name":user.last_name,"username":user.username,"last_seen":now},"$setOnInsert":{"created_at":now,"banned":False}},upsert=True)

    async def is_banned(self,user_id:int)->bool:
        user=await self.db.users.find_one({"user_id":user_id},{"banned":1})
        return bool(user and user.get("banned",False))

    async def get_setting(self,key:str,default=None):
        item=await self.db.settings.find_one({"key":key},{"value":1})
        return item.get("value",default) if item else default

    async def set_setting(self,key:str,value)->None:
        await self.db.settings.update_one({"key":key},{"$set":{"key":key,"value":value}},upsert=True)
