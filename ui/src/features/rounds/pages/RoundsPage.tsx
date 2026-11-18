import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import { api } from "../../../shared/api/client";
import { useChainsQuery } from "../../../shared/lib/chains";
import {
  formatAmount,
  formatCompactUsd,
  formatCount,
  formatDateTime,
  renderKickedValue,
  toggleKickedDisplayMode,
} from "../../../shared/lib/format";
import type { KickedDisplayMode } from "../../../shared/lib/format";
import { useRoundRows } from "../../../shared/lib/openRound";
import { roundPnlCoverageTitle } from "../../../shared/lib/pricingSource";
import { occurrenceKey } from "../../../shared/lib/routes";
import { LIVE_REFETCH_INTERVAL_MS } from "../../../shared/lib/polling";
import type { RoundListItem, RoundStatusCounts, StatsResponse } from "../../../shared/types/api";
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
import StatStrip, { Stat } from "../../../shared/ui/StatStrip";
import StatusBadge, { statusLabel } from "../../../shared/ui/StatusBadge";
import { TableHoverScope } from "../../../shared/ui/TableHoverContext";
import TokenAmountValue from "../../../shared/ui/TokenAmountValue";
import { ChipGroup, FilterField, Segmented, ViewTabs } from "../../../shared/ui/Toolbar";

const PAGE_SIZE = 20;
const ROUND_STATUS_FILTERS = ["all", "live", "sold_out", "expired", "settled"] as const;
type RoundStatusFilter = (typeof ROUND_STATUS_FILTERS)[number];
const STATS_WINDOWS = ["24h", "7d", "30d", "all"] as const;
type StatsWindow = (typeof STATS_WINDOWS)[number];

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

function parseStatsWindow(value: string | null): StatsWindow {
  return (STATS_WINDOWS as readonly string[]).includes(value ?? "") ? (value as StatsWindow) : "30d";
}

type Filters = {
  status: RoundStatusFilter;
  chainId?: number;
  versions: string[];
  query: string;
  page: number;
  window: StatsWindow;
};

function normalizeVersionFilter(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  return (trimmed.toLowerCase().startsWith("v") ? trimmed.slice(1) : trimmed).toLowerCase();
}

function readVersionFilters(searchParams: URLSearchParams): string[] {
  const seen = new Set<string>();
  const versions: string[] = [];
  searchParams.getAll("version").forEach((value) => {
    value.split(",").forEach((part) => {
      const version = normalizeVersionFilter(part);
      if (version && !seen.has(version)) {
        seen.add(version);
        versions.push(version);
      }
    });
  });
  return versions;
}

function readFilters(searchParams: URLSearchParams): Filters {
  const page = Number(searchParams.get("page") || "1");
  const chainId = searchParams.get("chain") ? Number(searchParams.get("chain")) : undefined;
  return {
    status: parseRoundStatus(searchParams.get("status")),
    chainId: Number.isFinite(chainId) ? chainId : undefined,
    versions: readVersionFilters(searchParams),
    query: searchParams.get("filter") || searchParams.get("pair") || "",
    page: Number.isFinite(page) && page > 0 ? page : 1,
    window: parseStatsWindow(searchParams.get("window")),
  };
}

function toSearchParams(filters: Filters) {
  const next = new URLSearchParams();
  if (filters.status !== "all") next.set("status", filters.status);
  if (filters.chainId) next.set("chain", String(filters.chainId));
  filters.versions.forEach((version) => next.append("version", version));
  if (filters.query) next.set("filter", filters.query);
  if (filters.page > 1) next.set("page", String(filters.page));
  if (filters.window !== "30d") next.set("window", filters.window);
  return next;
}

function displayVersion(version: string): string {
  return version.startsWith("v") ? version : `v${version}`;
}

const WINDOW_LABEL: Record<StatsWindow, string> = { "24h": "24h", "7d": "7d", "30d": "30d", all: "all time" };

function partial(count: number, total: number): string | null {
  return total > 0 && count < total ? "partial" : null;
}

function RoundsStrip({ stats, loading, window }: { stats?: StatsResponse; loading: boolean; window: StatsWindow }) {
  const scope = WINDOW_LABEL[window];
  return (
    <StatStrip label="Totals for the filters in scope" count={5}>
      <Stat
        label={`Received · ${scope}`}
        loading={loading}
        value={stats ? formatCompactUsd(stats.received_usd) : "—"}
        note={stats ? partial(stats.received_usd_take_count, stats.takes) : null}
        title={stats ? `USD value received across ${formatCount(stats.received_usd_take_count)} of ${formatCount(stats.takes)} takes` : undefined}
      />
      <Stat
        label={`Auction PnL · ${scope}`}
        loading={loading}
        value={stats ? formatCompactUsd(stats.auction_profit_usd, { signed: true }) : "—"}
        note={stats ? partial(stats.auction_profit_usd_take_count, stats.takes) : null}
        title={stats ? `Proceeds against market quotes, from ${formatCount(stats.auction_profit_usd_take_count)} of ${formatCount(stats.takes)} takes with USD pricing` : undefined}
      />
      <Stat label={`Rounds · ${scope}`} loading={loading} value={stats ? formatCount(stats.rounds) : "—"} />
      <Stat label={`Takes · ${scope}`} loading={loading} value={stats ? formatCount(stats.takes) : "—"} />
      <Stat label={`Takers · ${scope}`} loading={loading} value={stats ? formatCount(stats.takers) : "—"} />
    </StatStrip>
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
        <div className="sub-line pl-[26px]">{`R${round.round_id} · ${statusLabel(round.status)} · ${lotSummary(round)}`}</div>
      </td>
      <td className="col-lo mono fit pr-3 text-secondary">R{round.round_id}</td>
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
      <td className="col-lo max-w-[14rem]"><RoundLotCell round={round} /></td>
      <td className="col-md max-w-[14rem]">
        <TokenAmountValue
          amount={round.paid_amount}
          coverage={{ count: round.paid_take_count, total: round.take_count }}
          address={round.want_token}
          symbol={round.want_token_symbol}
          logoUrl={round.want_token_logo_url}
          chainId={round.chain_id}
        />
      </td>
      <td className="num">
        <PnlValue
          percent={round.total_auction_profit_bps}
          usd={round.total_auction_profit_usd}
          align="right"
          title={roundPnlCoverageTitle(round)}
        />
      </td>
      <td className="col-lo num dim fit pl-4" title={formatDateTime(round.kicked_at)}>{kicked}</td>
      <OpenMark />
    </tr>
  );
}

export default function RoundsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [kickedDisplayMode, setKickedDisplayMode] = useState<KickedDisplayMode>("relative");
  const [progressDisplayMode, setProgressDisplayMode] = useState<RoundProgressMiniMode>("time");
  const filters = useMemo(() => readFilters(searchParams), [searchParams]);
  const firstPaint = useRef(true);

  const chainsQuery = useChainsQuery();
  const chainsData = chainsQuery.data;
  const versionsQuery = useQuery({
    queryKey: ["auction-versions", filters.chainId],
    queryFn: ({ signal }) => api.getAuctionVersions(filters.chainId, signal),
  });

  const normalizedQuery = filters.query.trim();
  const isAuctionAddressQuery = /^0x[a-fA-F0-9]{40}$/.test(normalizedQuery);
  const isTxHashQuery = /^0x[a-fA-F0-9]{64}$/.test(normalizedQuery);

  const roundsQuery = useQuery({
    queryKey: ["rounds", { ...filters, window: undefined }],
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
    queryFn: ({ signal }) =>
      api.getRounds({
        status: filters.status,
        chain_id: filters.chainId,
        auction_address: isAuctionAddressQuery ? normalizedQuery : undefined,
        tx_hash: isTxHashQuery ? normalizedQuery : undefined,
        pair: normalizedQuery && !isAuctionAddressQuery && !isTxHashQuery ? normalizedQuery : undefined,
        version: filters.versions,
        page: filters.page,
        limit: PAGE_SIZE,
      }, signal),
  });

  const statsQuery = useQuery({
    queryKey: ["stats", filters.chainId, filters.versions, filters.window],
    refetchInterval: LIVE_REFETCH_INTERVAL_MS * 5,
    queryFn: ({ signal }) =>
      api.getStats({ chain_id: filters.chainId, version: filters.versions, time_window: filters.window }, signal),
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
  const versionOptions = (versionsQuery.data?.versions || []).map((option) => ({
    value: option.version.toLowerCase(),
    label: displayVersion(option.version),
    title: `${option.auction_count.toLocaleString()} auctions · ${option.round_count.toLocaleString()} rounds`,
    mono: true,
  }));

  const isIntro = firstPaint.current && Boolean(rounds?.length);
  if (rounds?.length) firstPaint.current = false;

  return (
    <div className="space-y-4">
      <RoundsStrip stats={statsQuery.data} loading={statsQuery.isLoading} window={filters.window} />
      {statsQuery.isError && !statsQuery.data ? (
        <RequestError message="Unable to load totals." onRetry={() => { void statsQuery.refetch(); }} />
      ) : null}

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
          <div className="mb-0.5 hidden md:block">
            <Segmented
              label="Totals window"
              value={filters.window}
              onChange={(window) => updateFilters({ window })}
              options={STATS_WINDOWS.map((value) => ({ value, label: value === "all" ? "All" : value }))}
            />
          </div>
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
            {versionOptions.length > 1 ? (
              <ChipGroup
                label="Version"
                resetLabel="All versions"
                options={versionOptions}
                selected={filters.versions}
                onChange={(versions) => updateFilters({ versions, page: 1 })}
              />
            ) : null}
          </div>
          <FilterField
            label="Filter rounds"
            value={filters.query}
            onChange={(value) => updateFilters({ query: value.trimStart(), page: 1 })}
            placeholder="Token, auction or tx hash"
          />
        </div>
        {chainsQuery.isError && <RequestError message={chainsData ? "Could not refresh network filters. Showing previously loaded data." : "Unable to load network filters."} onRetry={() => { void chainsQuery.refetch(); }} />}
        {versionsQuery.isError && <RequestError message={versionsQuery.data ? "Could not refresh version filters. Showing previously loaded data." : "Unable to load version filters."} onRetry={() => { void versionsQuery.refetch(); }} />}
      </div>

      <section className="card card-clip" aria-label="Rounds">
        {roundsQuery.isError && <RequestError message={roundsQuery.data ? "Could not refresh rounds. Showing previously loaded data." : "Unable to load rounds."} onRetry={() => { void roundsQuery.refetch(); }} />}
        {roundsQuery.isError && !roundsQuery.data ? null : (
          <div className="table-wrap">
            <TableHoverScope>
              <table className={isIntro ? "data-table intro" : "data-table"} aria-busy={roundsQuery.isLoading}>
                <thead>
                  <tr>
                    <th>Auction</th>
                    <th className="col-lo">Round</th>
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
                    <th className="col-md">Received</th>
                    <th className="num">PnL</th>
                    <th className="col-lo num">
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
                <tbody>
                  {roundsQuery.isLoading ? (
                    <SkeletonRows
                      rows={12}
                      widths={[150, 28, 52, 104, 120, 120, 64, 44, null]}
                      classNames={[undefined, "col-lo", "col-lo", "col-md", "col-lo", "col-md", "num", "col-lo num", "open-cell"]}
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
                        <EmptyState title="No rounds found" description="Try another status tab, or widen the chain, version or token filters." />
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
          page={filters.page}
          hasNext={roundsQuery.data.has_next}
          onPageChange={(page) => updateFilters({ page })}
          summary={`${formatCount(roundsQuery.data.total)} matching rounds`}
        />
      ) : null}
    </div>
  );
}
