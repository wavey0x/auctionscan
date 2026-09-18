# Auctionscan legacy cleanup and clean cutover

Reviewed against `d6c9158`. Status: implementation and rehearsal complete; production deployment awaits authenticated Vercel rollback access.

Implementation: `0bbf902`, `f235500`, `b38f3c4`, `d768a44`. Runtime source is 792 lines smaller (57 added, 849 removed), excluding generated types and tests. The existing locally ignored `AGENTS.md` inventory was updated without adding it to version control.

Verified September 17, 2026:

- Backend: 217 tests passed. UI: 19 tests passed; typecheck, build, generated OpenAPI check, and whitespace checks passed.
- A consistent production backup contained Ethereum only: 22,223 raw logs, 22,004 domain events, 266 deploy snapshots, and 4,717 kick snapshots. All 10,717 required observation blocks were complete. Snapshot provenance, integrity, foreign keys, and the finalized checkpoint hash were verified.
- Migration took 0.136 seconds locally; every retained row matched its baseline fingerprint. Fresh and production-upgraded projection columns, constraints, and indexes matched. Transaction-failure rollback and incremental writes without replay passed.
- Full replay (22,004 events) and takes-only replay (5,768 events) each completed with networking forbidden in approximately 70 seconds, including observation checks. All retained semantic projections, native events, captured facts, aliases, and checkpoints matched; no repair was needed.
- The migrated API served representative auction, round, take, and taker responses before replay. The removed route returned 404. Desktop and 390px mobile inspection confirmed the compact take layout, removal of Gas, provider selection, transaction/copy controls, and direct-link reload. Restoring the backup with `d6c9158` served the old API contract successfully.

Rehearsal evidence and database copies are kept outside the repository in `/tmp/auctionscan-cutover-20260918`; the source backup is also retained on `electro` under `/home/wavey/auctionscan-backups/legacy-cutover-20260918`. Backup SHA-256: `64982d3b21797be15b86aa7555fb43ed960bc2eaf86d1db88711a8adb8352c2a`. Production remains on `d6c9158` until the switch below.

Ship one deletion-focused release: remove unused API paths, ten redundant projection columns, one unread projection table, obsolete bootstrap repair, and pre-finality adoption. Preserve useful product behavior and durable facts. The substantial win is fewer representations, writes, and recovery branches to maintain; do not claim a performance or database-size improvement without measurement.

The necessary additions are one forward yoyo migration, small validity checks at existing boundaries, focused regression coverage, and updated documentation. Add no dependency, service, command, abstraction layer, or permanent verification framework. Runtime code should shrink materially; report its diff separately from generated types and tests. Do not trade readable code or useful coverage for a line-count target.

**1. Fix the scope before implementation**

The release includes dead code, redundant API fields and routes, unused configuration, unused projection storage, and removal of old-database conversion paths from normal application code.

The following work is excluded at the user's request:

- Consolidating top-level pricing and `pricing_by_source`, changing source selection, or removing the current pricing-selection fallbacks.
- Replacing `IndexerSettings.chains` with a single `chain`, merging `sync_once` with `sync_chain_once`, or merging `reproject` with `reproject_chain`.
- Renaming `total_auction_profit_bps` or otherwise redesigning pricing models, pagination, common response models, or query APIs.

Keep the current one-process-per-network design and shared SQLite database. Keep occurrence-based URLs, finality/reorg handling, observed-versus-estimated payment semantics, pricing eligibility, polling, and current projection calculations.

Supported historical contracts remain supported: their ABIs, parameter schemas, fixed-decay behavior, legacy auction IDs, and transfer-derived take detection describe real on-chain history. Removing application compatibility does not remove those inputs from Auctionscan.

Do not add dual writes, alternate API versions, old-field aliases, feature flags, migration planners, version negotiation, automatic schema repair, or browser compatibility detection. Retain existing migration identities. Older backup restoration uses the application revision saved with that backup.

**2. Delete the confirmed unused code and settings**

| Location | Delete or simplify | Required boundary |
| --- | --- | --- |
| `backend/src/backend/indexer/address_aliases.py` | Delete `collect_receiver_alias_addresses` and `load_existing_address_aliases`, plus imports used only by them. | Keep the active alias backfill, multicall lookup, and individual-call fallback. |
| `backend/src/backend/indexer/facts.py` | Delete `prune_indexed_blocks_through`. | Keep indexed headers needed for replay and finality; this does not introduce pruning. |
| `backend/src/backend/indexer/decode.py` | Delete `AbiRegistry.erc20_contract`, `_erc20_abi` loading, and the write-only `_factory_contract_abis` cache. | Keep factory ABI loading for event decoding and the active auction/registry methods. |
| `backend/src/backend/indexer/types.py` and `config.py` | Remove `ProjectPaths.erc20_abi_path` after deleting its runtime consumer; remove unused `ChainConfig.enabled`. | Keep `FactorySeed.enabled`, which discovery and indexing use. Update constructors and fixtures directly. |
| `backend/abis/ERC20.json` | Retain as a test/reference asset for `test_observations.py`. | An unused runtime accessor does not make this file unused. |
| `backend/src/backend/indexer/versioning.py` | Remove the unused `ContractVersionMetadata.historical` field and its assignments. | Keep all supported contract version definitions. |
| `backend/src/backend/api/db.py` and `config.yaml` | Remove `block_lag_warn` and `block_lag_critical` fields, parsing, values, and comments. | Keep the current health calculation and reported `block_lag`. |
| `ui/src/shared/lib/format.ts` | Delete `formatLongRelativeTime` and its now-unused date-fns import. | Keep other timestamp functions and date-fns uses. |
| `ui/src/shared/api/client.ts` | Delete unused `getAuctions` and `getTokens` methods and their unused imports. | Keep the existing `/auctions` and `/tokens` server endpoints; lack of a UI caller alone does not establish an obsolete API feature. |
| `.env.example` | Correct the stale description of the prices service as a token metadata/logo backfill service. | Keep active pricing configuration and runtime behavior. |

Re-run reference searches at implementation time. Update direct consumers and fixtures; do not leave forwarding functions or compatibility exports. No new dependency or general dead-code framework is needed.

Replace configured `version: legacy` placeholders with verified supported versions. The pinned artifact index identifies factory `0xCfA510188884F199fcC6e750764FAAbE6e56ec40` as `1.0.2`; the [verified Arbitrum factory source](https://arbiscan.io/address/0xCd1E4c17A5485f2a6DF1C01cC65EFDe25c951dBB#code) also uses the `1.0.2` fixed-decay contract, with governance-only kick and `forceApprove` calls. Its parameter, getter, and event semantics match the pinned `1.0.2` source. Keep the current loader. Delete the disabled, unused `local` factory stub and its unused `ANVIL_RPC_URL` example after confirming no local workflow depends on them; do not invent a factory version or build local setup support as part of cleanup. An unverified version is not permission to remove supported network history.

**3. Cut the obsolete API contract and update its UI consumers**

Make these removals together in `api/models.py`, serializers, route/query owners, generated TypeScript, and fixtures:

| Current surface | Final surface |
| --- | --- |
| `GET /api/auctions/{auction_address}/rounds` | Delete the route. The auction page already uses `GET /api/rounds` with `chain_id` and `auction_address`. Keep that filtered route. |
| `AuctionRound`, `AuctionRoundsResponse`, `auction_round_from_row`, `list_auction_rounds` | Delete the complete unused response path and its imports/type aliases. This also removes its `round_start`, `round_end`, `transaction_hash`, and null token-price fields. |
| `TakerTake.sequence` | Delete; keep `take_seq`. |
| `TakerTake.sold` | Delete; keep `amount_taken`. |
| `TakeDetail.auction_address` | Delete the redundant detail-only alias; retain inherited `auction`, which the current modal redirect uses. Do not rename fields across unrelated response types. |
| `TakeListItem.amount_taken_usd` | Delete the always-null placeholder. Keep actual-paid USD and expected-payment fields. |
| `TakeDetail.token_prices`, `TakeDetail.take_quotes` | Delete the unconsumed, loosely typed duplicate arrays. Keep typed `price_facts` and `quote_facts`. |
| `TakeDetail.gas_price`, `base_fee`, `priority_fee`, `gas_used`, `transaction_fee_eth`, `transaction_fee_usd` | Delete all six always-null fields. Remove the Gas entry in `TakeExpandedContent`. |

Remove the unconsumed `PricingQuoteProvider.route`, `PricingQuoteProvider.raw_provider_payload`, and `PricingPriceProvider.raw_provider_payload` API fields. Then delete `_provider_payloads_from_fact`, `_route_from_provider_payload`, and their serializer plumbing. This makes the old `legacy_provider_rows` and `routing_path` presentation adapters unnecessary without converting stored audit payloads or adding a new projection.

The structured audit responses continue to expose captured values, provider status, ordering, errors, timing, fact IDs, and summaries. Original provider responses remain byte-for-byte in `aggregate_response_json` in SQLite. The API stops reconstructing unused raw payload/route presentation; no raw audit fact is removed. Provider `estimated_gas` is captured quote data and remains; it is distinct from the unimplemented transaction-gas fields above.

Keep top-level canonical pricing, `pricing_by_source`, source options, and current pricing helpers as they are. In particular, canonical pricing comes from `take_pricing`/`round_pricing`, while provider rows come from the source tables. Removing their assembly logic would change current behavior and is outside this release.

Regenerate `ui/src/shared/types/generated.ts` from local OpenAPI and update `ui/src/shared/types/api.ts`. Do not hand-edit generated output or preserve old types to make tests pass. Assert that removed response keys and the removed route are absent from both actual responses and OpenAPI. Confirm the removed route returns 404.

Follow `ui/styles/STYLESHEET.md`. Remove the empty Gas entry and let the existing grid reflow; do not replace it with another metric, placeholder, card, or component system. Check the resulting mobile/desktop layout, alignment, readable values, keyboard focus, and inline copy/explorer actions. Preserve table density, source selectors, modal navigation, and observed-versus-estimated payment labels.

**4. Drop the unused projection storage**

Use one new writer-owned yoyo migration, proposed as `0018_legacy_cleanup.py` if that number is still free. Update the bootstrap schema in the same change.

| Projection | Remove |
| --- | --- |
| `take_pricing` | `canonical_from_price_fact_id`, `from_token_price_usd` — both are always written as `NULL`. |
| `round_pricing` | `kick_contract_expected_out_raw`, `kick_start_premium_bps` — both are always written as `NULL`. |
| `rounds` | `minimum_price_raw`, `starting_price_raw`, `step_decay_rate_raw`, `step_duration_raw`, `auction_length_raw` — duplicate raw settings with no current runtime readers. |
| `auctions` | `has_enabled_tokens` — maintained but not read by the running application. |
| `auction_param_history` | Drop the table and `_append_param_history` calls; it has no current runtime reader. Parameter-change events remain in `domain_events`. |

Update insert column lists, value tuples, replay clearing, and tests in the same commit. Remove `_recompute_enabled_tokens` and its calls while retaining the lifecycle updates already performed by enable/disable projectors.

Keep decoded round settings. Keep raw settings in `round_param_snapshot` and `auction_snapshot_facts`, and keep raw settings in `auction_current_params`, where incremental parameter updates still need them. Do not remove `auction_tokens.currently_enabled` or lifecycle fields used by detection.

The migration only removes these targets and preserves surviving values, constraints, and indexes. Prefer direct SQLite column/table drops supported by the deployed runtime; avoid rebuilding entire tables when unnecessary. Use individual statements in the yoyo transaction, with no `executescript` commit boundary. Limit schema checks to targets already absent on fresh bootstrap. No fact conversion, RPC, repricing, reproject, or database compaction is needed.

Verify fresh bootstrap and upgrade from a populated pre-cleanup database stamped through `0017`. The upgrade fixture must contain the old columns/table; using the edited bootstrap would miss the actual deletion path. Compare surviving column definitions, constraints, and indexes, plus retained row values. Test rollback of a failed transaction, not a reverse migration.

**5. Remove obsolete bootstrap repair and runtime adoption**

Simplify `ensure_current_schema` to creation of the current schema and observation schema. Delete its pre-yoyo repair calls and unreachable helpers, including the obsolete decoder wrapper. Bootstrap must not reconstruct snapshots from projections. In `test_migrations.py`, retire `test_apply_pending_migrations_upgrades_older_db`, its large private `_build_older_schema_db` fixture, and the wrapper-only decoder test. Replace their obsolete contract with the focused current-database upgrade coverage above; keep canonical decoder and historical-contract tests.

Migrations `0003`, `0004`, and `0005` import helpers from `db_migrations/helpers/schema_v0001.py`. Retain their required helpers and tests in the migration package. Keep `0008`'s historical payload parser; delete its counterpart in the running API. Do not reset stamps, squash history, move old repair code into a new utility, or duplicate it in a recovery script.

Before retiring adoption, check observations, deploy/kick snapshot provenance, and finality anchors for every indexed network, including inactive ones. Use the old application for any required preparation, preserving the original backup. Retained working databases must meet this boundary; archived backups stay paired with their old revision.

Remove `runtime.py`'s pre-finality adoption branches, `_adopt_backfilled_prefix`, and the `resume_indexing` result shape. Delete `backfill_snapshot_fact`; explicit current-data backfill uses existing `persist_snapshot_facts` to insert genuinely missing snapshots without overwriting captures.

Keep `--check-observations`, current-data `--backfill-observations`, and branch/hash validation. Reject an established database missing finality provenance, while allowing a never-synced network to initialize. Update the existing error message: directing users to the new `--backfill-observations` would be misleading once it cannot adopt old data. Direct them to preparation with the saved old revision. Backfill must not report success after leaving an existing null-provenance snapshot unrepaired; fail clearly without adding an adoption path.

Use current-model observation fixtures with deliberately missing inputs. Replace adoption assertions with refusal checks; retain partial backfill, transport failure, mismatch refusal, unchanged existing facts, and offline replay coverage. Keep `test_projection_legacy.py`: its historical contracts remain supported.

**6. Implementation order and review boundaries**

| Commit | Contents | Local verification |
| --- | --- | --- |
| 1 | Dead code, unused settings, explicit config versions, stale comments. | Reference checks; existing config, decode, observation, alias, and health tests; UI typecheck. |
| 2 | Obsolete route/response fields, unused raw audit presentation, Gas removal, generated contract. | API tests; generated contract check; UI tests/typecheck/build. |
| 3 | Projection deletions, bootstrap cleanup, new migration, obsolete fixture deletion. | Fresh bootstrap; populated current-DB upgrade and subsequent incremental indexing without reproject; transaction failure rollback; projection/replay/pricing tests. |
| 4 | Retire old adoption/snapshot mutation paths; update current-model maintenance tests and operations documentation. | Observation/backfill, finality, reorg, factory rewind, and both replay modes. |

Review these as separate changes, then deploy one final revision. Do not push intermediate breaking commits to `master`: its Vercel integration publishes the UI automatically. Use a `codex/` implementation branch and record the final release SHA.

Update `AGENTS.md` to remove deleted projections from its inventory, `OPERATIONS.md` to describe the new preparation boundary, and `README.md`/`.env.example` where instructions changed. Earlier completed implementation plans can remain historical records.

**7. Required checks and rehearsal**

Use existing test files and fixtures. Add focused coverage only for changed contracts, migration preservation/atomicity, and current-model refusal/replay behavior. Use small rehearsal queries or a task-local script; do not build a reusable schema-diff, fingerprint, or migration framework.

```sh
uv sync --project backend --locked --extra test
uv --project backend run pytest
npm --prefix ui run generate:api
npm --prefix ui run check:api
npm --prefix ui run test
npm --prefix ui run typecheck
npm --prefix ui run build
git diff --check
```

Use the uv version pinned by the repository. API generation runs without a database or RPC connection. Record actual results during implementation; this plan does not claim those tests have run for the proposed changes.

Rehearse the whole release on a consistent production SQLite backup, leaving the source snapshot untouched:

1. Record source SHA/configuration, applied migrations, integrity/foreign-key checks, indexed networks, and checkpoints. Complete the readiness checks in section 5 with the old application; if preparation changes data, save a new prepared baseline.
2. Fingerprint complete rows in `chain_logs`, `domain_events`, both snapshot tables, all four pricing audit tables, `rpc_observations`, `indexed_blocks`, `sync_state`, and address aliases. Include raw audit JSON strings. Record surviving projection values as well.
3. Migrate a copy and verify the planned schema, unchanged retained rows, and no pending migrations. Reapplying pending migrations must be a no-op. Exercise the API/UI on this migrated copy **before replay** so replay cannot hide an incomplete migration. Cover subsequent incremental writes in the upgrade test.
4. On independent migrated copies, run full and takes-only reproject for every indexed network with network access forbidden. Both must use stored inputs. Compare retained projection semantics: auction identity/version, decoded parameters, metadata, round lifecycle/inventory, take occurrences/payments, taker totals, and pricing. Exclude removed fields and incidental regenerated IDs/bookkeeping timestamps. Native events and captured facts must stay exact; compare regenerated `Take` events by source occurrence and semantic payload. Existing replay changes to the operational pricing queue are allowed.
5. Investigate any semantic mismatch. If it also occurs with the old application, record it as a separate existing repair need; do not silently fix it through this cleanup. A deletion-only release must not require new derivation behavior.
6. Exercise filtered rounds, direct round/take links, corrected-round redirects, live-price snapshot mismatch, provider selection, taker pages, and mobile/desktop expanded takes. Check `/openapi.json`, `/docs`, and `/redoc`; use existing automated coverage and a focused browser check.
7. Record results and migration duration, and rehearse restoring the saved database with its old release. Use the measured cutover steps to size the maintenance window.

**Production needs migration and verification, not full reproject.** The deleted storage has no retained semantic change to rebuild. Offline replay on backup copies proves replayability. Only a separately identified, justified repair may add production replay; specify its affected networks and rehearse it before changing the rollout.

**8. Production switch**

The production checkout is `/home/wavey/auctionscan` on `electro`; its shared database is `/home/wavey/auctionscan/backend/data/auctionscan.sqlite3`. Use the established Vercel project and Git integration. Do not create or relink a project or introduce another deployment mechanism.

1. Finish checks and rehearsal. Record old/new SHAs, old Vercel deployment identity, configuration, and indexed-network/service inventory. Confirm access to existing deployment status and rollback controls.
2. Enter maintenance **before pushing to `master`**. Stop all `auctionscan-indexer@*.service` writers, manual writers, and the API; confirm exit. Finish any required preparation with the old application. Take the final consistent SQLite backup and fingerprints, retaining the old release/configuration. Verify the final baseline meets rehearsal readiness. API downtime is acceptable; no maintenance UI is needed.
3. Push the tested final revision to `origin master`. On `electro`, fetch, check cleanliness, pull with `--ff-only`, and verify the exact release SHA. Sync locked dependencies with the pinned uv version.
4. Apply the migration once using the existing writer entry point. Verify integrity, foreign keys, schema, retained-row fingerprints, and checkpoints. Run observation checks per indexed network sequentially. Keep writers and API stopped until verification and the Vercel production deployment for the exact SHA succeed.
5. Start the new API and verify its contract/docs and representative responses; restart previously active indexers. Check health, finality/discovery state, and incremental advancement. Verify the matching UI from a fresh browser load, including source selection and navigation. Check both public hosts and the frontend's Vercel response header. Let old API cache entries expire and verify a reload obtains current assets; already-open tabs require a reload.
6. Verify backup capture and a new post-cutover backup. Retain the pre-cutover rollback set under existing policy.

For Ethereum, the maintenance commands after dependency synchronization are:

```sh
cd /home/wavey/auctionscan
uv --project backend run python -c 'from backend.indexer.migrations import apply_pending_migrations; apply_pending_migrations("/home/wavey/auctionscan/backend/data/auctionscan.sqlite3")'
uv --project backend run python -m backend.indexer.app --network ethereum --db /home/wavey/auctionscan/backend/data/auctionscan.sqlite3 --check-observations
```

Repeat the observation check for other indexed networks. A disabled network with retained data needs an explicit maintenance configuration using verified historical settings. Apply the shared schema migration only once; resume incremental indexing without rebuilding projections.

**9. Failure and rollback**

Before writers resume, a failed migration, frontend build, or verification leaves the application in maintenance. Preserve the failed database and logs.

Rollback restores the complete old release: stop all writers/API, restore the verified pre-cutover SQLite backup using a clean database destination with no mismatched WAL/SHM sidecars, restore the saved old backend revision/dependencies/configuration, and restore the previous production Vercel deployment through its existing controls. Verify both applications against the restored database before restarting services. Merely reverting code does not undo dropped columns.

If rollback is considered after indexing resumes, preserve the new database and all newly captured pricing facts first. Rewinding to the old backup can refetch chain history but cannot recreate historical live pricing captures. Make that data-recovery decision explicitly; do not automatically overwrite the new database or replay old migrations backward.

No reverse migration, dual schema, or runtime fallback is required. The verified backup and old release are the rollback mechanism.

**10. Completion criteria**

- All enumerated dead functions, runtime fields, obsolete response fields, and the obsolete auction-round route are removed.
- The listed projection columns/table are absent on both fresh and upgraded databases, with no remaining writers or readers outside historical migration code.
- Current bootstrap creates the final schema and does not synthesize facts from projections.
- Normal application code no longer adopts pre-finality databases, mutates old null-provenance snapshots, or reconstructs legacy raw provider presentation.
- Native events, raw logs, snapshots, pricing audit facts, observations, aliases, and checkpoints survive the cutover with the expected fingerprints.
- Historical contract behavior, both offline replay modes, payment semantics, finality/reorg recovery, and active UI navigation still pass their checks.
- Pricing response consolidation and single-network wrapper refactoring are absent from the diff.
- Runtime code and maintenance paths are materially smaller. No replacement subsystem or speculative feature has appeared; deleted UI content was empty or redundant.
- The migrated database serves correct responses and resumes incremental indexing without reproject. Both offline replay modes are verified separately on backup copies.
- One final UI/API/indexer revision is deployed, indexing has resumed, and both pre- and post-cutover backups are verified.
