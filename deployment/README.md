# Render environment setup

## Important security rule
Do not enter real tokens, passwords, or MongoDB connection strings into a tracked GitHub file. The template `render-env.template.json` is safe to commit; the filled file must stay local as `deployment/render-env.private.json` (already ignored by `.gitignore`).

## Fill once
1. Download/clone the repository to your own machine.
2. Copy `deployment/render-env.template.json` to `deployment/render-env.private.json`.
3. Fill the private copy with values for each Render service.
4. Do not commit or upload the private copy.

## MongoDB URI
A URI cannot be created from a cluster name alone. It requires the actual Atlas cluster hostname plus a database user's username/password, and Atlas network access must permit the connecting service. The project integration does not reveal existing database passwords. Do not reuse a URI across worker services unless the storage-isolation design explicitly says they should share it.

## Bulk rollout status
The template is a configuration worksheet, not an automatic deploy/sync tool. Do not apply the variables to Render yet: the File-Bot worker/main role split, per-bot storage routing, and Render service types still need to be finalized. Applying the wrong values now could start duplicate pollers or point multiple workers at the same database.
