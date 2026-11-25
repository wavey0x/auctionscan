import { useEffect, useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useMatch, useNavigationType, useSearchParams } from "react-router-dom";

import AuctionRecentTakes from "../../auctions/components/AuctionRecentTakes";
import AuctionScopeHead from "../../auctions/components/AuctionScopeHead";
import { api } from "../../../shared/api/client";
import { useChainsQuery } from "../../../shared/lib/chains";
import {
  cn,
  formatAmount,
  formatCount,
  formatDateTime,
  renderKickedValue,
  toggleKickedDisplayMode,
} from "../../../shared/lib/format";
import type { KickedDisplayMode } from "../../../shared/lib/format";
import { useRoundRows } from "../../../shared/lib/openRound";
import { roundPnlCoverageTitle } from "../../../shared/lib/pricingSource";
import { occurrenceKey } from "../../../shared/lib/routes";
import { auctionLabel, parseProtocol, PROTOCOL_LABELS, PROTOCOLS, roundNumberIsMeaningful, type Protocol } from "../../../shared/lib/protocol";
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
import { ChipCount, ChipGroup, FilterField } from "../../../shared/ui/Toolbar";

const PAGE_SIZE = 20;

/**
 * The states worth isolating from the list: what is about to open, what is
 * open now, what cleared and what failed to. Together their counts account for
 * the list, so no one of them reads as its total; a settled round stays in the
 * unfiltered list.
 */
const STATUS_CHIPS = ["scheduled", "live", "sold_out", "expired"] as const;
type RoundStatusFilter = "all" | (typeof STATUS_CHIPS)[number];

function parseRoundStatus(value: string | null): RoundStatusFilter {
  return (STATUS_CHIPS as readonly string[]).includes(value ?? "")
    ? (value as RoundStatusFilter)
    : "all";
}

type Filters = {
  status: RoundStatusFilter;
  protocol?: Protocol;
  chainId?: number;
  query: string;
  page: number;
};

const FILTER_KEYS = ["status", "protocol", "chain", "filter", "pair", "page"];

function readFilters(searchParams: URLSearchParams): Filters {
  const page = Number(searchParams.get("page") || "1");
  const chainId = searchParams.get("chain") ? Number(searchParams.get("chain")) : undefined;
  return {
    status: parseRoundStatus(searchParams.get("status")),
    protocol: parseProtocol(searchParams.get("protocol")),
    chainId: Number.isFinite(chainId) ? chainId : undefined,
    query: searchParams.get("filter") || searchParams.get("pair") || "",
    page: Number.isFinite(page) && page > 0 ? page : 1,
  };
}

/** The list's filters written over the current URL, leaving what else it carries alone. */
function withFilters(current: URLSearchParams, filters: Filters) {
  const next = new URLSearchParams(current);
  FILTER_KEYS.forEach((key) => next.delete(key));
  if (filters.status !== "all") next.set("status", filters.status);
  if (filters.protocol) next.set("protocol", filters.protocol);
  if (filters.chainId) next.set("chain", String(filters.chainId));
  if (filters.query) next.set("filter", filters.query);
  if (filters.page > 1) next.set("page", String(filters.page));
  return next;
}

/** The auction the list is narrowed to when it is opened at `/auction/:chainId/:address`. */
type AuctionScope = { chainId: number; address: string };

function useAuctionScope(): { scope: AuctionScope | null; invalid: boolean } {
  const match = useMatch("/auction/:chainId/:address");
  const chainId = Number(match?.params.chainId);
  const address = match?.params.address ?? "";
  return useMemo(() => {
    if (!match) return { scope: null, invalid: false };
    if (!Number.isSafeInteger(chainId) || chainId <= 0 || !address) return { scope: null, invalid: true };
    return { scope: { chainId, address }, invalid: false };
  }, [Boolean(match), chainId, address]);
}

/** Where the whole list was last left, so leaving an auction returns to it with its filters and page. */
let lastListSearch = "";

/** The PnL column states one figure at a time: the rate a round cleared at, or what that came to. */
type PnlDisplayMode = "percent" | "usd";

function lotSummary(round: RoundListItem): string {
  const amount = round.initial_available ?? round.sold_amount;
  return [formatAmount(amount), round.from_token_symbol].filter(Boolean).join(" ");
}

function RoundRow({
  round,
  rowProps,
  progressMode,
  pnlMode,
  kickedMode,
  scoped,
}: {
  round: RoundListItem;
  rowProps: ReturnType<ReturnType<typeof useRoundRows<RoundListItem>>["rowProps"]>;
  progressMode: RoundProgressMiniMode;
  pnlMode: PnlDisplayMode;
  kickedMode: KickedDisplayMode;
  /** Within one auction a row is identified by its round alone, and the auction column is dropped. */
  scoped: boolean;
}) {
  const kicked = renderKickedValue(round.kicked_at, kickedMode);
  return (
    <tr {...rowProps}>
      {scoped ? (
        <td>
          <span className="font-mono">R{round.round_id}</span>
          <div className="sub-line">
            <span className="sub-lo">{`${statusLabel(round.status)} · ${lotSummary(round)} · `}</span>
            {renderKickedValue(round.kicked_at, "relative")}
          </div>
        </td>
      ) : (
        <td>
          <span className="flex min-w-0 items-center gap-2.5">
            <ChainIcon chainId={round.chain_id} />
            {/* The round rides on its auction, where its number places it; a burner's lot is known by its token. */}
            <AuctionAddressValue
              address={round.auction_address}
              chainId={round.chain_id}
              label={auctionLabel(round.protocol)}
              bareLabel
              tag={roundNumberIsMeaningful(round.protocol) ? `R${round.round_id}` : null}
            />
          </span>
          <div className="sub-line pl-[26px]">
            <span className="sub-lo">{`${statusLabel(round.status)} · ${lotSummary(round)} · `}</span>
            {renderKickedValue(round.kicked_at, "relative")}
          </div>
        </td>
      )}
      <td className="col-lo pr-4"><StatusBadge status={round.status} /></td>
      <td className="col-md pr-4">
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
          show={pnlMode}
          align="right"
          title={roundPnlCoverageTitle(round)}
        />
      </td>
      <td className="col-md num dim pl-4" title={formatDateTime(round.kicked_at)}>{kicked}</td>
      <OpenMark />
    </tr>
  );
}

/**
 * The rounds list, and an auction opened on it. `/auction/:chainId/:address`
 * is this same list narrowed to one auction, with the auction's identity and
 * settings heading the card: the filters, the table and the reader's place
 * stay where they were.
 */
export default function RoundsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigationType = useNavigationType();
  const [kickedDisplayMode, setKickedDisplayMode] = useState<KickedDisplayMode>("relative");
  const [progressDisplayMode, setProgressDisplayMode] = useState<RoundProgressMiniMode>("time");
  const [pnlDisplayMode, setPnlDisplayMode] = useState<PnlDisplayMode>("percent");
  const filters = useMemo(() => readFilters(searchParams), [searchParams]);
  const { scope, invalid: scopeInvalid } = useAuctionScope();
  const scopeKey = scope ? `${scope.chainId}:${scope.address.toLowerCase()}` : null;

  const chainsQuery = useChainsQuery();
  const chainsData = chainsQuery.data;

  const normalizedQuery = filters.query.trim();
  // Inside an auction the address is already given, so the field only narrows by token or transaction.
  const isAuctionAddressQuery = !scope && /^0x[a-fA-F0-9]{40}$/.test(normalizedQuery);
  const isTxHashQuery = /^0x[a-fA-F0-9]{64}$/.test(normalizedQuery);

  const roundsQuery = useQuery({
    queryKey: ["rounds", scopeKey, filters],
    // Keep chip counts, rows and pagination in place while a new filter loads.
    placeholderData: keepPreviousData,
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
    enabled: !scopeInvalid,
    queryFn: async ({ signal }) => ({
      ...(await api.getRounds({
        status: filters.status,
        protocol: scope ? "all" : filters.protocol ?? "all",
        chain_id: scope ? scope.chainId : filters.chainId,
        auction_address: scope ? scope.address : isAuctionAddressQuery ? normalizedQuery : undefined,
        tx_hash: isTxHashQuery ? normalizedQuery : undefined,
        pair: normalizedQuery && !isAuctionAddressQuery && !isTxHashQuery ? normalizedQuery : undefined,
        page: filters.page,
        limit: PAGE_SIZE,
      }, signal)),
      scopeKey,
    }),
  });

  const auctionQuery = useQuery({
    queryKey: ["auction", scope?.chainId, scope?.address],
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
    queryFn: ({ signal }) => api.getAuction(scope!.chainId, scope!.address, signal),
    enabled: Boolean(scope),
  });
  // An auction the index has confirmed it does not hold has no rounds to list.
  const auctionMissing = Boolean(scope) && auctionQuery.isSuccess && auctionQuery.data === null;

  const rounds = roundsQuery.data?.rounds;
  const { rowProps } = useRoundRows(rounds, { stale: roundsQuery.isPlaceholderData });
  // The table takes the shape of the rows it is showing, so rows kept on screen
  // while an auction loads do not lose their auction column before they leave.
  const tableScoped = roundsQuery.data ? roundsQuery.data.scopeKey !== null : scope !== null;

  useEffect(() => {
    if (!scopeKey && !scopeInvalid) lastListSearch = searchParams.toString();
  }, [scopeKey, scopeInvalid, searchParams]);

  // An auction opened from further down the list starts at its head. Going
  // back is left to the browser, which returns the reader to where they were.
  useEffect(() => {
    if (scopeKey && navigationType !== "POP" && window.scrollY > 0) window.scrollTo(0, 0);
  }, [scopeKey]);

  const updateFilters = (patch: Partial<Filters>) => {
    setSearchParams(withFilters(searchParams, { ...filters, ...patch }));
  };

  if (scopeInvalid || auctionMissing) {
    return <EmptyState title="Auction not found" description="The requested auction could not be loaded." />;
  }

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
        {roundsQuery.isPlaceholderData ? <span role="status" aria-label="Updating rounds" className="sr-only" /> : null}
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
          <div className="filter-line">
            <ChipGroup
              label="Round status"
              single
              options={STATUS_CHIPS.map((status) => ({
                value: status,
                label: <>{statusLabel(status)}<ChipCount value={counts?.[status]} /></>,
              }))}
              selected={filters.status === "all" ? [] : [filters.status]}
              onChange={(next) => updateFilters({ status: next[0] ?? "all", page: 1 })}
            />
            {scope ? null : (
              <ChipGroup
                label="Protocol"
                single
                options={PROTOCOLS.map((protocol) => ({ value: protocol, label: PROTOCOL_LABELS[protocol] }))}
                selected={filters.protocol ? [filters.protocol] : []}
                onChange={(next) => updateFilters({ protocol: next[0], page: 1 })}
              />
            )}
            {/* A choice between chains exists only once there is more than one. */}
            {scope || chainOptions.length < 2 ? null : (
              <ChipGroup
                label="Chain"
                single
                options={chainOptions}
                selected={filters.chainId ? [filters.chainId] : []}
                onChange={(next) => updateFilters({ chainId: next[0], page: 1 })}
              />
            )}
          </div>
          <FilterField
            label="Filter rounds"
            value={filters.query}
            onChange={(value) => updateFilters({ query: value.trimStart(), page: 1 })}
            placeholder={scope ? "Token or tx hash" : "Token, auction or tx hash"}
          />
        </div>
        {chainsQuery.isError && !chainsData && <RequestError message="Unable to load network filters." onRetry={() => { void chainsQuery.refetch(); }} />}
      </div>

      <section className="card card-clip" aria-label="Rounds">
        {scope ? (
          <AuctionScopeHead
            chainId={scope.chainId}
            address={scope.address}
            auctionQuery={auctionQuery}
            backTo={{ pathname: "/", search: lastListSearch }}
          />
        ) : null}
        {roundsQuery.isError && !roundsQuery.data && <RequestError message="Unable to load rounds." onRetry={() => { void roundsQuery.refetch(); }} />}
        {roundsQuery.isError && !roundsQuery.data ? null : (
          <div className="table-wrap">
            <TableHoverScope>
              <table className="data-table rounds-table" aria-busy={roundsQuery.isLoading || roundsQuery.isPlaceholderData}>
                <thead>
                  {/* The header sizes the columns (`rcol-*`); Lot and Received take what is left. */}
                  <tr>
                    {tableScoped ? <th className="rcol-id">Round</th> : <th className="rcol-auction">Auction</th>}
                    <th className="col-lo rcol-status">Status</th>
                    <th className="col-md rcol-progress">
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
                    <th className="num rcol-pnl">
                      <button
                        type="button"
                        className="header-toggle"
                        title={pnlDisplayMode === "percent" ? "Show PnL in USD" : "Show PnL as a percentage"}
                        onClick={() => setPnlDisplayMode((current) => (current === "percent" ? "usd" : "percent"))}
                      >
                        PnL <em>{pnlDisplayMode === "percent" ? "%" : "$"}</em>
                      </button>
                    </th>
                    <th className={cn("col-md num rcol-kicked", kickedDisplayMode === "absolute" && "is-dated")}>
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
                      widths={[tableScoped ? 36 : 150, 52, 104, 120, 120, 64, 44, null]}
                      classNames={[undefined, "col-lo", "col-md", "col-lo", "col-lo", "num", "col-md num", "open-cell"]}
                    />
                  ) : rounds?.length ? (
                    rounds.map((round) => (
                      <RoundRow
                        key={`${round.chain_id}:${occurrenceKey(round.occurrence)}`}
                        round={round}
                        rowProps={rowProps(round)}
                        progressMode={progressDisplayMode}
                        pnlMode={pnlDisplayMode}
                        kickedMode={kickedDisplayMode}
                        scoped={tableScoped}
                      />
                    ))
                  ) : (
                    <tr>
                      <td colSpan={8}>
                        <EmptyState
                          title="No rounds found"
                          description={scope ? "Clear the status or the token filter to see all of this auction's rounds." : "Clear a status, or widen the token filter."}
                        />
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
      {scope ? <AuctionRecentTakes key={scopeKey} chainId={scope.chainId} address={scope.address} /> : null}
    </div>
  );
}
