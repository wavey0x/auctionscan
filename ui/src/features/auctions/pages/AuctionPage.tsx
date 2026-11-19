import type { CSSProperties, ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import AuctionRoundsTable from "../components/AuctionRoundsTable";
import AuctionTakesTable from "../components/AuctionTakesTable";
import { ApiError, api } from "../../../shared/api/client";
import { formatAmount, formatCount, formatDuration, formatPrice, toggleKickedDisplayMode } from "../../../shared/lib/format";
import type { KickedDisplayMode } from "../../../shared/lib/format";
import { resolvePriceSource, shouldShowPriceSourceSelector } from "../../../shared/lib/pricingSource";
import { parseOccurrence } from "../../../shared/lib/routes";
import AddressValue from "../../../shared/ui/AddressValue";
import AuctionAddressValue from "../../../shared/ui/AuctionAddressValue";
import AuctionVersionBadge from "../../../shared/ui/AuctionVersionBadge";
import ChainIcon from "../../../shared/ui/ChainIcon";
import EmptyState from "../../../shared/ui/EmptyState";
import RequestError from "../../../shared/ui/RequestError";
import Pagination from "../../../shared/ui/Pagination";
import PriceSourceSelect from "../../../shared/ui/PriceSourceSelect";
import { toggleProgressDisplayMode, type RoundProgressMiniMode } from "../../../shared/ui/RoundProgressMini";
import SkeletonRows from "../../../shared/ui/SkeletonRows";
import StatStrip, { Stat } from "../../../shared/ui/StatStrip";
import { TableHoverScope } from "../../../shared/ui/TableHoverContext";
import TokenPairValue from "../../../shared/ui/TokenPairValue";
import TokenValue from "../../../shared/ui/TokenValue";
import { LIVE_REFETCH_INTERVAL_MS } from "../../../shared/lib/polling";

const PAGE_SIZE = 10;
const RECENT_TAKES_LIMIT = 12;
const SELL_TOKEN_PREVIEW_LIMIT = 8;

function InfoItem({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="label">{label}</div>
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
          className="inline-flex items-center rounded-[6px] bg-hover px-2 py-1"
        >
          <TokenValue token={token} chainId={chainId} showCopy />
        </span>
      ))}
      {overflow ? (
        <button
          type="button"
          className="text-meta text-tertiary transition-colors hover:text-primary"
          onClick={onToggle}
        >
          {expanded ? "Show less" : `+${overflow} more`}
        </button>
      ) : null}
    </div>
  );
}

export default function AuctionPage() {
  const { chainId, address } = useParams<{ chainId: string; address: string }>();
  const [searchParams, setSearchParams] = useSearchParams();

  const chain = Number(chainId);
  const page = Math.max(1, Number(searchParams.get("page") || "1"));
  const selectedTakeParam = searchParams.get("take");
  const requestedPriceSource = searchParams.get("priceSource");
  const selectedOccurrence = parseOccurrence(chain, selectedTakeParam);
  const [showAllSellTokens, setShowAllSellTokens] = useState(false);
  const [kickedDisplayMode, setKickedDisplayMode] = useState<KickedDisplayMode>("relative");
  const [progressDisplayMode, setProgressDisplayMode] = useState<RoundProgressMiniMode>("time");

  const auctionQuery = useQuery({
    queryKey: ["auction", chain, address],
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
    queryFn: ({ signal }) => api.getAuction(chain, address!, signal),
    enabled: Number.isFinite(chain) && !!address,
  });

  const roundsQuery = useQuery({
    queryKey: ["auction-rounds-index", chain, address, page],
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
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
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
    queryFn: ({ signal }) => api.getAuctionTakes(chain, address!, undefined, RECENT_TAKES_LIMIT, signal),
    enabled: Number.isFinite(chain) && !!address,
  });

  const selectedTakeQuery = useQuery({
    queryKey: ["take-detail", selectedOccurrence],
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
    queryFn: ({ signal }) => api.getTake(selectedOccurrence!, signal),
    enabled: Boolean(selectedOccurrence),
  });

  const takeNotFound = selectedTakeQuery.error instanceof ApiError && selectedTakeQuery.error.status === 404;
  const selectedTake = !takeNotFound && selectedTakeQuery.data?.auction.toLowerCase() === address?.toLowerCase() ? selectedTakeQuery.data : undefined;
  const selectedTakeNotice = !selectedTakeParam ? null : !selectedOccurrence ? <EmptyState title="Invalid take link" /> : takeNotFound || (selectedTakeQuery.isSuccess && !selectedTake) ? (
    <EmptyState title="Take not found" description="This occurrence is absent from the indexed auction." />
  ) : selectedTakeQuery.isError && !selectedTake ? (
    <RequestError message="Unable to load take." onRetry={() => { void selectedTakeQuery.refetch(); }} />
  ) : null;

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
      <div className="space-y-4" aria-busy="true">
        <span className="skeleton-bar w-24" />
        <div className="card space-y-3 p-5">
          <span className="skeleton-bar h-4 w-56" />
          <span className="skeleton-bar w-80 max-w-full" />
        </div>
        <div className="strip" style={{ "--n": 5 } as CSSProperties}>
          {Array.from({ length: 5 }).map((_, index) => (
            <div key={index} className="stat space-y-2">
              <span className="skeleton-bar w-12" />
              <span className="skeleton-bar h-4 w-20" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (auctionQuery.isError && !auctionQuery.data) {
    return <RequestError message="Unable to load auction." onRetry={() => { void auctionQuery.refetch(); }} />;
  }

  if (!auctionQuery.data) {
    return <EmptyState title="Auction not found" description="The requested auction could not be loaded." />;
  }

  const auction = auctionQuery.data;
  const sellTokenCount = auction.from_tokens.length;
  const hasSingleSellToken = sellTokenCount === 1;

  return (
    <div className="space-y-4">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-meta text-tertiary">
        <Link to="/" className="inline-flex items-center gap-1.5 transition-colors hover:text-primary">
          <ArrowLeft className="h-3.5 w-3.5" strokeWidth={1.6} />
          Rounds
        </Link>
        <span className="text-faint">/</span>
        <span className="text-secondary">Auction</span>
      </nav>

      <section className="card px-4 py-4 md:px-5" aria-label="Auction">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <ChainIcon chainId={auction.chain_id} size="md" />
          <h1 className="m-0 text-heading font-normal text-primary [&_.identity-link]:text-heading">
            <AuctionAddressValue address={auction.address} chainId={auction.chain_id} width={8} showCowExplorerIcon />
          </h1>
          <AuctionVersionBadge version={auction.version} />
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-8 gap-y-3">
          {hasSingleSellToken && pairTokens ? (
            <InfoItem
              label="Pair"
              value={<TokenPairValue fromToken={pairTokens.fromToken} toToken={pairTokens.toToken} chainId={auction.chain_id} showCopy />}
            />
          ) : (
            <>
              <InfoItem label="Want token" value={<TokenValue token={auction.want_token} chainId={auction.chain_id} />} />
              <InfoItem
                label={`Sell tokens · ${sellTokenCount}`}
                value={
                  <SellTokensPreview
                    chainId={auction.chain_id}
                    tokens={auction.from_tokens}
                    expanded={showAllSellTokens}
                    onToggle={() => setShowAllSellTokens((value) => !value)}
                  />
                }
              />
            </>
          )}
          <InfoItem
            label="Receiver"
            value={<AddressValue address={auction.receiver} chainId={auction.chain_id} label={auction.receiver_name} />}
          />
          <InfoItem label="Min price" value={<span className="font-mono">{formatPrice(auction.parameters.minimum_price)}</span>} />
        </div>
      </section>

      <StatStrip label="Auction totals" count={5}>
        <Stat label="Rounds" value={formatCount(auction.activity.total_rounds)} />
        <Stat label="Takes" value={formatCount(auction.activity.total_takes)} />
        <Stat
          label="Volume"
          value={formatVolume(auction.activity.total_volume)}
          suffix={auction.want_token.symbol ?? undefined}
          note={auction.activity.paid_take_count < auction.activity.total_takes ? "partial" : null}
          title={auction.activity.paid_take_count < auction.activity.total_takes ? `Payment observed for ${auction.activity.paid_take_count} of ${auction.activity.total_takes} takes` : undefined}
        />
        <Stat label="Decay" value={auction.parameters.decay_percent ?? "—"} suffix={auction.parameters.update_interval ? `/ ${formatDuration(auction.parameters.update_interval)}` : undefined} />
        <Stat label="Duration" value={formatDuration(auction.parameters.auction_length)} />
      </StatStrip>

      <div className="space-y-2">
        <section className="card card-clip" aria-label="Rounds">
          <div className="card-title">
            <span>Rounds</span>
            <strong>{formatCount(auction.activity.total_rounds)}</strong>
          </div>
          {roundsQuery.isError && !roundsQuery.data && <RequestError message="Unable to load rounds." onRetry={() => { void roundsQuery.refetch(); }} />}
          {roundsQuery.isLoading ? (
            <div className="table-wrap">
              <table className="data-table">
                <tbody>
                  <SkeletonRows rows={8} widths={[110, 104, 60, 80, 24, 120, 120, 64, null]} classNames={[undefined, "col-md", "col-lo", "col-xl", "col-md num", undefined, "col-lo", "num", "open-cell"]} />
                </tbody>
              </table>
            </div>
          ) : roundsQuery.isError && !roundsQuery.data ? null : roundsQuery.data?.rounds.length ? (
            <AuctionRoundsTable
              rounds={roundsQuery.data.rounds}
              kickedDisplayMode={kickedDisplayMode}
              onToggleKickedDisplayMode={() => setKickedDisplayMode(toggleKickedDisplayMode)}
              progressDisplayMode={progressDisplayMode}
              onToggleProgressDisplayMode={() => setProgressDisplayMode((current) => toggleProgressDisplayMode(current))}
            />
          ) : (
            <EmptyState title="No rounds available" description="This auction does not have any indexed rounds yet." />
          )}
        </section>
        {roundsQuery.data ? (
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
        ) : null}
      </div>

      <section className="card card-clip" aria-label="Recent takes">
        <div className="card-title">
          <span className="inline-flex items-center gap-3">
            Recent takes
            {showPriceSourceSelector ? (
              <PriceSourceSelect value={selectedPriceSource} options={recentTakeOptions} onChange={setPriceSource} />
            ) : null}
          </span>
          <strong>{recentTakesQuery.data?.takes.length ?? "—"}</strong>
        </div>
        {selectedTakeNotice}
        {recentTakesQuery.isError && !recentTakesQuery.data && <RequestError message="Unable to load takes." onRetry={() => { void recentTakesQuery.refetch(); }} />}
        {recentTakesQuery.isLoading ? (
          <div className="table-wrap">
            <table className="data-table">
              <tbody>
                <SkeletonRows rows={6} widths={[28, 24, 80, 110, 110, 110, 60, 64, null]} classNames={[undefined, undefined, "col-lo", undefined, "col-md", undefined, "col-md num", "num", "open-cell"]} />
              </tbody>
            </table>
          </div>
        ) : recentTakesQuery.isError && !recentTakesQuery.data ? null : (
          <TableHoverScope>
            <AuctionTakesTable
              takes={recentTakesQuery.data?.takes || []}
              priceSource={selectedPriceSource}
              selectedOccurrenceKey={selectedTakeParam}
              selectedTake={selectedTake}
              isSelectedTakeLoading={selectedTakeQuery.isLoading}
              onOpenTake={(key) => setSelectedTake(selectedTakeParam === key ? undefined : key)}
            />
          </TableHoverScope>
        )}
      </section>
    </div>
  );
}

function formatVolume(value: string | null | undefined) {
  if (!value) {
    return "—";
  }
  return formatAmount(value);
}
