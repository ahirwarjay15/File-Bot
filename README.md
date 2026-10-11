# File-Bot

Async Telegram file/batch delivery bot built with Python 3.12, aiogram 3 and MongoDB Atlas through PyMongo Async.

## Current implementation
- `/file`: copies one message to the configured source channel and returns a deeplink with a copy button.
- `/batch`: collects up to 100 messages in order and stores one persistent batch deeplink in MongoDB.
- `/start file_KEY` and `/start batch_KEY`: file/batch delivery with configured Force Join membership checks.
- Owner-only moderator management: `/addmod`, `/delmod`; moderators can use bot-management commands.
- `/ban ID`, `/unban ID`, `/stats`.
- Configurable Start Message, Invalid Post text/button/About, Auto Delete timer/message, After Delete text/button, and shortener provider.
- Confirmed broadcast with rate limiting, forbidden-user tracking, and send/failure report.
- MongoDB-backed deletion tasks and startup recovery for interrupted task processing.

## Required Telegram setup
1. Create a private source channel used only for stored messages.
2. Add the bot as an administrator with permission to post/copy messages.
3. Set `SOURCE_CHANNEL_ID` to the channel's numeric ID.
4. Set `FORCE_JOIN_CHANNELS` as comma-separated channel usernames/IDs; bot must be able to check member status.
5. Set `BOT_TOKEN`, `OWNER_ID`, and `MONGODB_URI` in a private server-side `.env`. Never commit real secrets.

## Settings commands
- `/settings`
- `/setstart on|off`, `/setstarttext TEXT`
- `/setinvalid on|off`, `/setinvalidtext TEXT`, `/setinvalidbutton TEXT URL`
- `/setinvalidabout on|off`, `/setinvalidabouttext TEXT`
- `/setautodelete on|off`, `/setautodeletemin 2|5|15|30|60|180|360|720|1440`, `/setnotice TEXT`
- `/setafterdelete on|off`, `/setafterdeletetext TEXT`, `/setafterdeletebutton TEXT`
- `/setshortener API_URL API_TOKEN`

## Install and run
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```
Run `pytest -q`. Example systemd unit is at `deploy/file-bot.service.example`.

## Important limitations / test status
This repository's implementation is still awaiting runtime and end-to-end tests against Telegram, MongoDB Atlas and the Oracle VM. Do not treat it as production-ready until those checks pass.

- The source channel contains the actual Telegram posts; MongoDB stores references/metadata. If a source post is deleted or access is revoked, the bot cannot reconstruct the media.
- Batch collection currently uses in-memory FSM state; if the process restarts while a moderator is still collecting a batch, that *unfinished collection session* is lost. Completed batch links and queued expiry tasks are persisted.
- Generic shortener configuration only works with providers whose API accepts JSON `url` and `token` and returns `short_url`, `shortenedUrl`, or `shortlink`. Provider-specific adapters may be required.
- Telegram does not expose a universal exact count of users who have blocked a bot.
- Telegram Bot API cannot delete user-authored messages in ordinary private chats; only eligible bot messages can be managed.
