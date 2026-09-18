# Focused cleanup verification

Implemented September 18, 2026 (UTC), starting from `3894252`.

## Delivered changes

- The DOM test environment retains Node's AbortController and AbortSignal so
  React Router's native Request accepts navigation signals. All existing
  navigation tests pass without replacing fetch or adding dependencies.
- Rounds, auctions, takers, profiles, search, direct round lookup, and take
  details distinguish request errors from successful empty/missing responses.
  Errors expose a local Retry action. Refresh failures retain loaded data with
  a warning; confirmed 404 or successful null responses supersede cached records.
- Supporting auction/takes requests no longer block an already-loaded round.
  Live prices remain hidden on request failure or an indexed-snapshot mismatch.
- Confirmed/live batch completion shares reconciliation and checkpoint updates.
  Full projection clearing has one implementation and does not reset round
  fields immediately before deleting the rounds. Take-only maintenance still
  resets surviving rounds. Maintenance clears its pricing work inside the
  replacement transaction; recovery retains valid work and removes orphans.

The change adds no application dependencies, database tables, migrations, or
API changes. Fact deletion remains in its existing owner. Recovery retains the
event-free shortcut and full replay for any removed domain event.

## Recovery measurement

Decision criterion: retain full replay if data-changing recovery completes
within a 10-second indexing pause on the production server. This is a bounded
cleanup criterion for the current data size, not a permanent performance SLA.

The snapshot was taken through SQLite's backup API while normal indexing
continued. It contains 5,768 takes and 4,718 kicks, with indexed head 26,001,422
and confirmed checkpoint 26,001,340. Its current live tail contains no domain
events. To exercise data-changing recovery, each independent copy uses a
simulated earlier finality watermark and removes real stored events:

| Case | Ancestor | Removed domain events |
| --- | ---: | --- |
| Latest kick/settings | 26,001,252 | One kick, minimum price, starting price, and step decay update |
| Latest take/settlement | 25,999,610 | One take, one settlement, two kicks, and three parameter updates |

Each case calls `_recover_live_tail_reorg(record_reorg=True)` inside the normal
writer transaction. Three independent copies were measured per case and code
version. Timings include transaction commit and exclude copying, startup, and
verification. Live RPC requests are prohibited by the harness. This exercises
the actual data-changing recovery path, not maintenance take re-detection.

Median seconds:

| Environment / code | Kick/settings | Take/settlement |
| --- | ---: | ---: |
| Local before cleanup | 4.461 | 4.541 |
| Local after cleanup | 4.609 | 4.447 |
| Production server before cleanup | 3.820 | 3.914 |

The slowest of the six production baseline runs took 4.113 seconds. Pricing
rebuilding was the largest individual stage at 1.68–1.75 seconds median;
reconstructing native/take events together took about 1.37 seconds, and applying
their projections about 0.59–0.63 seconds. Small local before/after variation
does not establish a speed improvement.

No recovery optimization or partial recovery strategy is warranted by these
measurements. The existing full replay comfortably meets the selected target.

Every measured run verified all surviving raw/snapshot/observation/header facts
and unchanged pricing audit facts. All 13 projection tables, surviving pricing
queue work, and normalized checkpoints match across local before/after and
production baseline runs. Projection comparisons exclude regenerated timestamps
and internal take row IDs. Checkpoint assertions include the rewound head,
confirmed boundary, and incremented reorg count.

The source snapshot, standalone measurement harness, and production baseline
output are retained on `electro` at:
`/home/wavey/auctionscan-backups/focused-cleanup-20260918/`.
The harness always works on temporary copies and leaves its input unchanged.

## Checks

- Full backend suite: 217 passed.
- Maintenance/replay suite after strengthening queue cleanup assertions:
  22 passed, including atomic failure and successful full/take-only maintenance.
- UI suite: 45 passed, covering initial failure, successful emptiness, Retry,
  failed refresh with retained data, confirmed removal after cached success,
  independent section loading/failure, selected takes, and live-price rejection.
- UI typecheck, production build, and generated API-contract check passed.
- Existing backend recovery tests cover rollback on failure, surviving queue
  work, event-free recovery, event-removing recovery, and factory rewind.

Deployment requires only the normal code update, dependency synchronization,
and service restarts. Production reprojection is not required.
