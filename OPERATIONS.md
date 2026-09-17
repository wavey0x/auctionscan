# Operations

The API and UI ship together. Breaking changes are intentional; there are no
old response shapes or runtime conversion paths. Use the uv release recorded
in `backend/pyproject.toml` and `uv sync --project backend --locked` on the deployment host.

## Backups and restoration

Use SQLite's online backup API to create a consistent snapshot of the shared
database. Verify integrity and foreign keys, record fact counts and sync
checkpoints, and retain the matching application revision and configuration.
Keep encrypted backups off the serving host and periodically rehearse recovery.
Store credentials and host-specific schedules, retention, destinations and
administrative commands in a private operations runbook.

The recovery window is the age of the latest verified, usable off-host snapshot.
Monitor backup failures and overdue captures. Process-lock files are not database
contents and do not need restoration.

For a recovery rehearsal, restore a snapshot into a private temporary directory,
never over the serving database. Keep the original capture unchanged. Run
`PRAGMA integrity_check` and `PRAGMA foreign_key_check`, then compare captured
fact counts and checkpoints before and after migrations and offline replay.

Older captures may lack RPC observations. Use explicit `--check-observations`
and `--backfill-observations` maintenance to prepare the restored copy before
`--reproject`. Once prepared, full and takes-only replay must work with network
access disabled and preserve captured facts and sync checkpoints.

For actual recovery, stop the API and all writers, retain the damaged database
for investigation, restore the verified copy with its matching application and
configuration, and verify the API before restarting indexing. If installing a
newer application, run its writer-owned migrations and required maintenance
before making it available. The API never upgrades a database.

## Shared-database maintenance and deployment

All networks share one SQLite file. Normal writer concurrency uses SQLite's
transaction locking; each network still runs in its own process. Do not split
databases or introduce a coordinating runtime. Resolve contention by shortening
transactions and improving queries, indexes, and batching.

Before schema changes or exclusive maintenance:

1. List every active `auctionscan-indexer@*.service` and any manually launched
   writer. Stop them all and confirm they have exited. Per-network process locks
   and the yoyo migration lock do not establish a database-wide maintenance window.
2. Stop `auctionscan-api.service` during migration and reprojection. A maintenance
   window is acceptable; restore service only after the current model is ready.
3. Take a verified snapshot and retain the old application revision. Never copy
   just the main file of a live WAL database; use the SQLite backup API.
4. Install the already-tested revision into a clean checkout and sync locked
   dependencies with the pinned uv version. Run one writer to apply migrations
   and any explicit observation backfill or reprojection required by the release.
5. Start the matching API and UI, then all previously active indexers. Verify
   health, checkpoints advancing toward head, API documentation, real round/take
   responses, UI navigation, and indexer logs. Confirm backup capture still works.

Normal deployments do not need reprojection. Releases changing derived payment
semantics do: run `--check-observations`, explicitly fill missing inputs if needed,
and run `--reproject` before restarting indexing. Rehearse these steps on a restored
copy first. Preserve chain logs, snapshots, RPC observations, pricing audit facts,
and checkpoint state through projection-only repairs.
