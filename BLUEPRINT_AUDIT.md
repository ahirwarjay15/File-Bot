# Blueprint vs GitHub audit

Repository: ahirwarjay15/File-Bot, branch main.

## Source coverage note
The supplied blueprint file starts at section 5 (Auto Delete). Sections 1–4 are not present in that file, so those sections cannot be certified against the uploaded source. The matrix below covers the requirements that are actually present in the supplied file and the additional flows named in its final end-to-end section.

## Feature-by-feature status

| Blueprint requirement | Code status | Verification status |
|---|---|---|
| Auto Delete defaults off, 30-minute timer, cycle 2m/5m/15m/30m/1h/3h/6h/12h/24h | Implemented in settings and delivery service | Automated checks pending |
| Auto Delete only schedules delivered file messages and the auto-delete notice | Implemented | Telegram integration test pending |
| Single-file timer starts after successful delivery; alert shares deadline | Implemented | Telegram integration test pending |
| Batch timer starts at first successful delivery; all files share one deadline; one alert after last attempt | Implemented | Telegram integration test pending |
| After Delete only runs while Auto Delete is enabled; replacement points to original deeplink | Implemented | Telegram integration test pending |
| Expiry jobs persist and are recovered after restart | Implemented with MongoDB task records | Crash/restart integration test pending |
| Invalid Post defaults off; normal messages only; moderator and banned users excluded | Implemented | Telegram integration test pending |
| Start About and Invalid About have independent toggles and edit their existing messages | Start About control and callback added; Invalid About already implemented | Callback integration test pending |
| Invalid Post text variables, custom URL button, photo/GIF poster, About button | Implemented | Media and callback integration tests pending |
| About button edits existing invalid post, including media caption | Implemented | Telegram integration test pending |
| Shortener add/remove, masked token, API validation, manual shortening + COPY | GPlinks adapter plus generic compatible JSON API adapter implemented | Adapter unit tests added; live provider test pending |
| /file creates one permanent deeplink and does not auto-shorten it | Implemented | Telegram integration test pending |
| /batch creates one permanent deeplink for up to 100 messages | Implemented | Telegram integration test pending |
| Batch source order, 200-second timeout, persistent collection session, restart recovery | Implemented with MongoDB session and stable batch ID | Concurrency/restart tests pending |
| Force Join checks configured channels, caches verification for matching channel set, removes prompt after successful check | Implemented | Real membership checks pending |
| Optional Force Join animation, excluded from Auto Delete | Implemented through settings UI; deleted after delivery | Telegram media test pending |
| Moderator maximum three, owner-only add/remove, owner excluded from list | Implemented | Concurrent moderator-change test pending |
| Ban/unban persistence and owner/moderator protection | Implemented | Authorization tests pending |
| Stats popup reports tracked users and known blocked/unreachable users | Implemented | Count accuracy depends on Telegram delivery errors |
| Broadcast confirmation, queued rate-limited delivery, per-recipient result, restart recovery | Implemented with MongoDB jobs and recipient records | Large-broadcast/crash test pending |

## Known remaining gaps before production

- Request-level deduplication is persisted for repeated /start updates and Force Join callbacks. Broadcast now recovers queued drafts even if the process stops before job creation, skips users banned after queueing, and marks interrupted in-flight recipients as unknown. Automatic replay of an interrupted single/batch delivery request still needs a durable per-item delivery queue; exactly-once delivery cannot be guaranteed across the Telegram-send/database-write crash window.
- The blueprint mentions a separate last-two-message retention rule. That retention/cleanup behavior is not implemented because the supplied section does not define its trigger/cleanup sequence. Telegram also does not generally allow the bot to delete user-authored messages in private chats.
- The supplied file lacks blueprint sections 1–4, so the complete A-to-Z comparison requires the missing source sections.
- No automated test run or end-to-end Telegram/Atlas/Oracle test has been confirmed yet. The repository workflow now runs syntax compilation and pytest on pushes/PRs, but this audit does not claim a passing run.

## Release gate

Do not deploy as production-ready until the GitHub Actions checks pass, test cases cover settings callbacks and permission boundaries, and the full flow is tested with a real bot and Atlas database—including restart during batch collection, batch generation, expiry, and broadcast.