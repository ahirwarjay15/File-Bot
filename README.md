# File-Bot

Modular async Telegram file-link bot built with Python 3.12, aiogram 3 and MongoDB Atlas via PyMongo Async.

## Features implemented in the codebase
- `/file`: copy one message into the configured private source channel and generate a deep link.
- `/batch`: collect up to 100 messages and generate links in received order.
- `/start file_KEY`: validate a stored key, enforce configured Force Join channels, and deliver the source message.
- Owner/moderator management: `/addmod`, `/delmod`, `/ban`, `/unban`, `/stats`.
- Start-message and invalid-post settings; auto-delete and after-delete settings.
- `/broadcast`: reply to a message and confirm before sending to tracked, non-banned users.
- `/shortener`: manually shorten a URL through a configurable provider adapter.
- MongoDB-backed delivery deletion tasks, allowing due tasks to be picked up after process restarts.

## Required Telegram setup
1. Create a **private source channel** dedicated to stored posts.
2. Add the bot as an administrator with permission to post messages.
3. Set `SOURCE_CHANNEL_ID` to the channel's numeric ID.
4. Add every Force Join channel to `FORCE_JOIN_CHANNELS` as comma-separated usernames/IDs and make the bot able to check membership (normally admin in each channel).
5. Set `BOT_TOKEN`, `OWNER_ID`, and `MONGODB_URI` in the server's private `.env` file. Never commit `.env`.

## Settings commands
- `/settings` — list settings commands
- `/setstart on|off`, `/setstarttext TEXT`
- `/setinvalid on|off`, `/setinvalidtext TEXT`
- `/setautodelete on|off`, `/setautodeletemin MINUTES`, `/setnotice TEXT`
- `/setafterdelete on|off`
- `/setshortener API_URL API_TOKEN`

## Install and run
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Run checks with `pytest -q`. For production, run under systemd and keep logs. Add the Oracle server public IP to MongoDB Atlas Network Access if IP allowlisting is enabled.

## Storage and delivery notes
Actual media posts live in the Telegram source channel; MongoDB stores metadata and message references. Do not delete the source posts or remove the bot's access. No design can guarantee permanent availability if Telegram removes a post/account or access is revoked.

## Important test status
The code has been assembled but **has not yet been integration-tested** against your Telegram bot, MongoDB Atlas and Oracle instance. Complete deployment, run unit and end-to-end checks, then fix any discovered incompatibilities before relying on it. Batch collection currently uses aiogram's in-memory FSM; an interrupted batch session will not survive a process restart. The persisted delete queue does survive restarts.
