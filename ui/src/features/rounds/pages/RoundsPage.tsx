import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import { api } from "../../../shared/api/client";
import { useChainsQuery } from "../../../shared/lib/chains";
import {
  cn,
  coerceFiniteNumber,
  formatAmount,
  formatCompactUsd,
  formatCount,
  formatDateTime,
  renderKickedValue,
  signedMetricTone,
  toggleKickedDisplayMode,
} from "../../../shared/lib/format";
import type { KickedDisplayMode } from "../../../shared/lib/format";
import { useRoundRows } from "../../../shared/lib/openRound";
import { roundPnlCoverageTitle } from "../../../shared/lib/pricingSource";
import { occurrenceKey } from "../../../shared/lib/routes";
import { LIVE_REFETCH_INTERVAL_MS } from "../../../shared/lib/polling";
import type { RoundListItem, RoundStatusCounts } from "../../../shared/types/api";
import AuctionAddressValue from "../../../shared/ui/AuctionAddressValue";
import ChainIcon from "../../../shared/ui/ChainIcon";
import EmptyState from "../../../shared/ui/EmptyState";
import OpenMark from "../../../shared/ui/OpenMark";
import Pagination from "../../../shared/ui/Pagination";
import PnlValue from "../../../shared/ui/PnlValue";
import RequestError from "../../../shared/ui/RequestError";
import { RoundLotCell } from "../../../shared/ui/RoundCells";
import RoundProgressMini, { toggleProgressDisplayMode, type RoundProgressMiniMode } from "../../../shared/ui/RoundProgressMini";
import SkeletonRows from "../../../shared/ui/SkeletonRows";
import StatusBadge, { statusLabel } from "../../../shared/ui/StatusBadge";
import { TableHoverScope } from "../../../shared/ui/TableHoverContext";
import TokenAmountValue from "../../../shared/ui/TokenAmountValue";
import { ChipGroup, FilterField, ViewTabs } from "../../../shared/ui/Toolbar";

const PAGE_SIZE = 20;
const TOTALS_WINDOW = "30d";
const ROUND_STATUS_FILTERS = ["all", "live", "sold_out", "expired", "settled"] as const;
type RoundStatusFilter = (typeof ROUND_STATUS_FILTERS)[number];

const STATUS_TAB_LABELS: Record<RoundStatusFilter, string> = {
  all: "All rounds",
  live: "Live",
  sold_out: "Sold",
  expired: "Expired",
  settled: "Settled",
};

function parseRoundStatus(value: string | null): RoundStatusFilter {
  return (ROUND_STATUS_FILTERS as readonly string[]).includes(value ?? "")
    ? (value as RoundStatusFilter)
    : "all";
}

type Filters = {
  status: RoundStatusFilter;
  chainId?: number;
  query: string;
  page: number;
};

function readFilters(searchParams: URLSearchParams): Filters {
  const page = Number(searchParams.get("page") || "1");
  const chainId = searchParams.get("chain") ? Number(searchParams.get("chain")) : undefined;
  return {
    status: parseRoundStatus(searchParams.get("status")),
    chainId: Number.isFinite(chainId) ? chainId : undefined,
    query: searchParams.get("filter") || searchParams.get("pair") || "",
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

function toSearchParams(filters: Filters) {
  const next = new URLSearchParams();
  if (filters.status !== "all") next.set("status", filters.status);
  if (filters.chainId) next.set("chain", String(filters.chainId));
  if (filters.query) next.set("filter", filters.query);
  if (filters.page > 1) next.set("page", String(filters.page));
  return next;
}

/**
 * How the auctions have done lately, as one quiet line beside the tabs. It has
 * a fixed window and no control, so it cannot be mistaken for a table filter,
 * and it simply stays away while it is loading or unavailable.
 */
function RoundsTotals({ chainId }: { chainId?: number }) {
  const statsQuery = useQuery({
    queryKey: ["stats", chainId, TOTALS_WINDOW],
    refetchInterval: LIVE_REFETCH_INTERVAL_MS * 5,
    queryFn: ({ signal }) => api.getStats({ chain_id: chainId, time_window: TOTALS_WINDOW }, signal),
  });
  const stats = statsQuery.data;
  if (!stats) return null;

  const pnl = coerceFiniteNumber(stats.auction_profit_usd);
  const partialPnl = stats.takes > 0 && stats.auction_profit_usd_take_count < stats.takes;
  return (
    <p className="totals-line" aria-label="Totals for the last 30 days">
      <span>{TOTALS_WINDOW}</span>
      <span title={`USD value received across ${formatCount(stats.received_usd_take_count)} of ${formatCount(stats.takes)} takes`}>
        received <b>{formatCompactUsd(stats.received_usd)}</b>
      </span>
      <span title={`Proceeds against market quotes, from ${formatCount(stats.auction_profit_usd_take_count)} of ${formatCount(stats.takes)} takes with USD pricing`}>
        PnL <b className={signedMetricTone(pnl)}>{formatCompactUsd(stats.auction_profit_usd, { signed: true })}</b>
        {partialPnl ? <span className="stat-note">partial</span> : null}
      </span>
    </p>
  );
}

function lotSummary(round: RoundListItem): string {
  const amount = round.initial_available ?? round.sold_amount;
  return [formatAmount(amount), round.from_token_symbol].filter(Boolean).join(" ");
}

function RoundRow({
  round,
  rowProps,
  progressMode,
  kickedMode,
}: {
  round: RoundListItem;
  rowProps: ReturnType<ReturnType<typeof useRoundRows<RoundListItem>>["rowProps"]>;
  progressMode: RoundProgressMiniMode;
  kickedMode: KickedDisplayMode;
}) {
  const kicked = renderKickedValue(round.kicked_at, kickedMode);
  return (
    <tr {...rowProps}>
      <td className="max-w-[15rem]">
        <span className="flex min-w-0 items-center gap-2.5">
          <ChainIcon chainId={round.chain_id} />
          <AuctionAddressValue address={round.auction_address} chainId={round.chain_id} />
        </span>
        <div className="sub-line pl-[26px]">
          R{round.round_id}
          <span className="sub-lo">{` · ${statusLabel(round.status)} · ${lotSummary(round)}`}</span>
          {` · ${renderKickedValue(round.kicked_at, "relative")}`}
        </div>
      </td>
      <td className="col-md mono fit pr-3 text-secondary">R{round.round_id}</td>
      <td className="col-lo fit pr-4"><StatusBadge status={round.status} /></td>
      <td className="col-md fit pr-4">
        <RoundProgressMini
          status={round.status}
          kickedAt={round.kicked_at}
          scheduledEndAt={round.scheduled_end_at}
          endAt={round.end_at}
          availableAmount={round.available_amount}
          initialAvailable={round.initial_available}
          soldAmount={round.sold_amount}
          fromTokenSymbol={round.from_token_symbol}
          takeCount={round.take_count}
          mode={progressMode}
        />
      </td>
      <td className="col-lo"><div className="cell-clip"><RoundLotCell round={round} /></div></td>
      <td className="col-lo">
        <div className="cell-clip">
        <TokenAmountValue
          amount={round.paid_amount}
          coverage={{ count: round.paid_take_count, total: round.take_count }}
          address={round.want_token}
          symbol={round.want_token_symbol}
          logoUrl={round.want_token_logo_url}
          chainId={round.chain_id}
        />
        </div>
      </td>
      <td className="num">
        <PnlValue
          percent={round.total_auction_profit_bps}
          usd={round.total_auction_profit_usd}
          align="right"
          title={roundPnlCoverageTitle(round)}
        />
      </td>
      <td className="col-md num dim fit pl-4" title={formatDateTime(round.kicked_at)}>{kicked}</td>
      <OpenMark />
    </tr>
  );
}

export default function RoundsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [kickedDisplayMode, setKickedDisplayMode] = useState<KickedDisplayMode>("relative");
  const [progressDisplayMode, setProgressDisplayMode] = useState<RoundProgressMiniMode>("time");
  const filters = useMemo(() => readFilters(searchParams), [searchParams]);

  const chainsQuery = useChainsQuery();
  const chainsData = chainsQuery.data;

  const normalizedQuery = filters.query.trim();
  const isAuctionAddressQuery = /^0x[a-fA-F0-9]{40}$/.test(normalizedQuery);
  const isTxHashQuery = /^0x[a-fA-F0-9]{64}$/.test(normalizedQuery);

  const roundsQuery = useQuery({
    queryKey: ["rounds", filters],
    // Keep tab counts, rows and pagination in place while a new filter loads.
    placeholderData: keepPreviousData,
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
    queryFn: ({ signal }) =>
      api.getRounds({
        status: filters.status,
        chain_id: filters.chainId,
        auction_address: isAuctionAddressQuery ? normalizedQuery : undefined,
        tx_hash: isTxHashQuery ? normalizedQuery : undefined,
        pair: normalizedQuery && !isAuctionAddressQuery && !isTxHashQuery ? normalizedQuery : undefined,
        page: filters.page,
        limit: PAGE_SIZE,
      }, signal),
  });

  const rounds = roundsQuery.data?.rounds;
  const { rowProps } = useRoundRows(rounds);

  const updateFilters = (patch: Partial<Filters>) => {
    setSearchParams(toSearchParams({ ...filters, ...patch }));
  };

  const counts: RoundStatusCounts | undefined = roundsQuery.data?.status_counts;
  const chainOptions = Object.values(chainsData?.chains || {}).map((chain) => ({
    value: chain.chain_id,
    label: <ChainIcon chainId={chain.chain_id} size="sm" />,
    title: chain.short_name || chain.name,
    icon: true,
  }));

  return (
    <div className="space-y-4">
      <div className="toolbar">
        <div className="tabs-row">
          <ViewTabs
            label="Round status"
            value={filters.status}
            onChange={(status) => updateFilters({ status, page: 1 })}
            options={ROUND_STATUS_FILTERS.map((status) => ({
              value: status,
              label: STATUS_TAB_LABELS[status],
              count: counts ? counts[status] : null,
            }))}
          />
          <RoundsTotals chainId={filters.chainId} />
          {roundsQuery.isPlaceholderData ? <span role="status" aria-label="Updating rounds" className="sr-only" /> : null}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="filter-line">
            <ChipGroup
              label="Chain"
              resetLabel="All chains"
              single
              options={chainOptions}
              selected={filters.chainId ? [filters.chainId] : []}
              onChange={(next) => updateFilters({ chainId: next[0], page: 1 })}
            />
          </div>
          <FilterField
            label="Filter rounds"
            value={filters.query}
            onChange={(value) => updateFilters({ query: value.trimStart(), page: 1 })}
            placeholder="Token, auction or tx hash"
          />
        </div>
        {chainsQuery.isError && <RequestError message={chainsData ? "Could not refresh network filters. Showing previously loaded data." : "Unable to load network filters."} onRetry={() => { void chainsQuery.refetch(); }} />}
      </div>

      <section className="card card-clip" aria-label="Rounds">
        {roundsQuery.isError && <RequestError message={roundsQuery.data ? "Could not refresh rounds. Showing previously loaded data." : "Unable to load rounds."} onRetry={() => { void roundsQuery.refetch(); }} />}
        {roundsQuery.isError && !roundsQuery.data ? null : (
          <div className="table-wrap">
            <TableHoverScope>
              <table className="data-table" aria-busy={roundsQuery.isLoading || roundsQuery.isPlaceholderData}>
                <thead>
                  <tr>
                    <th>Auction</th>
                    <th className="col-md">Round</th>
                    <th className="col-lo">Status</th>
                    <th className="col-md">
                      <button
                        type="button"
                        className="header-toggle"
                        title={`Show ${progressDisplayMode === "time" ? "share of the lot sold" : "time elapsed"}`}
                        onClick={() => setProgressDisplayMode((current) => toggleProgressDisplayMode(current))}
                      >
                        Progress <em>{progressDisplayMode === "time" ? "time" : "sold"}</em>
                      </button>
                    </th>
                    <th className="col-lo">Lot</th>
                    <th className="col-lo">Received</th>
                    <th className="num">PnL</th>
                    <th className="col-md num">
                      <button
                        type="button"
                        className="header-toggle"
                        title={kickedDisplayMode === "relative" ? "Show kick times" : "Show time since kick"}
                        onClick={() => setKickedDisplayMode(toggleKickedDisplayMode)}
                      >
                        Kicked
                      </button>
                    </th>
                    <th className="open-cell"><span className="sr-only">Open</span></th>
                  </tr>
                </thead>
                <tbody className={cn(roundsQuery.isPlaceholderData && "is-stale")}>
                  {roundsQuery.isLoading ? (
                    <SkeletonRows
                      rows={12}
                      widths={[150, 28, 52, 104, 120, 120, 64, 44, null]}
                      classNames={[undefined, "col-md", "col-lo", "col-md", "col-lo", "col-lo", "num", "col-md num", "open-cell"]}
                    />
                  ) : rounds?.length ? (
                    rounds.map((round) => (
                      <RoundRow
                        key={`${round.chain_id}:${occurrenceKey(round.occurrence)}`}
                        round={round}
                        rowProps={rowProps(round)}
                        progressMode={progressDisplayMode}
                        kickedMode={kickedDisplayMode}
                      />
                    ))
                  ) : (
                    <tr>
                      <td colSpan={9}>
                        <EmptyState title="No rounds found" description="Try another status tab, or widen the chain or token filters." />
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </TableHoverScope>
          </div>
        )}
      </section>
      {roundsQuery.data ? (
        <Pagination
          page={roundsQuery.data.page}
          hasNext={roundsQuery.data.has_next}
          disabled={roundsQuery.isPlaceholderData}
          onPageChange={(page) => updateFilters({ page })}
          summary={`${formatCount(roundsQuery.data.total)} matching rounds`}
        />
      ) : null}
    </div>
  );
}
