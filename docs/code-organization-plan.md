# Auctionscan: focused code organization

Prepared September 17, 2026 against `61f7d01`. Status: planned; application code is unchanged.

## Objective

Make frequently edited code easier to locate and understand through three bounded changes:

1. Separate the round modal's data coordination from its larger views.
2. Give the auction page's two substantial lists their own components.
3. Move the self-contained taker SQL into one dedicated module.

Preserve behavior, visual layout, public API, SQL results, and deployment requirements. Use ordinary functions, React components, and one feature-specific hook. The work adds six source files; it does not introduce a new application layer or a general component/query framework.

This plan follows the completed [backend architecture cleanup](architecture-improvement-plan.md). It does not reopen that implementation.

## Boundaries

- Keep facts, projections, decoding, and writer transactions as they are.
- Keep React Query as the owner of remote data and the URL as the owner of navigation/selection state.
- Keep generated API types and existing shared UI primitives. New components stay inside their owning feature.
- Preserve query keys, enabled conditions, cancellation signals, polling, retry behavior, and cache settings exactly.
- Move existing markup and styles intact, including mobile/desktop variants, loading states, table hover boundaries, focus attributes, and accessibility labels.
- Update imports directly. Do not leave compatibility exports, barrel files, or wrappers around moved functions.
- Do not add dependencies, schema migrations, configuration, or deployment tooling.
- Do not use line-count targets as acceptance criteria. Each extraction must give a coherent responsibility a clear owner.

Known UI error/empty-state confusion is a separate behavior fix. In particular, the current round modal can display an empty take list after a request fails. Record that follow-up without changing it during these moves or adding tests that endorse the misleading message.

## 1. Organize the round modal

**Current problem.** `ui/src/features/rounds/components/RoundModalContent.tsx` contains 917 lines. It combines five requests, indexed-snapshot price coordination, route effects, selection state, loading views, settings, and take rendering. These are concrete responsibilities with different reasons to change.

### Move the two substantial views

| New file, relative to `ui/src/features/rounds/` | Move from `RoundModalContent.tsx` |
| --- | --- |
| `components/RoundSettingsPanel.tsx` | `RoundSettingsPanel`, `livePriceErrorMessage`, `PriceStatusMarker`, `PriceValue`, and `LiveLabelMarker`. |
| `components/RoundTakesTable.tsx` | `TakeTable`, renamed to `RoundTakesTable`, including both responsive variants and selected-take expansion. |

Keep their current prop contracts for the mechanical move. Keep small private helpers in the same file as their consumer. Reuse `TakeExpandedContent`, `TakeExpandedRow`, token/address components, and formatting helpers as today.

The table receives takes, pricing source, selected occurrence, selected detail/loading state, and a selection callback. It does not fetch data, read the URL, or own selection. Preserve its current desktop `TableHoverScope`; do not move the provider around the entire modal.

Keep `HeaderMetric`, `ModalCloseButton`, `formatDisplayVersion`, and the current loading components in `RoundModalContent.tsx`. Their consumers remain there, and they do not justify more files.

### Move data coordination into one hook

Add `ui/src/features/rounds/useRoundDetails.ts` exporting `useRoundDetails`.

Inputs are the already parsed chain ID, optional auction address, round occurrence, and optional selected-take occurrence. Reuse `SourceOccurrence` from the generated API type aliases. The hook does not call router hooks.

Move these existing operations together:

- The round, auction, takes, selected-take, and live-price `useQuery` calls.
- The `mismatchRetryAfter` ref and the existing throttled HTTP 409 refresh behavior.
- The checks that the returned round belongs to the route's auction and the selected take belongs to the displayed round.
- The indexed-block reference and validation that a live price matches both the occurrence and the displayed indexed snapshot.

Return the five query results and the existing derived values (`round`, `selectedTake`, `priceReference`, and `displayedLivePrice`). Keep the return type inferred; do not build another query-result abstraction or copy query data into React state.

`RoundModalContent.tsx` continues to own:

- Route and search-parameter parsing, preserving `location.state` when changing modal search parameters.
- Redirecting to the corrected round when the selected take's inferred round changes. This effect must still inspect the successful selected-take query result before the same-round display filter; otherwise the redirect can silently stop working.
- The `take` and `priceSource` URL updates, source normalization, Escape behavior, and display preferences.
- Loading/empty-state decisions, the header, and composition of the extracted views.

Keep the hook unconditional and mounted at the same level as the existing queries. Do not reset the mismatch-throttle ref or change any query's activation condition during the move. Keep the modal shell and focus management in `RoundModal.tsx` untouched.

**Verification.** Keep the existing component-level tests in `RoundModalContent.test.tsx`; they must still prove throttled snapshot-mismatch recovery and rejection of late prices from older snapshots. Add one focused integration case there for a selected take moving to another round: the route updates with replace semantics, and the search parameters and modal background state survive. Test the mounted component through the API boundary rather than mocking the new hook.

**Stopping point.** The settings/table files contain rendering, the hook owns the five requests and snapshot coordination, and the modal owns navigation and composition. There is no second state store and no new generic hook.

## 2. Organize the auction page's lists

**Current problem.** `ui/src/features/auctions/pages/AuctionPage.tsx` contains 813 lines. Much of it is substantial list rendering embedded alongside page queries and URL handling.

Add two files under `ui/src/features/auctions/components/`:

| File | Responsibility |
| --- | --- |
| `AuctionTakesTable.tsx` | Move `RecentTakesList`, renaming it to `AuctionTakesTable`; preserve its mobile/desktop views and selected-take expansion. |
| `AuctionRoundsTable.tsx` | Move `RecentRoundsMobileList` and the adjacent desktop rounds table into one responsive component. Keep the mobile helper private in this file. |

For `AuctionTakesTable`, retain the existing props and selection callback. Its surrounding `TableHoverScope` stays in the page, in the same place relative to loading and empty states.

For `AuctionRoundsTable`, pass:

- The rounds array using the existing API type.
- Kicked-time and progress display modes, with their existing toggle callbacks.
- `onOpenRound(round)` for mobile navigation.
- `onRoundClick(event, round)` for desktop navigation; forward both `onClick` and `onAuxClick` unchanged.

The page's desktop callback continues to call `handleRowNavigation` with the existing round URL and background-location state. Preserve modifier-click, middle-click, and nested link/button behavior. The table retains its existing desktop `TableHoverScope`; rounds and takes must not share a hover provider.

Keep all queries, URL selection, source normalization, Escape handling, page-size constants, pagination, panel headers, loading/empty decisions, and navigation callbacks in `AuctionPage.tsx`. Keep `InfoItem`, `SellTokensPreview`, and `formatVolume` local. Do not add an auction data hook in this pass: the immediate problem is the embedded list markup.

Do not merge the round and auction take tables into a configurable shared table. Their context, columns, hover scopes, and selection presentation differ. Their existing shared leaf components already remove the useful duplication.

**Verification.** Add a small `AuctionPage.test.tsx` integration suite using the existing Vitest/Testing Library setup. Cover the wiring at risk: pagination retains existing query parameters, take selection can be toggled/cleared, and desktop round navigation retains its background location while modifier/middle clicks open the correct URL. Include an inline link or display-toggle interaction that does not trigger row navigation. Mock API methods and `window.open`, not the extracted components.

Use a manual desktop and mobile comparison for layout, selection expansion, hover scope, and display toggles. Do not introduce screenshot infrastructure or tests for static markup.

**Stopping point.** The page clearly shows its queries, navigation, summary, and panel composition. The two components own their complete list views. No design changes or general table API are needed.

## 3. Isolate the taker query family

**Current problem.** `backend/src/backend/api/queries.py` contains 1,472 lines spanning several read surfaces. Its taker functions form a self-contained group with no dependency on the module's other private SQL builders.

Add `backend/src/backend/api/taker_queries.py`. Move these six functions without changing their bodies or signatures:

```text
_taker_ctes
_ranked_taker_cte
_taker_item_from_row
list_takers
get_taker_detail
list_taker_takes
```

The new module needs the existing `sqlite3`, `Any`, and address-normalization imports. It must not import the general `queries` module, route handlers, or serializers.

Update `api/routes/takers.py` to import the three public taker functions from `taker_queries`. Keep `load_as_of`, `occurrence_from_row`, and `list_take_pricing_sources_for_keys` imported from `queries`; they serve other routes too.

Update `backend/tests/test_pricing.py` to import and monkeypatch the new owner in `test_taker_sql_materializes_only_the_requested_page`. Currently that test patches `api_queries._taker_item_from_row` and calls `api_queries.list_takers`. Keep its assertion that a 15-row page materializes only 15 rows.

Leave the remaining query module intact. Do not create a query package, repository classes, a shared SQL-builder module, or one file per endpoint. Do not change SQL ordering, rank calculation, filtering, normalization, aggregation precision, null handling, or pagination.

**Verification.** Run `test_api.py` and `test_pricing.py`. Existing cases cover cross-chain aggregation, USD volume ordering, filtering/ranking, pagination, detail consistency, and bounded result materialization. Check the generated OpenAPI contract remains unchanged. New SQL tests are unnecessary for an exact move.

**Stopping point.** All taker query implementation lives in one file, consumers import it directly, and the old module has no taker compatibility exports or circular imports.

## Delivery and checks

Use four targeted implementation commits, keeping the data hook separate from view moves:

| Order | Commit scope | Check before committing |
| --- | --- | --- |
| 1 | Move the round settings and take views. | Existing UI tests and TypeScript check; inspect unchanged markup. |
| 2 | Extract round data coordination and add the corrected-round navigation case. | UI tests and TypeScript check, especially snapshot and navigation behavior. |
| 3 | Extract auction lists and add focused page wiring tests. | UI tests, TypeScript check, and responsive interaction comparison. |
| 4 | Move taker queries and update direct consumers/tests. | Backend API/pricing tests and generated API contract check. |

Commands from the repository root:

```sh
npm --prefix ui test
npm --prefix ui run typecheck
uv --project backend run pytest backend/tests/test_api.py backend/tests/test_pricing.py -q
npm --prefix ui run check:api
```

After all changes, run the full backend suite once, the full UI tests, the API contract check, and the UI production build. Reuse successful checks from the final unchanged revision; do not repeatedly rerun every suite after documentation-only edits.

```sh
uv --project backend run pytest -q
npm --prefix ui test
npm --prefix ui run check:api
npm --prefix ui run build
git diff --check
```

For browser comparison, use the same representative auction and round before/after, with both desktop and mobile widths. Check normal/modified row navigation, selected-take expansion, Escape behavior, pagination, pricing-source selection, table-local hover, and modal focus/scroll restoration. Loading, empty, and request-failure behavior should remain unchanged in this refactor.

Inspect the final diff for changed query keys, polling options, SQL text, generated types, styles, and URL semantics; these should have no intentional changes. Remove unused imports left by moves, without unrelated formatting churn.

There is no database migration or reproject requirement. When implementation is complete, use the normal checked deployment procedure with the repository-pinned `uv` version and locked dependencies.

## Explicit stopping point and follow-ups

Complete this plan when the six modules have clear ownership, direct consumers use them, behavior checks pass, and the code is easier to navigate. Preserve the existing feature/shared folder layout.

Leave the following for separate work:

- UI request failures versus genuine empty results: a small correctness change with its own tests.
- Further runtime/projection splitting: the previous cleanup established the boundaries; the sync method intentionally retains orchestration and transaction sequencing.
- Splitting the remaining API queries: do so only when another cohesive group becomes a demonstrated maintenance problem.
- Deployment automation, broad typing/lint adoption, dependency upgrades, polling changes, performance optimization, and visual redesign.

The result should be easier to understand through clear ownership, with no new framework and no change to how Auctionscan behaves.
