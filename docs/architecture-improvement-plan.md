# Auctionscan: simple architecture fixes

Revised September 17, 2026 against commit `239a16d`.

This backend implementation is complete locally on `codex/architecture-cleanup`. UI work and UI tests are excluded. The sections below retain the implementation requirements; verified results are recorded at the end. Production deployment and its one-time data repair have not been performed.

## Direction

Make four focused changes: separate pricing capture from pricing projections, give chain fact writes one owner, extract collection and replay helpers from runtime, and avoid full replay when a live reorg removes no domain events.

Keep the existing SQLite database, one process per network, explicit SQL, writer transaction, captured facts, and read-only API. The current design is fundamentally sound. Improve its boundaries without replacing it.

Fixes 1–3 are behavior-preserving refactors and can ship independently. Fix 4 has two separately reviewed parts: first correct sweep handling so incremental indexing and replay agree, then add reversible expiry and the recovery shortcut. The shortcut depends on the lifecycle correction and on repairing existing projections before resuming indexing.

General scoped recovery, dependency-closure planning, projection checkpoints, new scope types, and a separate benchmarking program are outside this plan.

A data-changing reorg will still use full recovery. Its cost remains proportional to history. That limitation is explicit; the first recovery fix eliminates unnecessary replay, not every possible recovery bottleneck.

## Fix 1: split pricing at its natural boundary

**Problem.** `pricing.py` mixes HTTP requests, queue handling, fact persistence, calculations, and projection writes. It has 2,032 lines, including a roughly 550-line rebuild function.

**Change.** Use three main files, reusing two existing ones:

| File | What belongs there |
| --- | --- |
| Existing `prices_api.py` | `PricingApiClient`, provider capability data, HTTP parsing, timeout/auth/rate-limit handling, and its existing exception classes. |
| Existing `pricing.py` | The capture lifecycle: enqueue/select jobs, run the existing worker, validate completed sources, persist pricing facts, update queue state, and request projection refresh. |
| New `pricing_projections.py` | Canonical source resolution, loading stored pricing inputs, building take/round totals, writing pricing projections, and rebuilding taker pricing summaries. |

Keep `pricing_summary.py` for its existing provider-selection calculations. Move projection-only arithmetic helpers with the projection code. Keep each record with the code that owns it rather than adding a general-purpose pricing types module.

Move `PricingApiClient`, `ProviderCapability`, `_extract_detail_message`, and the provider-cache TTL to `prices_api.py`. Move `rebuild_pricing_projections`, `_rebuild_taker_pricing_summaries`, the surviving-source loaders/resolvers, and their arithmetic/status/scope helpers to `pricing_projections.py`. Move `_source_round` there as a shared source resolver accepting scalar source identifiers; the queue adapter `_queue_job_round` stays in `pricing.py`. Keep `PricingQueueJob`, `SelectedPricingJob`, `PricingAttemptResult`, and `PricingDrainSummary` with capture. The dependency direction is `pricing.py` → `prices_api.py` / `pricing_projections.py`; neither extracted responsibility imports the capture runtime or its job records.

First move functions with their behavior intact and update imports directly. Then make `rebuild_pricing_projections` readable by extracting a handful of named stages inside its own file: load inputs, select observations, build take results, build round results, and write results. Extract only real units of work; helpers that merely hide a large argument list do not improve the design.

Both scoped and full pricing rebuilds must keep using the same calculations. The existing `rounds` and `previous_takers` arguments already provide the required scope support.

**Preserve.** Decimal precision, deterministic pricing selection, source block hashes, unknown-versus-zero payments, estimate separation, queue retry age, and the existing single outstanding background request. All HTTP stays outside the writer transaction.

**Verify.** Run the existing pricing and fresh-job tests. They already cover scoped/full equality, disappeared takers, stale sources, transaction failure, and nonblocking requests. Add a regression case only if the extraction exposes an uncovered behavior.

**Done when.** Pricing projection code has no HTTP client or worker dependency, and provider transport changes have a clear home. Do not create a pricing framework or split every SQL helper into another file.

## Fix 2: give chain facts an explicit owner

**Problem.** `projections.py` writes raw logs and events as well as read models. Deployment and kick projectors also persist snapshot facts, obscuring which operations are safe to replay.

**Change.** Add one `facts.py` file for the chain fact SQL currently in `projections.py`:

- Raw log and domain-event insertion, including duplicate detection.
- Deploy and kick snapshot persistence and explicit snapshot backfill.
- Indexed block persistence/loading and canonical orphan-suffix deletion.
- Explicit deletion of derived `Take` domain events during maintenance.
- The existing event-history lookups needed to identify a kick's round and legacy sell token.

Move the existing insertion helpers, `persist_raw_logs`, `persist_prepared_events`, snapshot persistence/backfill helpers, indexed-block helpers, `delete_fact_blocks_above`, `_deterministic_round_id`, and `_resolve_event_from_token` together. Use ordinary module functions; give helpers shared with projections direct imports rather than compatibility re-exports.

Keep RPC observation capture and persistence in the existing `observations.py`, pricing audit persistence with the pricing capture lifecycle, and parameter decoding in `auction_params.py`. They already have specific ownership. Update `BlockReader.persist` to import indexed-block persistence from `facts.py`. `facts.py` must not depend on projections or runtime.

Keep `apply_batch_with_results` as a short batch coordinator. Its sequence becomes explicit:

1. Persist raw logs and domain events; retain the newly inserted events.
2. Persist the captured deployment/kick snapshots for those events.
3. Apply native projections and take projections.
4. Let the existing caller handle pricing and checkpoint updates.

The caller still commits everything in one transaction. Fact helpers accept its connection; they do not commit independently.

Remove snapshot writes from `_project_deployment` and `_project_kick`. Projection-only replay reads the stored snapshot and never attempts to capture or repair it. Explicit observation backfill remains the place for filling missing historical provenance.

Make the maintenance exception explicit. Move the `DELETE FROM domain_events ... event_name = 'Take'` statement out of `clear_take_state` into `facts.delete_derived_take_events(conn, chain_id)`. In `reproject_chain`, call it once inside `replace_projections`, after all replay inputs have been prepared and validated, before either the full or takes-only projection reset. `clear_take_state` and `clear_projection_state` then reset read models and operational queue state without deleting domain events. Live recovery continues to use `clear_rebuildable_chain_state` and reapply surviving stored takes; it must not invoke the maintenance deletion. Update direct test callers that intentionally regenerate takes to perform the same explicit deletion.

Keep the existing kick-context queries rather than inventing another numbering scheme. They can be shared between snapshot persistence and projection: all native events have already been persisted, and the queries use block/transaction/log order. Preserve the current handling of duplicate events and missing snapshots. Do not introduce a flag such as `replaying=True` that changes what a projector owns.

**Preserve.** Snapshot raw values, `param_schema`, source identity, same-block ordering, native facts, and pricing audit history. Full reproject and takes-only reproject retain their existing distinct behavior.

**Verify.** Existing projection, snapshot, legacy-contract, observation-backfill, and replay tests, with these focused assertions:

- During projection-only native replay, install a SQLite connection authorizer that denies `INSERT`, `UPDATE`, and `DELETE` on `auction_snapshot_facts` and `round_param_snapshot`. Replay must succeed without attempting those writes. Remove the authorizer in `finally` and compare complete snapshot rows, including provenance and creation timestamps. Row equality alone is insufficient because today's ignored inserts already leave existing rows unchanged.
- Keep the missing-snapshot case: offline replay raises `MissingObservation` before replacing current projections and does not silently populate a snapshot.
- Exercise multiple kicks in one block and duplicate batches; snapshot identity, round numbering, and existing rows must remain stable.
- Both maintenance modes regenerate derived take events while preserving native domain events, raw logs, snapshots, and pricing audit facts. Failure during replacement rolls the deletion and projection changes back together.

**Done when.** Each fact write has a clear owner, while the batch still commits atomically. The remaining projection code may be long; keep related auction and round logic together unless there is a concrete reason to split it.

## Fix 3: extract collection and replay helpers from runtime

**Problem.** `runtime.py` contains detailed event scanning and stored-input reconstruction alongside the watch loop, finality checks, and transaction sequencing.

**Change.** Add two small modules:

| New file | Move from runtime | Inputs |
| --- | --- | --- |
| `collection.py` | Factory/auction log scanning and native-event hydration. | The existing chain, ABI registry, hydrator, tracked addresses, and block range. |
| `replay.py` | Loading native/take replay events, restoring snapshots from fact rows, and rebuilding `PreparedEvent` values from stored data. | The caller's connection, existing chain/offline reader, and hydrator. |

Move `_scan_factory_events`, `_scan_auction_events`, and `_hydrate_native_event` to collection functions. Move `_load_replay_native_events`, `_load_replay_take_events`, `_snapshot_from_fact_row`, both `_load_persisted_*_snapshot` helpers, and `_replay_prepared_from_domain_event_row` to replay functions. Take scanning/re-derivation stays in the existing `TakeDetector`; this extraction does not create another take implementation.

Move the shared event-token metadata routine onto the existing `Hydrator` so collection and replay use one implementation. Replay uses its offline `BlockReader`; it must not fall back to live RPC.

Use ordinary functions and existing event records. Pass the dependencies a function actually needs. Do not pass the entire runtime object, create service base classes, or add another orchestration layer.

Keep the following in `IndexerRuntime`: process ownership, watch-loop error handling, discovery refresh, finality checks, sync sequencing, transaction boundaries, and the short recovery decision. Full reproject remains explicit maintenance. Keep its input-validation-before-replacement behavior.

Update callers directly; do not retain forwarding methods solely to preserve internal imports or test monkeypatches. Adjust affected tests to patch the actual collection/replay boundary.

**Verify.** Existing runtime, collection-boundary, finality, discovery-rewind, and observation tests. In particular, RPC must remain outside write transactions and missing offline inputs must leave the current database intact.

**Done when.** A reader can follow the sync workflow without reading ABI scanning or snapshot reconstruction details, and neither extracted module depends on `IndexerRuntime`.

## Fix 4: skip replay when the removed suffix contains no domain events

**Problem.** Every live-tail reorg currently wipes and rebuilds chain projections and pricing, even if the removed blocks contain no native or derived take events.

### 4a. Make sweep handling independent of projection timing

**Required prerequisite.** `_project_swept` currently closes a round only when its projected status is `live`. Incremental indexing can already have marked that round `expired` or `sold_out`; full replay applies native events before takes and reconciles expiry afterward. Review reproduced both discrepancies on an event-free rollback:

| Surviving history before the removed empty block | Incremental result today | Full recovery today |
| --- | --- | --- |
| Kick → expiry → sweep | `expired`, no `settled_at` | `settled`, `settled_at` at the sweep |
| Kick → sell out → sweep | `sold_out`, no `settled_at` | `sold_out`, `settled_at` at the sweep |

**Chosen behavior.** A sweep records closure of the latest round for its token, even if time reconciliation or take projection has already changed that round's status. There is no new `swept` status; the existing representation uses `settled_at`, with sold-out status taking precedence.

Change only the round update in `_project_swept`:

1. Keep the existing latest-round lookup by chain, auction, and swept token. If there is no matching round, keep the existing auction lifecycle update without changing any round.
2. If the round already has `settled_at`, preserve its existing closure and end time. Repeated sweeps must not overwrite them.
3. Otherwise, record `settled_at = event.timestamp` without gating on the current `live`/`expired`/`sold_out` status. Choose `sold_out` when `remaining_available_raw` is zero, otherwise `settled`, using a `CASE` in the existing update. Do not change inventory or take totals.
4. Keep the current end-time rule: use the sweep timestamp if `end_at` is absent or later; otherwise retain the earlier end. A prior sellout retains its earlier end time. A take applied later during replay can still establish the earlier sellout end and `sold_out` status through the existing take projector.

Do not change native/take application order or add a lifecycle framework. Merely accepting `expired` alongside `live` is insufficient: it leaves the sold-out timestamp discrepancy.

**Verify.** Extend `test_projection_lifecycle.py` / `test_replay_and_takes.py` and the existing reorg fixture. Compare split incremental batches, a combined batch, and full replay for expiry-then-sweep and sellout-then-sweep. Assert `status`, `settled_at`, `end_at`, and inventory explicitly, not just agreement between paths. Include a sweep before expiry, repeated sweeps, a previously settled round, and an unmatched token. Preserve the existing partial-take-before-sweep and take-after-native-replay cases.

For the expiry regression, use a short fixture duration: kick at block 102, end at timestamp 103, reconcile at block 104, sweep at block 105, and remove empty block 106 with ancestor 105. The corrected result is `settled`, closure at 105, end at 103. In a separate sold-out fixture, keep the scheduled end later than block 105 and sell all inventory at block 104 before the sweep; the corrected result is `sold_out`, closure at 105, end at 104. Use the fixture's timestamp offset consistently.

**Done when.** Both histories have the specified values regardless of batch boundaries or replay. Commit this correctness change separately. Fixes 1–3 need not wait for it, but 4b does.

### 4b. Add reversible expiry and the event-free branch

**Why a small fix is possible.** In the current implementation, event application changes auction state, takes, and projected token metadata. Indexed time can additionally change round expiry. Pricing captures against surviving occurrences remain valid audit observations; rolling back empty blocks is not a reason to discard them.

The safe fast path is therefore: no removed domain events, plus explicit reconciliation of time-derived state. This relies on the current projection ownership; its test should make that assumption visible.

**Change.** Add a single branch to the existing recovery function:

1. For ordinary live reorgs (`record_reorg=True`), before deleting facts, check whether any `domain_events` row for that chain has `block_number > ancestor_block`. Use `SELECT 1 ... LIMIT 1` without filtering event names; the current block index supports this lookup.
2. If an event exists, or `record_reorg=False`, run full recovery with the corrected projectors from 4a.
3. For an ordinary reorg with no removed domain events, remove the orphaned fact/header suffix using the existing deletion helper. Preserve event-derived projections, token metadata, taker totals, and pricing projections.
4. Reconcile expiry at the ancestor timestamp, remove any orphaned queue work using the existing source check, and update checkpoint hashes, health, and the reorg counter.
5. Keep all mutations in the existing writer transaction.

Use the existing distinction between an ordinary recorded reorg and maintenance calls. Factory-discovery rewinds, explicit reproject, and observation-backfill adoption continue through full repair. No new public switch, recovery planner, or policy class is needed.

Keep suffix deletion, the offline-reader reset, queue cleanup, ancestor timestamp lookup, and state updates common to both branches. Guard only projection clearing, historical event loading/application, and pricing rebuilding. An ancestor at or above zero still requires its stored header; absence raises `MissingObservation` and rolls back. For ancestor `-1`, preserve the current behavior of skipping timestamp reconciliation. Do not discard a pending pricing request merely because an event-free suffix changed; the existing commit-time canonical-source check remains authoritative.

**Necessary accompanying fix: make expiry reconciliation reversible.** The existing function moves live rounds to expired. Add the inverse for time-expired rounds whose end is at or after the indexed timestamp:

- Only reconsider `live` and `expired` rounds with remaining inventory and no `settled_at`.
- Preserve the current strict expiry boundary: a round expires when `end_at < indexed_timestamp`; equality remains live.
- Preserve sold-out, swept, and explicitly settled states.
- Require a non-null `end_at` for either expiry transition; do not infer a new deadline for an unknown end.
- Write only expiry rows whose status actually changes. Retain the existing terminal-state normalization and sold-out end-time repair in this function; adding the inverse expiry transition must not remove those repairs.

Use that same reconciliation function in ordinary sync and recovery. Do not add a second definition of expiry or per-round timers.

Raw transfer logs or RPC observations without domain events can still exist in a removed suffix. Delete them according to the existing canonical-fact policy; do not mistake their mere presence for a projected take. Conversely, a suffix containing even one derived `Take` must take full recovery.

**Verify with a few focused backend cases.**

| Case | Required result |
| --- | --- |
| Empty suffix with no expiry transition | Same checkpoint and semantic result as full recovery; no event or pricing replay. |
| Empty suffix crosses a round's expiry time | Correctly reopens at the ancestor, then expires again when replacement blocks advance time. Include equality at the end time. |
| Terminal rounds are present | Sold-out, settled, and swept rounds remain terminal. |
| Expiry or sellout followed by a surviving sweep | Keep the exact closure and end times established by 4a, including after an empty-suffix rollback. |
| Removed native event or derived take | Full recovery still executes and matches existing expectations. |
| Rejected transfer inputs without a take | Orphan logs/observations are removed without changing event-derived state. |
| Failure before recovery commit | The whole transaction rolls back, including facts and checkpoint. |
| Missing ancestor header | Raise and roll back; do not preserve projections at an unverified timestamp. |
| Maintenance/factory rewind | Continues through full repair, including a subsequent failed rescan. |

Use existing fixtures in `test_reorg_runtime.py`, `test_rpc_reorg_recovery.py`, and `test_factory_rewind.py`. Compare the fast path against the full-recovery sequence **after 4a**, on independent copies with the same facts and ancestor. Normalize only incidental projection timestamps and surrogate IDs; preserve source hashes, surviving fact contents, numeric values, `settled_at`, and `end_at` exactly. Assert expected lifecycle values and checkpoint hashes, health, and reorg counters independently. Do not hide differences by treating closure timestamps as incidental.

In the event-free tests, make historical replay loaders, projection clearing, and pricing rebuild raise if called. Cover the predicate separately with a suffix containing only a derived `Take`; it must still execute full recovery. Add a focused expiry boundary case for before, equal to, and after `end_at`, including advancing replacement blocks and a repeated reconciliation that performs no extra expiry update.

**Done when.** Event-free reorgs perform no historical event replay and no pricing rebuild. Reorgs that remove data retain the established full-replay behavior.

## Keep verification and measurement proportionate

The September 17 review ran all 187 backend tests and the generated API contract check successfully at `239a16d`. The sweep cases above were additional reproductions and are not covered by that baseline. Use the existing suite as the foundation; add the specified regressions without treating the old full-recovery output as the sole correctness oracle. UI tests are excluded.

Run these groups while editing (paths are relative to the repository root):

| Change | Focused test files under `backend/tests/` |
| --- | --- |
| 1 | `test_pricing.py`, `test_pricing_fresh_jobs.py`, `test_api.py` |
| 2 | `test_projections.py`, `test_projection_lifecycle.py`, `test_projection_legacy.py`, `test_replay_and_takes.py`, `test_observation_backfill.py`, `test_pricing.py` |
| 3 | `test_runtime.py`, `test_collection_boundaries.py`, `test_finality.py`, `test_factory_rewind.py`, `test_discovery_refresh.py`, `test_discovery_resilience.py`, `test_observations.py`, `test_observation_backfill.py`, `test_token_metadata_replay.py`, `test_replay_and_takes.py`, `test_reorg_runtime.py` |
| 4a / 4b | `test_projection_lifecycle.py`, `test_replay_and_takes.py`, `test_reorg_runtime.py`, `test_rpc_reorg_recovery.py`, `test_factory_rewind.py`, `test_observation_backfill.py`, `test_pricing.py` |

Use `uv --project backend run pytest backend/tests/<file>` for a focused group. Before each finished change, run `uv --project backend run pytest` and `npm --prefix ui run check:api`. No new dependency, generated API change, or schema migration is expected.

For recovery, add elapsed-time fields to the existing recovery log: total duration, whether replay was skipped, and pricing rebuild duration. Use `time.perf_counter()`. No new metrics tables, telemetry service, or scheduled job.

Make one repeatable local timing comparison using existing fixtures at small and larger histories. Compare an event-free reorg and a reorg that removes a take. Verify results as well as timing. A consistent SQLite backup can provide a representative sample; use copies, not a maintenance run against the live database.

The immediate performance acceptance criterion is structural and testable: an event-free reorg does not load/reapply historical events or rebuild historical pricing. Do not claim that all recovery has become independent of history or attach an invented latency guarantee.

If measurements show data-changing full recovery causes an operational problem, inspect which phase dominates first. Fix a specific query or repeated calculation when possible. Revisit auction-scoped repair only if simpler changes cannot meet a recorded operating requirement. It is outside this implementation, not an unimplemented part of an advertised complete recovery optimization.

## Delivery order and stopping point

| Change | Scope | Release condition |
| --- | --- | --- |
| 1. Pricing separation | Reuse `prices_api.py`; add `pricing_projections.py`; simplify the rebuild function. | Existing pricing behavior and tests agree. |
| 2. Fact ownership | Add `facts.py`; make snapshot persistence and maintenance take-event deletion explicit. | Native/snapshot/pricing facts survive maintenance; snapshot writes are forbidden during projection-only replay; normal sync remains atomic. |
| 3. Runtime extraction | Add `collection.py` and `replay.py`; share metadata loading through `Hydrator`. | No cyclic dependencies, hidden RPC in replay, or network work in write transactions. |
| 4a. Sweep correctness | Correct `_project_swept` in a separate behavior-change commit. | Incremental and replayed lifecycle values agree for expired and sold-out rounds; the existing-data repair below is rehearsed on a copy. |
| 4b. Recovery fast path | Add the event-existence branch and reversible expiry reconciliation after 4a. | Targeted recovery cases, full backend suite, and local timing comparison pass; existing projections are repaired before indexing resumes. |

Separate mechanical moves from calculation or recovery changes in reviewable commits. These fixes require four new source files, no new package hierarchy, and no new tables or configuration.

### Deployment and existing-data repair

Fixes 1–3 require no production reproject. Follow the existing deploy procedure for those refactors.

Deploying 4a to an existing database requires a one-time **full** `--reproject` from stored facts before resuming indexing with 4b. This records the missing sweep closures and prevents the fast path from indefinitely preserving old lifecycle state. `--takes-only` is insufficient because it does not replay native sweep events. This is a specific correction, not a new normal-deployment step or startup repair.

1. Rehearse on a consistent SQLite backup using the new code. Run `--check-observations`, then full `--reproject` with `--db` pointing to the copy. Verify the lifecycle changes, unchanged native/snapshot/pricing audit facts, and offline replay. Record duration for the maintenance window. Missing observations must be handled through the existing explicit backfill workflow before repair; do not add a live-RPC fallback.
2. On production, stop `auctionscan-indexer@ethereum.service`, take a consistent backup, and deploy the checked revision using the clean-checkout procedure in `AGENTS.md`. Keep the indexer stopped until the repair and verification finish. The read-only API can remain available against the previously committed state during the projection transaction.
3. From `/home/wavey/auctionscan`, run:

   ```sh
   uv --project backend run python -m backend.indexer.app --network ethereum --db /home/wavey/auctionscan/backend/data/auctionscan.sqlite3 --check-observations
   uv --project backend run python -m backend.indexer.app --network ethereum --db /home/wavey/auctionscan/backend/data/auctionscan.sqlite3 --reproject
   ```

4. Verify expected round closure/end times and the preserved facts, then restart the API and indexer and perform the existing service, health, and log checks. If repair fails, leave the indexer stopped, resolve the missing input or failure, and retry the existing maintenance command; do not enable the fast path against unrepaired state. The writer transaction keeps the previously committed projections intact on replacement failure.

The database schema and public API remain unchanged. Rolling code back does not undo repaired projection values; returning to pre-4a behavior requires a deliberate data-recovery decision using the backup and would reintroduce the known inconsistency. If implementation reveals a necessary schema change, handle it explicitly through a new writer-owned migration and the bootstrap helper, rather than quietly expanding a refactor.

Stop when responsibilities are clear, the existing replay guarantees hold, and unnecessary recovery work is removed. Further file splitting, API restructuring, checkpoints, and general recovery machinery require their own demonstrated need.

## Implementation and verification results — September 17, 2026

The implementation uses the four planned source modules, with no database schema, public API, dependency, or configuration changes. Work is separated into reviewable commits:

| Commit | Change |
| --- | --- |
| `3d5875c` | Mechanical pricing transport/projection separation. |
| `f9628b8` | Explicit pricing input loading, observation selection, take/round rebuilding, and taker rebuilding stages. |
| `69f6fcd` | Fact ownership, explicit maintenance deletion, snapshot write protection, and atomic replacement tests. |
| `853ce0c` | Collection/replay extraction, shared hydration, and tests at the new function boundaries. |
| `448ca90` | Sweep closure correction with incremental, combined-batch, and replay comparisons. |
| `c2a931f` | Reversible expiry, the event-free recovery branch, rollback/equivalence tests, and local timing cases. |

Final validation:

- `uv --project backend run pytest -q`: **209 passed**. The only warning is the existing dependency warning from `websockets.legacy`.
- `npm --prefix ui run check:api`: passed; generated types remain unchanged.
- Undefined-name checks on backend source/tests and `git diff --check`: passed.
- Snapshot replay runs with SQLite writes to both snapshot tables forbidden. Missing observations and snapshots refuse replacement; both maintenance modes roll back failed take regeneration.
- Event-free recovery tests forbid projection clearing, historical event loading, and pricing rebuilding, and compare against full repair on independent backups. They include actual stored pricing facts, rejected transfer inputs, expiry reversal, terminal/swept rounds, and missing-header/commit failures. Native-event and derived-take removal still exercise full repair. Existing factory-rewind and finality tests pass.
- Full repair on a backup of a captured fixture restores the legacy expired/swept round to its expected closure and end timestamps. RPC and live header access are disabled during repair; stored facts and the original database remain unchanged.

The repeatable timing comparison is part of the existing recovery tests, without latency assertions or a separate benchmark program:

```sh
uv --project backend run pytest backend/tests/test_reorg_runtime.py -k recovery_paths_agree -q -s
```

One local run measured the complete recovery writer transaction, including commit:

| Additional historical takes | Empty suffix, fast path | Empty suffix, forced full repair | Suffix removes a take, full repair |
| --- | --- | --- | --- |
| 20 | 0.328 ms | 3.722 ms | 3.895 ms |
| 1,000 | 0.325 ms | 127.729 ms | 125.442 ms |

These are synthetic fixture measurements, not production latency estimates. Both sizes assert matching projection results against independent full-repair copies. The structural guarantee is the absence of historical event/pricing replay on the event-free path; other recovery queries still have their existing costs.

The local `backend/data/auctionscan.sqlite3` predates `rpc_observations` and was inspected read-only, not modified or backfilled. The deployment procedure above still requires a rehearsal on a current production backup, sufficient stored observations, and a full production reproject before resuming indexing with the lifecycle correction. No push, production restart, or production maintenance was performed during implementation.
