"""Delivery services and durable expiry worker."""
import asyncio,logging
from datetime import datetime,timedelta,timezone
from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardMarkup,InlineKeyboardButton
log=logging.getLogger(__name__)

async def deliver_reference(bot:Bot,db,settings,*,user_id:int,file_doc:dict,deeplink:str):
    sent=await bot.copy_message(chat_id=user_id,from_chat_id=file_doc["source_chat_id"],message_id=file_doc["source_message_id"])
    auto=await db.settings.find_one({"key":"auto_delete","enabled":True})
    if auto:
        minutes=max(1,min(int(auto.get("minutes",30)),1440))
        deadline=datetime.now(timezone.utc)+timedelta(minutes=minutes)
        alert=await bot.send_message(user_id,auto.get("notice") or f"Your file will be automatically deleted after {minutes} minutes.")
        await db.tasks.insert_one({"kind":"delete_delivery","user_id":user_id,"message_ids":[sent.message_id,alert.message_id],"deadline":deadline,"deeplink":deeplink,"status":"pending","created_at":datetime.now(timezone.utc)})
    return sent

async def deliver_batch(bot:Bot,db,*,user_id:int,batch:dict,deeplink:str):
    auto=await db.settings.find_one({"key":"auto_delete","enabled":True})
    minutes=max(1,min(int(auto.get("minutes",30)),1440)) if auto else None
    deadline=None; delivered=[]; failed=0
    for item in batch.get("items",[]):
        try:
            sent=await bot.copy_message(chat_id=user_id,from_chat_id=item["source_chat_id"],message_id=item["source_message_id"])
            delivered.append(sent.message_id)
            if auto and deadline is None:
                deadline=datetime.now(timezone.utc)+timedelta(minutes=minutes)
        except TelegramAPIError:
            failed+=1
            log.exception("Batch item delivery failed")
    if auto and deadline and delivered:
        alert=None
        # Do not send a stale alert if the shared deadline already passed.
        if deadline>datetime.now(timezone.utc):
            try: alert=await bot.send_message(user_id,auto.get("notice") or f"Your files will be automatically deleted after {minutes} minutes.")
            except TelegramAPIError: log.exception("Could not send batch auto-delete alert")
        ids=delivered+([alert.message_id] if alert else [])
        await db.tasks.insert_one({"kind":"delete_delivery","user_id":user_id,"message_ids":ids,"deadline":deadline,"deeplink":deeplink,"status":"pending","created_at":datetime.now(timezone.utc)})
    return len(delivered),failed

async def run_task_worker(bot:Bot,db,poll_seconds:int=5):
    while True:
        now=datetime.now(timezone.utc)
        async for task in db.tasks.find({"status":"pending","deadline":{"$lte":now}}).sort("deadline",1).limit(50):
            claimed=await db.tasks.update_one({"_id":task["_id"],"status":"pending"},{"$set":{"status":"processing","claimed_at":datetime.now(timezone.utc)}})
            if not claimed.modified_count:continue
            try:
                for mid in task.get("message_ids",[]):
                    try:await bot.delete_message(task["user_id"],mid)
                    except TelegramAPIError:log.info("Could not delete delivered message %s for user %s",mid,task["user_id"])
                auto=await db.settings.find_one({"key":"auto_delete","enabled":True})
                after=await db.settings.find_one({"key":"after_delete","enabled":True}) if auto else None
                if after:
                    text=after.get("text") or "Your Video / File Is Successfully Deleted."
                    link=task.get("deeplink")
                    markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=after.get("button_text") or "Get your files again",url=link)]]) if link else None
                    await bot.send_message(task["user_id"],text,reply_markup=markup)
                await db.tasks.update_one({"_id":task["_id"]},{"$set":{"status":"done","finished_at":datetime.now(timezone.utc)}})
            except Exception:
                log.exception("Expiry task failed")
                await db.tasks.update_one({"_id":task["_id"]},{"$set":{"status":"pending","last_error_at":datetime.now(timezone.utc)}})
        await asyncio.sleep(poll_seconds)
