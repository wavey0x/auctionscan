# Operations

The API and UI ship together. Breaking changes are intentional; there are no
old response shapes or runtime conversion paths. Use the uv release recorded
in `backend/pyproject.toml` and `uv sync --project backend --locked` on the deployment host.

Host names, filesystem layout, credentials and the release command sequence
live in `OPERATIONS.private.md`, which is untracked because this repository is
public. This file covers policy and mechanism only.

Both services run under a dedicated non-login account. The installed code and
virtual environment are root-owned and read-only to it; the SQLite database
and writer locks live on a separate writable path, and systemd supplies
credentials from an environment file readable only by root and that account.
The unit files in `deploy/systemd/` are installed directly, with no
service-identity override.

The units are sandboxed (`ProtectSystem=strict`, an empty capability bounding
set, a `@system-service` syscall filter and the database directory as the only
writable path). Changing a unit file requires `systemctl daemon-reload` before
the restart, and `systemd-analyze security` reports the effective exposure.

The production checkout pulls with a repository-scoped, read-only deploy key
held by root on the deployment host, so `git fetch origin` in the release
procedure works unattended and the host cannot push. The key is generated on
the host and its private half never leaves it.

The API is read-only and listens on loopback only. TLS termination and the
public API hostname are handled by a reverse proxy shared with unrelated
services on that host, so its configuration is not vendored here. A deployment
only has to keep the loopback bind and port in the unit aligned with the proxy
upstream.

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

Restore older captures with their saved application revision first. Use that
revision to prepare missing observations, snapshot provenance, and finality
anchors before upgrading. The current application rejects pre-finality data
and incomplete snapshot provenance; it does not adopt or convert them.

For current databases, `--check-observations` checks offline replay inputs and
`--backfill-observations` explicitly captures missing inputs on the same branch.
Backfill preserves existing snapshots and rejects a branch mismatch. Once
prepared, full and takes-only replay work with network access disabled and
preserve captured facts and sync checkpoints.

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

Projection-column deletions that preserve surviving values do not require
reprojection; verify migration and incremental writes, and rehearse replay on
backup copies. Releases changing derived payment
semantics do: run `--check-observations`, explicitly fill missing inputs if needed,
and run `--reproject` before restarting indexing. Rehearse these steps on a restored
copy first. Preserve chain logs, snapshots, RPC observations, pricing audit facts,
and checkpoint state through projection-only repairs.

`--backfill-pricing` adds pricing facts for confirmed events that live capture
missed, for example takes indexed after an outage or a rewind. It holds the
network's writer lock, so stop that indexer, run it, and start the indexer
again; the API can keep serving. It needs an archive RPC that serves
`eth_simulateV1` (redemptions are simulated at past blocks) and the prices
service, commits as it goes and can be interrupted and rerun. `--auction`
limits it to one auction. A failed replay is final until `--retry-failed`
asks again, for when the method has improved.
