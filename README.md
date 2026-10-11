# File-Bot

A modular Telegram file-store bot designed for Oracle Cloud Ubuntu with MongoDB Atlas metadata storage.

## Design goals

- **Fast async bot:** Python 3.12 and aiogram 3.
- **Persistent metadata:** MongoDB Atlas through the supported PyMongo Async API.
- **Durable file references:** store file posts in a dedicated private Telegram source channel and keep source chat/message identifiers in MongoDB. This avoids downloading large media to the VPS.
- **24/7 operation:** Oracle Cloud VPS, later managed with systemd and automatic restart.
- **Maintainability:** separate handlers, services, database code, settings and tests.
- **Secrets safety:** never commit `.env`, Telegram bot tokens, database passwords or SSH private keys.

## Important storage note

The bot can retain references to source-channel posts, but cannot guarantee availability if the source message/channel is deleted, the bot loses access, Telegram restricts the account, or the database is lost. Keep source posts untouched and enable database backups before production. No service can promise zero downtime.

## Setup

1. Create a Python virtual environment: `python3 -m venv .venv && source .venv/bin/activate`
2. Install packages: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` on the Oracle server and set `BOT_TOKEN`, `OWNER_ID`, and `MONGODB_URI` there.
4. Create a dedicated MongoDB Atlas user with access only to the bot database, and allow the Oracle VPS IP in Network Access.
5. Add the bot to the private source channel with appropriate administrator permissions.
6. Run tests with `pytest -q`; start with `python main.py` after the code is complete.

## Current implementation status

Initial project setup includes dependency pins, a secret-safe environment template, validated configuration, async MongoDB startup/index creation, a minimal `/start` handler, and polling lifecycle. This is a foundation, not a production-complete bot yet. File deep-links and delivery, batch flow, force-join, auto-delete, moderation, broadcasts, shortener integration, restart recovery, deployment service, and broader tests must be implemented and tested before real users rely on it.
