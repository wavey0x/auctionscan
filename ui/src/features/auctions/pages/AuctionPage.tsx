import MetricCoverage from "../../../shared/ui/MetricCoverage";
import type { ReactNode } from "react";
import { Fragment, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../../../shared/api/client";
import {
  formatAmount,
  formatCompactDateTime,
  formatDateTime,
  formatDuration,
  formatLongRelativeTime,
  formatPrice,
  renderKickedValue,
  toggleKickedDisplayMode,
} from "../../../shared/lib/format";
import type { KickedDisplayMode } from "../../../shared/lib/format";
import { getTakePricingBySource, resolvePriceSource, shouldShowPriceSourceSelector } from "../../../shared/lib/pricingSource";
import { handleRowNavigation } from "../../../shared/lib/rowNavigation";
import { roundProgressSummary } from "../../../shared/lib/roundProgress";
import { occurrenceKey, parseOccurrence, buildRoundPathWithSource, roundModalSourceFromLocation, withBackgroundLocation } from "../../../shared/lib/routes";
import AddressValue from "../../../shared/ui/AddressValue";
import AuctionAddressValue from "../../../shared/ui/AuctionAddressValue";
import AuctionVersionBadge from "../../../shared/ui/AuctionVersionBadge";
import ChainPill from "../../../shared/ui/ChainPill";
import EmptyState from "../../../shared/ui/EmptyState";
import Pagination from "../../../shared/ui/Pagination";
import Panel from "../../../shared/ui/Panel";
import PnlValue from "../../../shared/ui/PnlValue";
import PriceSourceSelect from "../../../shared/ui/PriceSourceSelect";
import RoundProgressMini, { toggleProgressDisplayMode, type RoundProgressMiniMode } from "../../../shared/ui/RoundProgressMini";
import Skeleton from "../../../shared/ui/Skeleton";
import StackedListRow from "../../../shared/ui/StackedListRow";
import StatusBadge from "../../../shared/ui/StatusBadge";
import TakeExpandedContent from "../../../shared/ui/TakeExpandedContent";
import TakerAddressValue from "../../../shared/ui/TakerAddressValue";
import TakeExpandedRow from "../../../shared/ui/TakeExpandedRow";
import { TableHoverScope } from "../../../shared/ui/TableHoverContext";
import TokenAmountValue from "../../../shared/ui/TokenAmountValue";
import TokenPairValue from "../../../shared/ui/TokenPairValue";
import TokenValue from "../../../shared/ui/TokenValue";
import TxHashValue from "../../../shared/ui/TxHashValue";

const PAGE_SIZE = 10;
const RECENT_TAKES_LIMIT = 12;
const SELL_TOKEN_PREVIEW_LIMIT = 8;

function InfoItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <div className="metric-label">{label}</div>
      <div className="mt-1 text-data text-primary">{value}</div>
    </div>
  );
}

function SellTokensPreview({
  chainId,
  tokens,
  expanded,
  onToggle,
}: {
  chainId: number;
  tokens: Array<{
    address: string;
    symbol: string;
    name: string;
    decimals: number;
    chain_id: number;
    logo_url?: string | null;
  }>;
  expanded: boolean;
  onToggle: () => void;
}) {
  const visibleTokens = expanded ? tokens : tokens.slice(0, SELL_TOKEN_PREVIEW_LIMIT);
  const overflow = Math.max(tokens.length - SELL_TOKEN_PREVIEW_LIMIT, 0);

  return (
    <div className="flex flex-wrap items-center gap-2">
      {visibleTokens.map((token) => (
        <span
          key={token.address}
          className="inline-flex items-center rounded-md border border-divider-subtle bg-background px-2 py-1"
        >
          <TokenValue token={token} chainId={chainId} showCopy />
        </span>
      ))}
      {overflow ? (
        <button
          type="button"
          className="text-meta text-tertiary underline-offset-4 transition-colors hover:text-primary hover:underline"
          onClick={onToggle}
        >
          {expanded ? "Show less" : `+${overflow} more`}
        </button>
      ) : null}
    </div>
  );
}

function RecentTakesList({
  takes,
  priceSource,
  selectedOccurrenceKey,
  selectedTake,
  isSelectedTakeLoading,
  onOpenTake,
}: {
  takes: Awaited<ReturnType<typeof api.getAuctionTakes>>["takes"];
  priceSource: string;
  selectedOccurrenceKey?: string | null;
  selectedTake?: Awaited<ReturnType<typeof api.getTake>>;
  isSelectedTakeLoading: boolean;
  onOpenTake: (key: string) => void;
}) {
  if (!takes.length) {
    return (
      <div className="p-3">
        <EmptyState title="No recent takes" description="This auction has no indexed take activity yet." />
      </div>
    );
  }

  return (
    <>
      <div className="md:hidden">
        {takes.map((take) => {
          const isSelected = occurrenceKey(take.occurrence) === selectedOccurrenceKey;
          const takePricing = getTakePricingBySource(take, priceSource);

          return (
            <StackedListRow
              key={`${take.chain_id}:${occurrenceKey(take.occurrence)}`}
              interactive
              className="space-y-2"
              onClick={() => onOpenTake(occurrenceKey(take.occurrence))}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-primary">R{take.round_id}</span>
                  <span className="font-mono text-tertiary">T{take.take_seq}</span>
                </div>
                <div className="font-mono text-meta text-tertiary" title={formatDateTime(take.timestamp)}>
                  {formatCompactDateTime(take.timestamp)}
                </div>
              </div>
              <div className="flex min-w-0 items-center justify-between gap-3">
                <div className="min-w-0">
                  <TakerAddressValue address={take.taker} chainId={take.chain_id} />
                </div>
                <TxHashValue txHash={take.tx_hash} chainId={take.chain_id} width={6} />
              </div>
              <div className="space-y-1">
                <div className="flex min-w-0 items-center gap-1.5">
                  <span className="metric-label shrink-0">Sold</span>
                  <TokenAmountValue
                    amount={take.amount_taken}
                    address={take.from_token}
                    symbol={take.from_token_symbol}
                    logoUrl={take.from_token_logo_url}
                    chainId={take.chain_id}
                    className="min-w-0 w-auto"
                  />
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <div className="flex min-w-0 items-center gap-1.5">
                    <span className="metric-label shrink-0">Paid</span>
                    <TokenAmountValue
                      amount={take.amount_paid}
                      estimatedAmount={take.expected_amount_paid}
                      address={take.to_token}
                      symbol={take.to_token_symbol}
                      logoUrl={take.to_token_logo_url}
                      chainId={take.chain_id}
                      className="min-w-0 w-auto"
                    />
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="metric-label shrink-0">Price</span>
                    <span className="font-mono text-primary">{formatPrice(take.price)}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="metric-label shrink-0">PnL</span>
                    <PnlValue percent={takePricing.pnl_percent} usd={takePricing.pnl_usd} compact />
                  </div>
                </div>
              </div>
              {isSelected ? (
                <div className="rounded-md border border-divider-subtle bg-background px-3 py-3">
                  {isSelectedTakeLoading ? (
                    <Skeleton className="h-32 w-full" />
                  ) : selectedTake ? (
                    <TakeExpandedContent take={selectedTake} priceSource={priceSource} />
                  ) : (
                    <EmptyState title="Take not found" description="The selected take detail could not be loaded." />
                  )}
                </div>
              ) : null}
            </StackedListRow>
          );
        })}
      </div>
      <div className="hidden md:block table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Round</th>
              <th>Take</th>
              <th>Time</th>
              <th>Taker</th>
              <th>Sold</th>
              <th>Paid</th>
              <th>Price</th>
              <th>PnL</th>
            </tr>
          </thead>
          <tbody>
            {takes.map((take) => {
              const isSelected = occurrenceKey(take.occurrence) === selectedOccurrenceKey;
              const takePricing = getTakePricingBySource(take, priceSource);

              return (
                <Fragment key={`${take.chain_id}:${occurrenceKey(take.occurrence)}`}>
                  <tr
                    className={`data-row ${isSelected ? "bg-surface" : ""}`}
                    onClick={() => onOpenTake(occurrenceKey(take.occurrence))}
                  >
                    <td className="font-mono text-primary">R{take.round_id}</td>
                    <td className="font-mono text-primary">T{take.take_seq}</td>
                    <td className="font-mono text-primary" title={formatDateTime(take.timestamp)}>
                      {formatCompactDateTime(take.timestamp)}
                    </td>
                    <td>
                      <TakerAddressValue address={take.taker} chainId={take.chain_id} />
                    </td>
                    <td className="text-primary">
                      <TokenAmountValue
                        amount={take.amount_taken}
                        address={take.from_token}
                        symbol={take.from_token_symbol}
                        logoUrl={take.from_token_logo_url}
                        chainId={take.chain_id}
                      />
                    </td>
                    <td className="text-primary">
                      <TokenAmountValue
                        amount={take.amount_paid}
                        estimatedAmount={take.expected_amount_paid}
                        address={take.to_token}
                        symbol={take.to_token_symbol}
                        logoUrl={take.to_token_logo_url}
                        chainId={take.chain_id}
                      />
                    </td>
                    <td className="font-mono text-primary">{formatPrice(take.price)}</td>
                    <td>
                      <PnlValue percent={takePricing.pnl_percent} usd={takePricing.pnl_usd} className="w-[4.8rem]" />
                    </td>
                  </tr>
                  {isSelected ? (
                    <TakeExpandedRow
                      colSpan={8}
                      take={selectedTake}
                      isLoading={isSelectedTakeLoading}
                      priceSource={priceSource}
                    />
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function RecentRoundsMobileList({
  rounds,
  kickedDisplayMode,
  onToggleKickedDisplayMode,
  progressDisplayMode,
  onToggleProgressDisplayMode,
  onOpenRound,
}: {
  rounds: Awaited<ReturnType<typeof api.getRounds>>["rounds"];
  kickedDisplayMode: KickedDisplayMode;
  onToggleKickedDisplayMode: () => void;
  progressDisplayMode: RoundProgressMiniMode;
  onToggleProgressDisplayMode: () => void;
  onOpenRound: (round: Awaited<ReturnType<typeof api.getRounds>>["rounds"][number]) => void;
}) {
  return (
    <div className="md:hidden">
      {rounds.map((round) => (
        <StackedListRow
          key={`${round.chain_id}:${occurrenceKey(round.occurrence)}`}
          interactive
          className="space-y-2"
          onClick={() => onOpenRound(round)}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="grid grid-cols-[auto_auto] items-center gap-1">
              <span className="font-mono text-primary">R{round.round_id}</span>
              <StatusBadge status={round.status} className="min-w-[3.9rem] px-1" />
            </div>
            <div className="font-mono text-meta text-tertiary">{round.take_count} takes</div>
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
              onClick={(event) => {
                event.stopPropagation();
                onToggleProgressDisplayMode();
              }}
            >
              {roundProgressSummary(round, progressDisplayMode)}
            </button>
            <span aria-hidden="true">·</span>
            <span className="font-mono" title={formatDateTime(round.end_at || round.last_take_at)}>
              {formatCompactDateTime(round.end_at || round.last_take_at)}
            </span>
          </div>
          <div className="space-y-1">
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="metric-label shrink-0">Sold</span>
              <TokenAmountValue
                amount={round.sold_amount}
                address={round.from_token}
                symbol={round.from_token_symbol}
                logoUrl={round.from_token_logo_url}
                chainId={round.chain_id}
                className="min-w-0 w-auto"
              />
            </div>
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
            <div className="flex items-center gap-1.5">
              <span className="metric-label shrink-0">PnL</span>
              <PnlValue
                percent={round.total_auction_profit_bps}
                usd={round.total_auction_profit_usd}
                compact
              />
              <MetricCoverage count={round.priced_take_count ?? 0} total={round.take_count} label="quoted" />
              {round.usd_priced_take_count !== (round.priced_take_count ?? 0) ? <MetricCoverage count={round.usd_priced_take_count} total={round.take_count} label="USD" /> : null}
            </div>
          </div>
        </StackedListRow>
      ))}
    </div>
  );
}

export default function AuctionPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { chainId, address } = useParams<{ chainId: string; address: string }>();
  const [searchParams, setSearchParams] = useSearchParams();

  const chain = Number(chainId);
  const page = Math.max(1, Number(searchParams.get("page") || "1"));
  const selectedTakeParam = searchParams.get("take");
  const requestedPriceSource = searchParams.get("priceSource");
  const selectedOccurrence = parseOccurrence(chain, selectedTakeParam);
  const [showAllSellTokens, setShowAllSellTokens] = useState(false);
  const roundModalSource = roundModalSourceFromLocation(location);
  const [kickedDisplayMode, setKickedDisplayMode] = useState<KickedDisplayMode>("relative");
  const [progressDisplayMode, setProgressDisplayMode] = useState<RoundProgressMiniMode>("time");

  const auctionQuery = useQuery({
    queryKey: ["auction", chain, address],
    queryFn: ({ signal }) => api.getAuction(chain, address!, signal),
    enabled: Number.isFinite(chain) && !!address,
  });

  const roundsQuery = useQuery({
    queryKey: ["auction-rounds-index", chain, address, page],
    queryFn: ({ signal }) =>
      api.getRounds({
        chain_id: chain,
        auction_address: address,
        page,
        limit: PAGE_SIZE,
      }, signal),
    enabled: Number.isFinite(chain) && !!address,
  });

  const recentTakesQuery = useQuery({
    queryKey: ["auction-recent-takes", chain, address],
    queryFn: ({ signal }) => api.getAuctionTakes(chain, address!, undefined, RECENT_TAKES_LIMIT, signal),
    enabled: Number.isFinite(chain) && !!address,
  });

  const selectedTakeQuery = useQuery({
    queryKey: ["take-detail", selectedOccurrence],
    queryFn: ({ signal }) => api.getTake(selectedOccurrence!, signal),
    enabled: Boolean(selectedOccurrence),
  });

  const selectedTake = !selectedTakeQuery.isError && selectedTakeQuery.data?.auction.toLowerCase() === address?.toLowerCase() ? selectedTakeQuery.data : undefined;

  const pairTokens = useMemo(() => {
    if (!auctionQuery.data) {
      return null;
    }

    return {
      fromToken: auctionQuery.data.from_tokens[0],
      toToken: auctionQuery.data.want_token,
      fromCount: auctionQuery.data.from_tokens.length,
    };
  }, [auctionQuery.data]);

  const setSelectedTake = (key?: string) => {
    const next = new URLSearchParams(searchParams);
    if (!key) {
      next.delete("take");
    } else {
      next.set("take", key);
    }
    setSearchParams(next, { replace: true });
  };

  const setPriceSource = (sourceId: string) => {
    const next = new URLSearchParams(searchParams);
    if (sourceId === "canonical") {
      next.delete("priceSource");
    } else {
      next.set("priceSource", sourceId);
    }
    setSearchParams(next, { replace: true });
  };

  useEffect(() => {
    if (!selectedTakeParam) {
      return undefined;
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSelectedTake(undefined);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedTakeParam, searchParams, setSearchParams]);

  const recentTakeOptions = recentTakesQuery.data?.available_price_sources || [];
  const selectedPriceSource = resolvePriceSource(requestedPriceSource, recentTakeOptions);
  const showPriceSourceSelector = shouldShowPriceSourceSelector(recentTakeOptions);

  useEffect(() => {
    if (!recentTakeOptions.length) {
      return;
    }
    const normalized = requestedPriceSource?.trim().toLowerCase() || "canonical";
    if (normalized === selectedPriceSource) {
      return;
    }
    setPriceSource(selectedPriceSource);
  }, [requestedPriceSource, selectedPriceSource, recentTakeOptions.length]);

  if (auctionQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-[28rem] w-full" />
      </div>
    );
  }

  if (!auctionQuery.data) {
    return <EmptyState title="Auction not found" description="The requested auction could not be loaded." />;
  }

  const sellTokenCount = auctionQuery.data.from_tokens.length;
  const hasSingleSellToken = sellTokenCount === 1;

  return (
    <div className="space-y-4">
      <Link
        to="/"
        className="inline-flex items-center gap-2 text-meta text-tertiary underline-offset-4 transition-colors hover:text-primary hover:underline"
      >
        <ArrowLeft className="h-3.5 w-3.5" strokeWidth={1.8} />
        Back
      </Link>

      <Panel className="space-y-4">
        <div className="space-y-3">
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="metric-label">Auction:</span>
              <AuctionAddressValue
                address={auctionQuery.data.address}
                chainId={auctionQuery.data.chain_id}
                width={8}
                showCowExplorerIcon
              />
              <AuctionVersionBadge version={auctionQuery.data.version} />
            </div>
            <ChainPill chainId={auctionQuery.data.chain_id} size="xs" />
          </div>

          {hasSingleSellToken && pairTokens ? (
            <div className="space-y-1">
              <div className="metric-label">Pair</div>
              <TokenPairValue
                fromToken={pairTokens.fromToken}
                toToken={pairTokens.toToken}
                chainId={auctionQuery.data.chain_id}
                size="md"
                showCopy
              />
            </div>
          ) : (
            <div className="space-y-3">
              <div className="space-y-1">
                <div className="metric-label">Want token</div>
                <TokenValue token={auctionQuery.data.want_token} chainId={auctionQuery.data.chain_id} size="md" />
              </div>
              <div className="space-y-1">
                <div className="metric-label">Sell tokens</div>
                <SellTokensPreview
                  chainId={auctionQuery.data.chain_id}
                  tokens={auctionQuery.data.from_tokens}
                  expanded={showAllSellTokens}
                  onToggle={() => setShowAllSellTokens((value) => !value)}
                />
              </div>
            </div>
          )}
        </div>

        <div className="grid gap-4 border-t border-divider-strong pt-4 sm:grid-cols-2 xl:grid-cols-6">
          <InfoItem
            label="Receiver"
            value={
              <AddressValue
                address={auctionQuery.data.receiver}
                chainId={auctionQuery.data.chain_id}
                label={auctionQuery.data.receiver_name}
              />
            }
          />
          <InfoItem
            label="Decay"
            value={auctionQuery.data.parameters.decay_percent ?? "—"}
          />
          <InfoItem label="Duration" value={formatDuration(auctionQuery.data.parameters.auction_length)} />
          <InfoItem label="Total rounds" value={<span className="font-mono">{auctionQuery.data.activity.total_rounds.toLocaleString()}</span>} />
          <InfoItem label="Volume" value={<span className="font-mono">{formatVolume(auctionQuery.data.activity.total_volume, auctionQuery.data.want_token.symbol)} <MetricCoverage count={auctionQuery.data.activity.paid_take_count} total={auctionQuery.data.activity.total_takes} /></span>} />
          <InfoItem
            label="Min price"
            value={<span className="font-mono">{formatPrice(auctionQuery.data.parameters.minimum_price)}</span>}
          />
        </div>
      </Panel>

      <Panel padded={false}>
        <div className="px-3 pt-3 md:px-4">
          <div className="text-heading text-primary">
            Recent rounds: <span className="font-mono">{auctionQuery.data.activity.total_rounds.toLocaleString()}</span>
          </div>
        </div>
        {roundsQuery.isLoading ? (
          <div className="space-y-2 p-3">
            {Array.from({ length: 8 }).map((_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        ) : roundsQuery.data?.rounds.length ? (
          <>
            <RecentRoundsMobileList
              rounds={roundsQuery.data.rounds}
              kickedDisplayMode={kickedDisplayMode}
              onToggleKickedDisplayMode={() =>
                setKickedDisplayMode(toggleKickedDisplayMode)
              }
              progressDisplayMode={progressDisplayMode}
              onToggleProgressDisplayMode={() =>
                setProgressDisplayMode((current) => toggleProgressDisplayMode(current))
              }
              onOpenRound={(round) =>
                navigate(
                  buildRoundPathWithSource(round.chain_id, round.auction_address, round.occurrence, roundModalSource),
                  { state: withBackgroundLocation(location) },
                )
              }
            />
            <div className="hidden md:block table-wrap">
            <TableHoverScope>
              <table className="data-table">
                <thead>
                  <tr>
                    <th className="w-[7.5rem] whitespace-nowrap">Round Status</th>
                    <th>
                      <button
                        type="button"
                        className="font-inherit normal-case text-inherit underline-offset-4 transition-colors hover:text-primary hover:underline"
                        onClick={() => setProgressDisplayMode((current) => toggleProgressDisplayMode(current))}
                      >
                        Progress ({progressDisplayMode === "time" ? "Time" : "Take"})
                      </button>
                    </th>
                    <th>
                      <button
                        type="button"
                        className="font-inherit uppercase text-inherit underline-offset-4 transition-colors hover:text-primary hover:underline"
                        onClick={() =>
                          setKickedDisplayMode((current) =>
                            current === "relative" ? "absolute" : "relative",
                          )
                        }
                      >
                        Kicked
                      </button>
                    </th>
                    <th>Closed</th>
                    <th className="text-right">Takes</th>
                    <th>Sold</th>
                    <th>Received</th>
                    <th className="w-[4.8rem] pr-1 leading-none">PnL</th>
                  </tr>
                </thead>
                <tbody>
                  {roundsQuery.data.rounds.map((round) => (
                    <tr
                      key={`${round.chain_id}:${occurrenceKey(round.occurrence)}`}
                      className="data-row"
                      onClick={(event) =>
                        handleRowNavigation(
                          event,
                          buildRoundPathWithSource(round.chain_id, round.auction_address, round.occurrence, roundModalSource),
                          (to) => navigate(to, { state: withBackgroundLocation(location) }),
                        )
                      }
                      onAuxClick={(event) =>
                        handleRowNavigation(
                          event,
                          buildRoundPathWithSource(round.chain_id, round.auction_address, round.occurrence, roundModalSource),
                          (to) => navigate(to, { state: withBackgroundLocation(location) }),
                        )
                      }
                    >
                      <td className="w-[7.5rem]">
                        <div className="grid grid-cols-[2.35rem_minmax(0,1fr)] items-center gap-1">
                          <span className="font-mono text-primary">R{round.round_id}</span>
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
                          mode={progressDisplayMode}
                          onToggleMode={() =>
                            setProgressDisplayMode((current) => toggleProgressDisplayMode(current))
                          }
                        />
                      </td>
                      <td title={formatDateTime(round.kicked_at)}>
                        <button
                          type="button"
                          className="font-mono text-primary underline-offset-4 transition-colors hover:text-primary hover:underline"
                          onClick={(event) => {
                            event.stopPropagation();
                            setKickedDisplayMode(toggleKickedDisplayMode);
                          }}
                        >
                          {renderKickedValue(round.kicked_at, kickedDisplayMode)}
                        </button>
                      </td>
                      <td className="font-mono text-primary" title={formatDateTime(round.end_at || round.last_take_at)}>
                        {formatCompactDateTime(round.end_at || round.last_take_at)}
                      </td>
                      <td className="text-right font-mono text-primary">{round.take_count}</td>
                      <td className="text-primary">
                        <TokenAmountValue
                          amount={round.sold_amount}
                          address={round.from_token}
                          symbol={round.from_token_symbol}
                          logoUrl={round.from_token_logo_url}
                          chainId={round.chain_id}
                        />
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
                        <PnlValue
                          percent={round.total_auction_profit_bps}
                          usd={round.total_auction_profit_usd}
                          className="w-[4.8rem]"
                        />
                        <MetricCoverage count={round.priced_take_count ?? 0} total={round.take_count} label="quoted" />
                        {round.usd_priced_take_count !== (round.priced_take_count ?? 0) ? <MetricCoverage count={round.usd_priced_take_count} total={round.take_count} label="USD" /> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableHoverScope>
            </div>
          </>
        ) : (
          <div className="p-3">
            <EmptyState title="No rounds available" description="This auction does not have any indexed rounds yet." />
          </div>
        )}
        {roundsQuery.data ? (
          <div className="px-3 pb-3 pt-2 md:px-4">
            <Pagination
              page={page}
              hasNext={roundsQuery.data.has_next}
              onPageChange={(nextPage) => {
                const next = new URLSearchParams(searchParams);
                if (nextPage <= 1) next.delete("page");
                else next.set("page", String(nextPage));
                setSearchParams(next);
              }}
              summary={`${roundsQuery.data.total.toLocaleString()} rounds in this auction`}
            />
          </div>
        ) : null}
      </Panel>

      <Panel padded={false}>
        <div className="flex items-center justify-between gap-3 px-3 pt-3 md:px-4">
          <div className="flex items-center gap-3">
            <div className="text-heading text-primary">Recent takes</div>
            {showPriceSourceSelector ? (
              <PriceSourceSelect
                value={selectedPriceSource}
                options={recentTakeOptions}
                onChange={setPriceSource}
              />
            ) : null}
          </div>
          <div className="flex items-center justify-between gap-3">
            <div className="font-mono text-meta text-tertiary">{recentTakesQuery.data?.takes.length ?? 0}</div>
          </div>
        </div>
        {selectedTakeParam && !selectedTakeQuery.isFetching && !selectedTake ? <EmptyState title="Take unavailable" description="This occurrence is absent from the indexed auction." /> : null}
        {recentTakesQuery.isLoading ? (
          <div className="space-y-2 p-3">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-14 w-full" />
            ))}
          </div>
        ) : (
          <TableHoverScope>
            <RecentTakesList
              takes={recentTakesQuery.data?.takes || []}
              priceSource={selectedPriceSource}
              selectedOccurrenceKey={selectedTakeParam}
              selectedTake={selectedTake}
              isSelectedTakeLoading={selectedTakeQuery.isLoading}
              onOpenTake={(key) => setSelectedTake(selectedTakeParam === key ? undefined : key)}
            />
          </TableHoverScope>
        )}
      </Panel>
    </div>
  );
}

function formatVolume(value: string | null | undefined, symbol?: string | null) {
  if (!value) {
    return "—";
  }

  return `${formatAmount(value)} ${symbol || ""}`.trim();
}
