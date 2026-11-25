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
- live capture quotes an event within `DEFAULT_MAX_CAPTURE_LAG_SECONDS` or
  not at all, and some lots (LP tokens, principal tokens) no live source
  quotes at any time. The replay prices what that leaves, at the event's own
  block, once the event is confirmed: the indexer runs it beside live capture
  (`ReplayCapture`, a batch at a time off the writer's thread), where it also
  quotes again whatever an older method quoted, and `--backfill-pricing`
  (writer maintenance) runs the same replay over a whole backlog. Beside
  live capture the replay is paced, one batch a minute, and waits five
  minutes when the prices service rate-limits it: live capture asks the same
  service under the same limit and has only minutes to quote an event. The prices service's `curve` provider supplies today's route,
  Curve Router NG's `get_dy` evaluates it at the block before the event (a
  staged window: the last block before it opens), and crvUSD's
  `AggregatorStablePrice` values the want token through crvUSD at that block.
- a replayed quote is the lot's best exit at that block, as an aggregator's
  quote would have been: the route is one exit among the others, not the
  answer whenever it exists, because a thin pool can pay far less for a lot
  than redeeming it does. An LP lot is also withdrawn from its pool, into one
  coin (`calc_withdraw_one_coin`) or into every coin in proportion to the
  pool's balances; the pool is the MetaRegistry's, else the LP's `minter()`,
  else the LP itself. A coin, or the lot itself, is also redeemed, at most
  twice in a row: a matured principal token (`redeem`, else `redeemForIBT`),
  a Spectra wrapper (`unwrap`), an ERC-4626 share (`redeem`), a share of an
  older vault (`withdraw`, for the asset its `token()` names: iearn's yTokens
  and Yearn's v2). A principal token before maturity has no redemption. An
  LP lot is withdrawn whatever becomes of its own route: asked to route some
  LP tokens, Curve's API answers with an error every time, and that only
  defers a lot that is no LP token. A redemption counts for what it
  delivers, never for `previewRedeem`: `eth_simulateV1` runs it as the holder
  at that block (the pool for its coins, the auction for its lot) between two
  reads of the holder's balance, so one that reverts, queues or delivers
  nothing is no exit. Atomic takers' own exits (withdraw, redeem, route to
  crvUSD in the take transaction) are what these paths reproduce. The best
  exit must absorb the lot: the lot has to fetch 95% of the price a 1% slice
  of it fetches along the same exit, or there is no quote. A lot that moves
  its own market further would not have been sold whole there by a seller
  with other venues, and Curve is the only venue the replay knows: set beside
  live quotes of the same takes, the replays that fell short of this were
  the ones below the market. A coin's route is asked for about its own size
  (amounts within a factor of four share one), since a route that suits a
  small amount can be a pool too thin for a large one. Today's route is one
  sample of what Curve would use now and changes from hour to hour; for a
  small amount it can name a pool that did not exist, or held next to
  nothing, at the event's block. Where the route for the amount does not
  work at the block or cannot absorb it, the routes for 10 and 100 times the
  amount are tried in turn (`ROUTE_SCALES`), evaluated for the amount itself:
  larger sizes lean on deeper pools, which are older.
- replays are ordinary pricing facts with `capture_origin = 'block_replay'`,
  provider `curve`, `capture_state = 'fresh'` and zero lag. Projections
  choose one fresh observation per event: a live one if there is any, the
  first captured, because it is what the market said at the time; otherwise
  the newest replay, because a later replay is the same question answered by
  a better method. Facts stay append-only. An event with no exit, or none
  that absorbs the lot, is recorded as a failed replay and is final until
  asked again: `--retry-failed` reopens the events a replay found no price
  for, `--requote` the events an older method answered, each adding a new
  attempt beside the old. Every replayed quote records the method's
  `METHOD_VERSION`; raise it whenever the replay would answer the same event
  differently, or `--requote` finds nothing to do. A failed attempt never
  takes a price away. Network and provider errors leave no fact, and a call
  that breaks instead of reverting (an old token's bad jump) is an answer,
  not an error. The contracts live in `config.yaml` under `replay_pricing`
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
  - `curve-1` -> `curve_lot_bounds`
- `v1_fixed_decay` is special:
  - `starting_price` stays unscaled
  - `minimum_price` is absent
  - `step_decay_percent` is synthesized from the known fixed contract constant
  - `step_duration_seconds` remains `NULL`
- `v1_wad_start_wad_bps` is like `v1_wad_bps`, except `starting_price_raw`
  is also WAD-scaled and must be decoded by dividing by `1e18`
- `curve_lot_bounds` (Curve's DutchAuctionBurner) stores `start_total` in
  `starting_price_raw` and `floor_total` in `minimum_price_raw`, both lot totals
  in raw want units. The decoder scales them by the want token's decimals into
  `starting_price` and `floor_price`; `minimum_price` is absent, because the
  price holds at the floor until the window ends instead of cutting off.
  `step_decay_percent` is derived: the curve reaches the floor in its last of
  `(auction_length - 1) // step_duration` steps
- duration fields are still part of the decoded layer even when they are
  identity transforms today; that keeps units explicit and the projection
  schema stable

## Curve Burners

Curve's `DutchAuctionBurner` (version `curve-1`) is indexed through the same
round model as Yearn auctions; the decoder translates its events so rounds,
takes and pricing need few per-protocol branches.

- It is a singleton per chain with no factory, seeded from `auctions:` in
  `config.yaml`. Seeded `tracked_auctions` rows have no factory and survive
  projection rebuilds; a new seed rewinds the indexer to its `start_block`.
- `EconomicsSet` creates the auction row and its settings snapshot
  (`auction_snapshot_facts` kind `economics`); later ones retune the curve.
- `LotStaged` becomes `AuctionKicked` with the lot's window in `startsAt` and
  `endsAt`. One token and window is one round. Round numbers are assigned in
  one place, `facts.kick_round`, when kicks are persisted: the first stage
  opens the round, keeps its `round_param_snapshot` row and is the round's
  stable link; later stages for the same window re-snapshot the lot. The
  latest stage is authoritative before the window opens, so it also undoes a
  recovery. Collection reads no snapshot for a repeated stage.
- The round is `scheduled` until its window opens, with `kicked_at` at the
  window start. Windows exclude their end: a Curve round expires at
  `endsAt`, a Yearn round only after its last second. A round with nothing
  sold is never `sold_out`.
- `Recovered` becomes `AuctionSwept`; only the recovered transfer is excluded
  from takes.
- Takes stay transfer-derived: one address-less `Transfer` scan by sender
  covers native takes and settlement adapters. A take names its window, and
  the projection resolves its round. A native take reads its `Taken` log: the
  caller is the taker, and payment and the lot's remaining balance come from
  it. A CoW fill reads the burner-owned `Trade` for its payment and is
  credited to the transaction sender (the settling solver), not the
  settlement contract; its remaining balance is an `available(token)` read
  kept as an observation. Remaining inventory comes from these observations,
  not from the stage minus sales: rebasing lots (stETH) can sell more than
  their stage. Each receipt log pays for one fill at most.
- The kick quote is queued when indexed time crosses `startsAt`, whatever the
  round's status, for the lot as finally staged and linked to the first
  stage. A kick quote for another amount does not price the round. One fresh
  want-token price answers every queued request for the same token and
  moment.

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
falling back. `status` accepts the stored round statuses only (`all`,
`scheduled`, `live`, `sold_out`, `expired`, `settled`); there are no alias
spellings. `protocol` (`all`, `yearn`, `curve`) is resolved to contract
versions, not stored. On `/api/takers` it narrows the totals as well as the
rows: the taker summaries are per taker across every protocol, so one
protocol's totals are rolled up from its takes and their `take_pricing` by
the rules `taker_pricing_summary` is built with. The UI's status chips offer Live, Sold
(`sold_out`) and Expired; the list without a status chip is all rounds,
scheduled and settled ones included.

`sort_by` on `/api/rounds` orders the whole filtered list before it is paged:
`kicked` (the default, newest first), `value` (largest first) and
`pnl_percent` / `pnl_usd` (worst first). `value` is the market value a list
row shows: what sold, valued when it sold, else the kick quote. The UI's
`roundMarketValue` picks the figure by the same rule; change them together.
Rounds without the figure come last.

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
- `auctions`: singleton auctions no factory deploys (Curve burners), each with
  its deployment block as `start_block` and a factory-less version.
- `replay_pricing`: the Curve Router NG, crvUSD, crvUSD price aggregator and
  Curve MetaRegistry that the pricing replay reads at past blocks. A network
  with it replays beside live capture and can backfill pricing; one without
  it does neither.
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

Production is split between Vercel, which serves the static React UI from
`ui`, and a single Linux host running the FastAPI API and the Ethereum
indexer under systemd. The unit files live in `deploy/systemd/`.

- Public site: `https://auctionscan.info`
- Public API: `https://api.auctionscan.info` (`/docs`, `/api/health`)
- Pushes to `master` trigger the Vercel Git integration
- `VITE_API_BASE_URL` must be set in the Vercel project environment to
  `https://api.auctionscan.info/api`; the repo default `/api` is for
  same-origin local development and would 404 in production
- Only `VITE_`-prefixed variables reach the browser bundle. Never give an RPC
  URL or API key that prefix

The API is read-only and binds loopback only; TLS and the public hostname are
handled by a reverse proxy shared with unrelated services on that host, so its
configuration is not vendored here.

Host names, filesystem layout, credentials and the step-by-step release and
verification commands are in `OPERATIONS.private.md`, which is deliberately
untracked because this repository is public. Follow that runbook for any
deployment; do not re-add host specifics to this file.

Release cautions that matter when changing code:

- `uv sync --locked` must not change `backend/uv.lock`; resolve a lock or uv
  version mismatch before restarting either service. `exclude-newer` in
  `backend/pyproject.toml` is recorded in the lockfile, so changing it
  invalidates the lock on the deployment host.
- Changing a file in `deploy/systemd/` means the units must be reinstalled and
  `systemctl daemon-reload` run before the restart.
- When a new registry factory or `auctions:` seed is first supported, the
  indexer may rewind to its deploy block. Temporary API block lag is expected
  until it catches up.
- Do not run `--reproject` as part of a normal deploy unless the change
  specifically requires rebuilding projections from stored facts.
