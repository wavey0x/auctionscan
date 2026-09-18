import MetricCoverage from "../../../shared/ui/MetricCoverage";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../../../shared/api/client";
import { useChainsQuery } from "../../../shared/lib/chains";
import {
  cn,
  formatAmount,
  formatDateTime,
  formatSignedUsdDelta,
  formatUnsignedPercent,
  formatUsd,
  renderKickedValue,
  signedMetricTone,
  toggleKickedDisplayMode,
} from "../../../shared/lib/format";
import type { KickedDisplayMode } from "../../../shared/lib/format";
import { handleRowNavigation } from "../../../shared/lib/rowNavigation";
import { occurrenceKey, buildRoundPathWithSource, roundModalSourceFromLocation, withBackgroundLocation } from "../../../shared/lib/routes";
import { roundProgressSummary } from "../../../shared/lib/roundProgress";
import type { RoundListItem } from "../../../shared/types/api";
import AuctionAddressValue from "../../../shared/ui/AuctionAddressValue";
import ChainIcon from "../../../shared/ui/ChainIcon";
import EmptyState from "../../../shared/ui/EmptyState";
import RequestError from "../../../shared/ui/RequestError";
import Pagination from "../../../shared/ui/Pagination";
import Panel from "../../../shared/ui/Panel";
import RoundProgressMini, { toggleProgressDisplayMode, type RoundProgressMiniMode } from "../../../shared/ui/RoundProgressMini";
import Skeleton from "../../../shared/ui/Skeleton";
import StackedListRow from "../../../shared/ui/StackedListRow";
import StatusBadge from "../../../shared/ui/StatusBadge";
import { TableHoverScope } from "../../../shared/ui/TableHoverContext";
import TokenAmountValue from "../../../shared/ui/TokenAmountValue";
import TokenValue from "../../../shared/ui/TokenValue";
import VersionMultiSelect from "../../../shared/ui/VersionMultiSelect";

const PAGE_SIZE = 15;
const ROUND_STATUS_FILTERS = new Set(["all", "live", "sold_out", "expired", "settled"]);

type Filters = {
  status: string;
  chainId?: number;
  versions: string[];
  query: string;
  page: number;
};

function formatSignedPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  const formatted = new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(Math.abs(value));
  if (value > 0) return `+${formatted}%`;
  if (value < 0) return `-${formatted}%`;
  return `${formatted}%`;
}

function coerceFiniteNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function RoundLotCell({ round }: { round: RoundListItem }) {
  const lotUsdLabel = round.kick_market_quote_usd
    ? `~${formatUsd(round.kick_market_quote_usd)}`
    : round.total_market_quote_usd
      ? `~${formatUsd(round.total_market_quote_usd)}`
      : "—";
  const lotAmount = round.initial_available ?? round.sold_amount;
  const lotAmountLabel = [formatAmount(lotAmount), round.from_token_symbol].filter(Boolean).join(" ").trim() || "—";
  const title = [
    lotUsdLabel !== "—"
      ? `Lot value: ${lotUsdLabel}`
      : "Lot value: —",
    round.kick_market_quote_usd
      ? "Source: kick-time estimate"
      : round.total_market_quote_usd
        ? "Source: take-time quote total"
        : null,
    `Lot amount: ${lotAmountLabel}`,
  ].filter(Boolean).join("\n");

  return (
    <div className="inline-flex min-w-0 max-w-full items-center gap-1.5 whitespace-nowrap" title={title}>
      <TokenValue
        address={round.from_token}
        symbol={lotAmountLabel}
        logoUrl={round.from_token_logo_url}
        chainId={round.chain_id}
        showCopy={false}
        className="min-w-0"
      />
      <div className="shrink-0 self-center font-mono text-[10px] leading-none text-tertiary">
        {lotUsdLabel}
      </div>
    </div>
  );
}

function RoundPnlInline({ round }: { round: RoundListItem }) {
  const pnlPercent = coerceFiniteNumber(round.total_auction_profit_bps);
  const pnlUsdValue = coerceFiniteNumber(round.total_auction_profit_usd);
  const directionValue = pnlPercent ?? pnlUsdValue;

  return (
    <span className="inline-flex min-w-0 items-center gap-1.5 font-mono">
      <span className={cn("truncate text-[12px] leading-none", signedMetricTone(directionValue))}>
        {formatUnsignedPercent(pnlPercent)}
      </span>
      <span className="truncate text-[10px] leading-none text-tertiary">{formatSignedUsdDelta(pnlUsdValue)}</span>
      <MetricCoverage count={round.priced_take_count ?? 0} total={round.take_count} label="quoted" />
      {round.usd_priced_take_count !== (round.priced_take_count ?? 0) ? <MetricCoverage count={round.usd_priced_take_count} total={round.take_count} label="USD" /> : null}
    </span>
  );
}

function RoundPnlCell({ round }: { round: RoundListItem }) {
  const pnlPercent = coerceFiniteNumber(round.total_auction_profit_bps);
  const pnlUsdValue = coerceFiniteNumber(round.total_auction_profit_usd);
  const directionValue = pnlPercent ?? pnlUsdValue;
  const title = [
    pnlUsdValue !== null ? `PnL: ${formatUsd(pnlUsdValue)}` : "PnL: —",
    pnlPercent !== null
      ? `PnL %: ${formatSignedPercent(pnlPercent)}`
      : "PnL %: —",
  ].join("\n");

  return (
    <div className="flex w-[4.8rem] flex-col items-start gap-[2px] font-mono leading-[0.92rem]" title={title}>
      <div className={cn("w-full truncate whitespace-nowrap text-left text-[13px] leading-none", signedMetricTone(directionValue))}>
        {formatUnsignedPercent(pnlPercent)}
      </div>
      <div className="w-full truncate whitespace-nowrap text-left font-mono text-[10px] leading-none text-tertiary">
        {formatSignedUsdDelta(pnlUsdValue)}
      </div>
      <MetricCoverage count={round.priced_take_count ?? 0} total={round.take_count} label="quoted" />
      {round.usd_priced_take_count !== (round.priced_take_count ?? 0) ? <MetricCoverage count={round.usd_priced_take_count} total={round.take_count} label="USD" /> : null}
    </div>
  );
}

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

function RoundsMobileRow({
  round,
  href,
  onOpen,
  kickedDisplayMode,
  onToggleKickedDisplayMode,
  progressDisplayMode,
  onToggleProgressDisplayMode,
}: {
  round: RoundListItem;
  href: string;
  onOpen: () => void;
  kickedDisplayMode: KickedDisplayMode;
  onToggleKickedDisplayMode: () => void;
  progressDisplayMode: RoundProgressMiniMode;
  onToggleProgressDisplayMode: () => void;
}) {
  return (
    <StackedListRow
      interactive
      className="space-y-2 md:hidden"
      onClick={(event) => handleRowNavigation(event, href, () => onOpen())}
      onAuxClick={(event) => handleRowNavigation(event, href, () => onOpen())}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2">
          <ChainIcon chainId={round.chain_id} />
          <AuctionAddressValue address={round.auction_address} chainId={round.chain_id} />
        </div>
        <div className="grid shrink-0 grid-cols-[auto_auto] items-center gap-1">
          <span className="font-mono text-primary">R{round.round_id}</span>
          <StatusBadge status={round.status} className="min-w-[3.9rem] px-1" />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-meta text-tertiary">
        <button
          type="button"
          className="font-mono underline-offset-4 transition-colors hover:text-primary hover:underline"
          title={formatDateTime(round.kicked_at)}
          onClick={(event) => {
            event.stopPropagation();
            onToggleKickedDisplayMode();
          }}
        >
          {renderKickedValue(round.kicked_at, kickedDisplayMode)}
        </button>
        <span aria-hidden="true">·</span>
        <button
          type="button"
          className="font-mono underline-offset-4 transition-colors hover:text-primary hover:underline"
          title={`Show ${progressDisplayMode === "time" ? "take" : "time"} progress`}
          onClick={(event) => {
            event.stopPropagation();
            onToggleProgressDisplayMode();
          }}
        >
          {roundProgressSummary(round, progressDisplayMode)}
        </button>
      </div>

      <div className="flex min-w-0 items-center gap-1.5">
        <span className="metric-label shrink-0">Lot</span>
        <RoundLotCell round={round} />
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="metric-label shrink-0">Recv</span>
          <TokenAmountValue
            amount={round.paid_amount}
            coverage={{ count: round.paid_take_count, total: round.take_count }}
            address={round.want_token}
            symbol={round.want_token_symbol}
            logoUrl={round.want_token_logo_url}
            chainId={round.chain_id}
            className="min-w-0 w-auto"
          />
        </div>
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="metric-label shrink-0">PnL</span>
          <RoundPnlInline round={round} />
        </div>
      </div>
    </StackedListRow>
  );
}

function readFilters(searchParams: URLSearchParams): Filters {
  const page = Number(searchParams.get("page") || "1");
  const chainId = searchParams.get("chain") ? Number(searchParams.get("chain")) : undefined;
  const status = searchParams.get("status") || "all";

  return {
    status: ROUND_STATUS_FILTERS.has(status) ? status : "all",
    chainId: Number.isFinite(chainId) ? chainId : undefined,
    versions: readVersionFilters(searchParams),
    query: searchParams.get("filter") || searchParams.get("pair") || "",
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

function toSearchParams(filters: Filters) {
  const next = new URLSearchParams();
  if (filters.status !== "all") next.set("status", filters.status);
  if (filters.chainId) next.set("chain", String(filters.chainId));
  filters.versions.forEach((version) => next.append("version", version));
  if (filters.query) next.set("filter", filters.query);
  if (filters.page > 1) next.set("page", String(filters.page));
  return next;
}

function RoundsTableRow({
  round,
  href,
  onOpen,
  progressDisplayMode,
  onToggleProgressDisplayMode,
}: {
  round: RoundListItem;
  href: string;
  onOpen: () => void;
  progressDisplayMode: RoundProgressMiniMode;
  onToggleProgressDisplayMode: () => void;
}) {
  return (
    <tr
      className="data-row"
      onClick={(event) => handleRowNavigation(event, href, () => onOpen())}
      onAuxClick={(event) => handleRowNavigation(event, href, () => onOpen())}
    >
      <td className="w-[3.25rem] pr-1" title={`Chain ${round.chain_id}`}>
        <ChainIcon chainId={round.chain_id} />
      </td>
      <td className="w-[10.25rem] pl-1">
        <AuctionAddressValue address={round.auction_address} chainId={round.chain_id} />
      </td>
      <td className="w-[9rem] pr-4">
        <div className="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-2">
          <div className="min-w-0">
            <div className="font-mono text-primary">R{round.round_id}</div>
            <div
              className="mt-1 truncate font-mono text-[10px] leading-none text-tertiary"
              title={formatDateTime(round.kicked_at)}
            >
              {renderKickedValue(round.kicked_at, "relative")}
            </div>
          </div>
          <StatusBadge status={round.status} className="min-w-[3.9rem] px-1" />
        </div>
      </td>
      <td>
        <RoundProgressMini
          status={round.status}
          kickedAt={round.kicked_at}
          scheduledEndAt={round.scheduled_end_at}
          endAt={round.end_at}
          availableAmount={round.available_amount}
          initialAvailable={round.initial_available}
          fromTokenSymbol={round.from_token_symbol}
          takeCount={round.take_count}
          mode={progressDisplayMode}
          onToggleMode={onToggleProgressDisplayMode}
        />
      </td>
      <td className="text-primary">
        <RoundLotCell round={round} />
      </td>
      <td className="text-primary">
        <TokenAmountValue
          amount={round.paid_amount}
          coverage={{ count: round.paid_take_count, total: round.take_count }}
          address={round.want_token}
          symbol={round.want_token_symbol}
          logoUrl={round.want_token_logo_url}
          chainId={round.chain_id}
        />
      </td>
      <td className="w-[4.8rem] pr-1">
        <RoundPnlCell round={round} />
      </td>
    </tr>
  );
}

export default function RoundsPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [kickedDisplayMode, setKickedDisplayMode] = useState<KickedDisplayMode>("relative");
  const [progressDisplayMode, setProgressDisplayMode] = useState<RoundProgressMiniMode>("time");
  const filters = useMemo(() => readFilters(searchParams), [searchParams]);

  const chainsQuery = useChainsQuery();
  const chainsData = chainsQuery.data;
  const versionsQuery = useQuery({
    queryKey: ["auction-versions", filters.chainId],
    queryFn: ({ signal }) => api.getAuctionVersions(filters.chainId, signal),
  });
  const roundModalSource = roundModalSourceFromLocation(location);

  const normalizedQuery = filters.query.trim();
  const isAuctionAddressQuery = /^0x[a-fA-F0-9]{40}$/.test(normalizedQuery);
  const isTxHashQuery = /^0x[a-fA-F0-9]{64}$/.test(normalizedQuery);

  const roundsQuery = useQuery({
    queryKey: ["rounds", filters],
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

  const updateFilters = (patch: Partial<Filters>) => {
    const nextFilters: Filters = {
      ...filters,
      ...patch,
    };

    setSearchParams(toSearchParams(nextFilters));
  };

  return (
    <div className="space-y-3">
      <Panel className="space-y-2 p-2 md:p-2.5">
        <div className="grid gap-2 md:grid-cols-[11rem_11rem_13rem_minmax(18rem,1fr)]">
          <label className="space-y-0">
            <span className="metric-label">Status</span>
            <select
              className="filter-select w-full"
              value={filters.status}
              onChange={(event) => updateFilters({ status: event.target.value, page: 1 })}
            >
              <option value="all">All</option>
              <option value="live">Live</option>
              <option value="sold_out">Sold</option>
              <option value="expired">Expired</option>
              <option value="settled">Settled</option>
            </select>
          </label>

          <label className="space-y-0">
            <span className="metric-label">Chain</span>
            <select
              className="filter-select w-full"
              value={filters.chainId || ""}
              onChange={(event) =>
                updateFilters({ chainId: event.target.value ? Number(event.target.value) : undefined, page: 1 })
              }
            >
              <option value="">All chains</option>
              {Object.values(chainsData?.chains || {}).map((chain) => (
                <option key={chain.chain_id} value={chain.chain_id}>
                  {chain.short_name || chain.name}
                </option>
              ))}
            </select>
          </label>

          <div className="space-y-0">
            <span className="metric-label">Version</span>
            <VersionMultiSelect
              value={filters.versions}
              options={versionsQuery.data?.versions || []}
              onChange={(versions) => updateFilters({ versions, page: 1 })}
            />
          </div>

          <label className="space-y-0">
            <span className="metric-label">Filter</span>
            <input
              className="filter-input"
              value={filters.query}
              onChange={(event) => updateFilters({ query: event.target.value.trimStart(), page: 1 })}
              placeholder="Token, auction, or tx hash"
            />
          </label>
        </div>

        {chainsQuery.isError && <RequestError message={chainsData ? "Could not refresh network filters. Showing previously loaded data." : "Unable to load network filters."} onRetry={() => { void chainsQuery.refetch(); }} />}
        {versionsQuery.isError && <RequestError message={versionsQuery.data ? "Could not refresh version filters. Showing previously loaded data." : "Unable to load version filters."} onRetry={() => { void versionsQuery.refetch(); }} />}
        {roundsQuery.data ? (
          <div className="border-t border-divider-subtle pt-1.5 text-meta text-tertiary">
            {roundsQuery.data.total.toLocaleString()} matching rounds
          </div>
        ) : null}
      </Panel>

      <Panel padded={false}>
        {roundsQuery.isError && <RequestError message={roundsQuery.data ? "Could not refresh rounds. Showing previously loaded data." : "Unable to load rounds."} onRetry={() => { void roundsQuery.refetch(); }} />}
        {roundsQuery.isLoading ? (
          <div className="space-y-2 p-3">
            {Array.from({ length: 8 }).map((_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        ) : roundsQuery.isError && !roundsQuery.data ? null : roundsQuery.data?.rounds.length ? (
          <>
            <div className="md:hidden">
              {roundsQuery.data.rounds.map((round) => (
                <RoundsMobileRow
                  key={`${round.chain_id}:${occurrenceKey(round.occurrence)}`}
                  round={round}
                  href={buildRoundPathWithSource(round.chain_id, round.auction_address, round.occurrence, roundModalSource)}
                  onOpen={() =>
                    navigate(
                      buildRoundPathWithSource(round.chain_id, round.auction_address, round.occurrence, roundModalSource),
                      { state: withBackgroundLocation(location) },
                    )
                  }
                  kickedDisplayMode={kickedDisplayMode}
                  onToggleKickedDisplayMode={() =>
                    setKickedDisplayMode(toggleKickedDisplayMode)
                  }
                  progressDisplayMode={progressDisplayMode}
                  onToggleProgressDisplayMode={() =>
                    setProgressDisplayMode((current) => toggleProgressDisplayMode(current))
                  }
                />
              ))}
            </div>
            <div className="hidden md:block">
            <TableHoverScope>
              <table className="data-table">
                <thead>
                  <tr>
                    <th className="w-[3.25rem] pr-1">Chain</th>
                    <th className="w-[10.25rem] whitespace-nowrap pl-1">Auction</th>
                    <th className="w-[9rem] whitespace-nowrap pr-4">Round Status</th>
                    <th>
                      <button
                        type="button"
                        className="flex flex-col items-start font-inherit text-inherit underline-offset-4 transition-colors hover:text-primary hover:underline"
                        onClick={() => setProgressDisplayMode((current) => toggleProgressDisplayMode(current))}
                      >
                        <span className="uppercase">Progress</span>
                        <span className="normal-case text-[10px] text-tertiary">
                          ({progressDisplayMode === "time" ? "Time" : "Take"})
                        </span>
                      </button>
                    </th>
                    <th>Lot</th>
                    <th>Received</th>
                    <th className="w-[4.8rem] pr-1 leading-none">PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {roundsQuery.data.rounds.map((round) => (
                    <RoundsTableRow
                      key={`${round.chain_id}:${occurrenceKey(round.occurrence)}`}
                      round={round}
                      href={buildRoundPathWithSource(round.chain_id, round.auction_address, round.occurrence, roundModalSource)}
                      onOpen={() =>
                        navigate(
                          buildRoundPathWithSource(round.chain_id, round.auction_address, round.occurrence, roundModalSource),
                          { state: withBackgroundLocation(location) },
                        )
                      }
                      progressDisplayMode={progressDisplayMode}
                      onToggleProgressDisplayMode={() =>
                        setProgressDisplayMode((current) => toggleProgressDisplayMode(current))
                      }
                    />
                  ))}
                </tbody>
              </table>
            </TableHoverScope>
            </div>
          </>
        ) : (
          <div className="p-3">
            <EmptyState title="No rounds found" description="Try widening the status, chain, version, or pair filters." />
          </div>
        )}
        {roundsQuery.data ? (
          <div className="px-3 pb-3 pt-2 md:px-4">
            <Pagination
              page={filters.page}
              hasNext={roundsQuery.data.has_next}
              onPageChange={(page) => updateFilters({ page })}
            />
          </div>
        ) : null}
      </Panel>

    </div>
  );
}
