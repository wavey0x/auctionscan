# AGENTS.md - Auctionscan Development Guide

This repo is the canonical Auctionscan project.

## Purpose

Auctionscan is a SQLite-backed auction indexer, read-only API, and React UI for
monitoring Dutch auctions.

- `backend` contains the indexer and FastAPI application
- `ui` contains the React frontend
- `artifacts` contains pinned source and ABI references for supported contracts

The pre-rewrite app was removed from the working tree on April 7, 2026. If you
need legacy behavior for comparison, inspect git history or the
`legacy-monorepo-snapshot-2026-04-07` tag.

## Backend Shape

The backend design is intentional:

- one long-running process per network
- `--network` is required
- no internal multi-network runtime
- SQLite is the system of record
- normal operation is incremental sync, not repeated rebuilds

Canonical three-layer model:

1. Facts
- `chain_logs`: raw persisted logs from the chain
- `domain_events`: normalized semantic events derived from logs
- snapshot facts: same-block `eth_call` observations captured during indexing
  and stored durably
  - `round_param_snapshot`: kick-time snapshot facts
  - `auction_snapshot_facts`: deploy-time snapshot facts
- pricing audit facts:
  - `pricing_quote_facts`
  - `pricing_quote_provider_facts`
  - `pricing_price_facts`
  - `pricing_price_provider_facts`
- operational mutable state:
  - `pricing_capture_queue`

2. Projections / read models
- `auctions`
- `auction_tokens`
- `auction_current_params`
- `rounds`
- `takes`
- `taker_summary`
- `take_pricing`
- `round_pricing`
- `taker_pricing_summary`

3. API formatting
- FastAPI serializers format already-decoded projection values
- the API should not own contract-version semantics

Think about ownership this way:

- facts answer: "what did we observe?"
- projections answer: "what derived state do we want to query?"
- API formatting answers: "how do we present stored derived values?"

The critical rule is that same-block snapshot reads are facts. They are not
throwaway cache and they are not API-only metadata. Even though
`round_param_snapshot` sounds projection-like, treat it as durable captured
truth for kick-time settings.

Rules for this model:

- hydrated snapshots are facts, not disposable cache
- facts store raw observed values plus `param_schema`
- pricing audit tables are facts and should remain replayable
- `pricing_capture_queue` is operational state, not durable fact history
- pricing capture runs up to `DEFAULT_MAX_CONCURRENCY` HTTP attempts at once;
  in-flight rows are excluded from selection, and all HTTP stays outside the
  writer transaction
- projections store decoded values for query/API use
- pricing projections rebuild from stored pricing facts, not from live repricing
- the canonical parameter decoder lives in the indexer layer
- version-aware scaling belongs in decoder/projection code, not serializers
- if a displayed value is semantically wrong, fix the decoder or projection;
  do not patch around it in the UI or API
- `param_schema` currently maps:
  - `0.0.1`, `1.0.1`, `1.0.2` -> `v1_fixed_decay`
  - `1.0.3`, `1.0.3cc` -> `v1_bps_decay`
  - `1.0.4` -> `v1_wad_bps`
  - `1.0.5` -> `v1_wad_start_wad_bps`
- `v1_fixed_decay` is special:
  - `starting_price` stays unscaled
  - `minimum_price` is absent
  - `step_decay_percent` is synthesized from the known fixed contract constant
  - `step_duration_seconds` remains `NULL`
- `v1_wad_start_wad_bps` is like `v1_wad_bps`, except `starting_price_raw`
  is also WAD-scaled and must be decoded by dividing by `1e18`
- duration fields are still part of the decoded layer even when they are
  identity transforms today; that keeps units explicit and the projection
  schema stable

If you are changing data logic, decide which layer owns the change before
editing code:

1. new observed truth -> fact storage
2. new derived meaning or unit semantics -> decoder / projection layer
3. pure string or display change -> API/UI formatting

The pattern is durable. Exact projection table shapes may still evolve, but the
fact/projection/API boundary should not.

## API Rule

The API should follow the OpenAPI standard from the start.

- prefer FastAPI
- define explicit request/response models
- keep `/openapi.json`, `/docs`, and `/redoc` working
- treat the OpenAPI schema as part of the contract with `ui`
- avoid parallel legacy/v2 route trees; keep one clear surface

The API is read-only against SQLite. The indexer owns writes.

Filter parameters are declared as `Literal` unions so the OpenAPI schema
carries their values and invalid input returns 422 rather than silently
falling back. `status` accepts the stored round statuses only (`all`, `live`,
`sold_out`, `expired`, `settled`); there are no alias spellings.

Address policy:

- store addresses canonically normalized in SQLite
- accept API input in any case and normalize internally
- return checksummed addresses from the API
- do not rely on address casing for identity comparisons

## Reproject

`--reproject` is a maintenance/correction feature, not the normal runtime mode.

- normal sync: fetch new chain data, persist facts, update projections, advance
  checkpoints
- `--reproject`: keep stored facts, wipe and rebuild projections from local
  facts
- `--reproject --takes-only`: rebuild only derived take state and take rollups

This exists because take detection and round derivation are inference-heavy and
must be repairable without full historical rescans.

For auction settings, "stored facts" includes snapshot fact tables. Reproject
must preserve:

- `chain_logs`
- `domain_events`
- `round_param_snapshot`
- `auction_snapshot_facts`
- `pricing_quote_facts`
- `pricing_quote_provider_facts`
- `pricing_price_facts`
- `pricing_price_provider_facts`

Reproject may clear operational pricing queue rows and pricing projections, but
it must not discard pricing audit facts.

Do not remove replayability casually.

Reproject intent:

- facts survive
- projections are disposable and rebuildable
- API formatting should not matter for reproject correctness
- a fix to parameter semantics should usually be repairable from stored facts
  plus reproject, not from fresh historical RPC calls

## Design Rules

- Prefer simple, explicit code over flexible frameworks.
- Do not reintroduce a giant all-in-one runtime.
- Do not add multi-process orchestration inside `backend`.
- Treat one process per network as a fixed operational rule.
- Keep `chain_logs` and native `domain_events` durable and replayable.
- Keep snapshot facts durable and replayable.
- Pre-launch breaking changes are acceptable. Prefer a clean forward state over
  backward-compatibility shims unless explicitly requested.
- This is a greenfield product; the API's only consumer is our own UI. Update
  them together. Do not add compatibility aliases, old API shapes, or runtime
  support for obsolete database/job states. Convert existing data once through
  writer-owned migrations or explicit maintenance, then use the current model.
- Schema changes should use writer-owned yoyo migrations. Do not add ad hoc
  startup shims or API-side schema mutation paths.
- When changing schema, update both the bootstrap schema helpers and add a new
  yoyo migration for already-stamped databases. Editing `0001_current_schema`
  alone is not enough once a DB has already applied it.
- Do not move contract-version parameter scaling into API serializers.
- If auction-setting semantics change, update the indexer decoder and
  projections, not UI-facing formatting code.
- When old behavior matters, use git history as reference for:
  - transfer-derived takes
  - receipt-level want-token matching
  - adaptive `eth_getLogs` splitting
  - version-specific contract quirks

## Network Configuration

`config.yaml` owns per-chain policy; the indexer holds no per-chain table.

- `finality_mode`: `finalized` uses the chain's `finalized` block tag and
  ignores `finality_depth`; `confirmations` subtracts `finality_depth` from the
  live head. Ethereum is `finalized`; everything else is `confirmations`.
- `finality_depth`: confirmation depth, defaulting to 64.
- `request_timeout_seconds`: RPC transport timeout, defaulting to 60.
- `disabled: true` means no indexer process exists for that network. The API
  omits disabled networks from `/api/health`, and `--network` refuses them.
  Only `ethereum` is enabled; enabling a network means deploying an
  `auctionscan-indexer@<network>.service` alongside the flag change.

## Practical Notes

- The project uses `.env` and `.env.example`.
- Backend Python dependencies are managed with `uv`.
- Sync them with `uv sync --project backend --extra test`.
- Run backend commands with `uv --project backend run ...`.
- `backend` and `ui` should not depend on any deleted legacy root layout.
- The UI style guide lives at `ui/styles/STYLESHEET.md`.
- Frontend changes should follow that guide and prioritize compact, dense
  layouts over card-heavy presentation.
- The SQLite file is `auctionscan.sqlite3`.
- When changing derivation logic, think in terms of replay:
  - what facts are persisted?
  - are hydrated snapshots being treated as facts?
  - what state is projected?
  - can the new logic repair an existing DB with `--reproject`?
- When changing auction-setting fields, think in terms of the three layers:
  - raw fact storage
  - decoder / projection logic
  - API formatting
- If you are unsure where code belongs:
  - snapshot capture and persistence -> fact layer
  - scaling, unit interpretation, semantic decoding -> projection layer
  - strings, percentages, labels, final shape for clients -> API layer
- If a doc disagrees with the implemented runtime, favor the code and update the
  doc.

## Deployment Notes

Production is split between Vercel for the static React UI and `electro` for
the FastAPI API plus indexer.

Frontend:

- Public site: `https://auctionscan.info`
- Served by Vercel from `ui`
- Pushes to `master` trigger the Vercel Git integration
- `VITE_API_BASE_URL` must be set in the Vercel project environment to
  `https://api.auctionscan.info/api`; the repo default `/api` is for
  same-origin local development and would 404 in production
- Only `VITE_`-prefixed variables reach the browser bundle. Never give an RPC
  URL or API key that prefix
- The local Vercel CLI may not be logged in; do not create or relink a Vercel
  project from defaults
- Verify with:
  - `curl -I https://auctionscan.info`
  - expect `server: Vercel`

Backend/API/indexer:

- Public API host: `https://api.auctionscan.info`
- API docs: `https://api.auctionscan.info/docs`
- API health: `https://api.auctionscan.info/api/health`
- Server SSH host: `electro`
- Production checkout: `/opt/auctionscan` (root-owned, readable by `svc-auctionscan`)
- Production SQLite DB: `/var/lib/auctionscan/auctionscan.sqlite3`
- Production credentials: `/etc/auctionscan.env` (`root:svc-auctionscan`, mode `0640`)
- Systemd services:
  - `auctionscan-api.service`
  - `auctionscan-indexer@ethereum.service`

Backend deploy procedure:

1. Locally run the relevant checks before pushing:
   - `uv --project backend run pytest`
   - if UI changed: `cd ui && npm run typecheck && npm run build`
2. Commit and push to `origin master`.
3. On production:
   - `ssh electro`
   - `sudo -n git -C /opt/auctionscan fetch origin`
   - `sudo -n git -C /opt/auctionscan status --short --branch`
   - only continue if the checkout is clean
   - stop both units for the update and preserve the current database
   - `sudo -n git -C /opt/auctionscan merge --ff-only origin/master`
   - `sudo -n uv sync --project /opt/auctionscan/backend --locked`
   - `sudo -n chown -R root:svc-auctionscan /opt/auctionscan`
   - `sudo -n chmod -R u=rwX,g=rX,o= /opt/auctionscan`
   - `sudo -n chmod -R go= /opt/auctionscan/.git`
   - reinstall the units into `/etc/systemd/system/` if
     `deploy/systemd/*.service` changed, then `sudo -n systemctl daemon-reload`
4. Restart services:
   - `sudo -n systemctl restart auctionscan-api.service auctionscan-indexer@ethereum.service`
5. Verify:
   - `systemctl is-active auctionscan-api.service auctionscan-indexer@ethereum.service`
   - `curl -sS https://api.auctionscan.info/api/health`
   - `journalctl -u auctionscan-indexer@ethereum.service --since "10 minutes ago" --no-pager`

Production cautions:

- `uv sync --locked` must not change `backend/uv.lock`; resolve a lock/version
  mismatch before restarting either service.
- When a new registry factory is first supported, the indexer may rewind to the
  factory deploy block. Temporary API block lag is expected until the scan
  catches up.
- Do not run `--reproject` in production as part of a normal deploy unless the
  change specifically requires rebuilding projections from stored facts.
