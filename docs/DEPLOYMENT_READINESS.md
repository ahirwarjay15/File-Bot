# Deployment Readiness — Main Bot + 15 Render Workers

## Current observed state (2026-10-16)

- GitHub default branch: `main`; all inspected Render services point at `main` and start `python main.py`.
- The 15 Render service slots exist, but the inspected latest deploys are `update_failed`.
- Render logs for Main-1 and Main-2 show missing required environment variables: `BOT_TOKEN`, `OWNER_ID`, and `MONGODB_URI`.
- These services are configured as public `web_service` instances, but the Telegram polling bot does not open an HTTP port. Render reports that a background worker is the appropriate service type for processes that do not receive HTTP traffic.
- The current feature branch adds `APP_ROLE=all|main|worker` as an initial role switch. It does **not** yet implement the full central bot registry, 15-way Atlas routing, per-bot data isolation, or safe multi-worker lease recovery.

## Do not do these yet

- Do not set `APP_ROLE=worker` on all Render services.
- Do not deploy the role-separation branch to production.
- Do not point every bot at the same Atlas database unless the per-bot isolation layer is implemented.
- Do not set MongoDB network access to `0.0.0.0/0` as a quick fix.
- Do not paste Telegram tokens, MongoDB passwords, or connection strings into GitHub issues, PRs, or chat.

## Required design before enabling workers

1. The Oracle VM runs the Main Bot / control plane only.
2. Jai's Org Atlas project stores the central bot registry, configuration, worker assignment and shard routing metadata.
3. Each worker has a stable `bot_id`, its own Telegram token, and a declared storage shard.
4. User, file, batch, settings, task, and delivery records are isolated by `bot_id`; a request must never read another bot's records.
5. Worker queue claims must be atomic, leased, and recoverable after a process crash. Broadcast and delivery processing must not be claimed concurrently by two workers.
6. The network path from each worker to Atlas must be designed explicitly. Render free services do not provide the stable egress identity needed for a narrow Atlas IP allow-list; use a suitable paid/static-egress plan or a secure private gateway instead of opening Atlas to every IP.
7. Deploy one worker to a staging bot and a non-production shard, test end-to-end, then roll out gradually.

## Render dashboard checklist (after the code is ready)

For each of the 15 worker services:

1. Create/recreate it as a **Background Worker**, not a Web Service. Existing Render service types may not be convertible in place; do not delete a service until its role and replacement are confirmed.
2. Select the intended worker code branch only after its PR is approved and merged.
3. Set secrets directly in the Render Environment UI:
   - `BOT_TOKEN`: token for this worker bot
   - `OWNER_ID`: authorized owner ID
   - `MONGODB_URI`: only the assigned shard or secure gateway URI
   - `MONGODB_DB_NAME`: the intended database name
   - `APP_ROLE=worker`: only after the worker routing and lease implementation is complete
   - `WORKER_ID`: stable worker identity (to be wired into code before rollout)
4. Never copy the Main Bot's token into all worker services.
5. Confirm the deploy is live and inspect logs for successful MongoDB connection, worker identity, shard assignment and zero Telegram polling.
6. Verify that a test file created for one bot cannot be resolved or delivered by another bot.

## Oracle VM checklist

The Oracle VM remains the single Main Host. Before cutover, back up the current code and environment file securely, deploy a tested commit, set `APP_ROLE=main` only when main/worker responsibilities are fully separated, and verify Telegram polling plus central DB access. Keep the current working process unchanged until a rollback-tested deployment is ready.

## Completion gate

The system is not production-ready until role isolation, bot registry, shard routing, lease-based job recovery, Atlas network connectivity, and end-to-end tests all pass. Passing unit CI alone is not sufficient.
