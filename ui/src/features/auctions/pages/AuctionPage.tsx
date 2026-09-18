import AuctionRoundsTable from "../components/AuctionRoundsTable";
import AuctionTakesTable from "../components/AuctionTakesTable";
import MetricCoverage from "../../../shared/ui/MetricCoverage";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../../../shared/api/client";
import { formatAmount, formatDuration, formatPrice, toggleKickedDisplayMode } from "../../../shared/lib/format";
import type { KickedDisplayMode } from "../../../shared/lib/format";
import { resolvePriceSource, shouldShowPriceSourceSelector } from "../../../shared/lib/pricingSource";
import { handleRowNavigation } from "../../../shared/lib/rowNavigation";
import { parseOccurrence, buildRoundPathWithSource, roundModalSourceFromLocation, withBackgroundLocation } from "../../../shared/lib/routes";
import AddressValue from "../../../shared/ui/AddressValue";
import AuctionAddressValue from "../../../shared/ui/AuctionAddressValue";
import AuctionVersionBadge from "../../../shared/ui/AuctionVersionBadge";
import ChainPill from "../../../shared/ui/ChainPill";
import EmptyState from "../../../shared/ui/EmptyState";
import RequestError from "../../../shared/ui/RequestError";
import Pagination from "../../../shared/ui/Pagination";
import Panel from "../../../shared/ui/Panel";
import PriceSourceSelect from "../../../shared/ui/PriceSourceSelect";
import { toggleProgressDisplayMode, type RoundProgressMiniMode } from "../../../shared/ui/RoundProgressMini";
import Skeleton from "../../../shared/ui/Skeleton";
import { TableHoverScope } from "../../../shared/ui/TableHoverContext";
import TokenPairValue from "../../../shared/ui/TokenPairValue";
import TokenValue from "../../../shared/ui/TokenValue";

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

  const takeNotFound = selectedTakeQuery.error instanceof ApiError && selectedTakeQuery.error.status === 404;
  const selectedTake = !takeNotFound && selectedTakeQuery.data?.auction.toLowerCase() === address?.toLowerCase() ? selectedTakeQuery.data : undefined;
  const selectedTakeNotice = !selectedTakeParam ? null : !selectedOccurrence ? <EmptyState title="Invalid take link" /> : takeNotFound || (selectedTakeQuery.isSuccess && !selectedTake) ? (
    <EmptyState title="Take not found" description="This occurrence is absent from the indexed auction." />
  ) : selectedTakeQuery.isError ? (
    <RequestError message={selectedTake ? "Could not refresh take. Showing previously loaded data." : "Unable to load take."} onRetry={() => { void selectedTakeQuery.refetch(); }} />
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
      <div className="space-y-4">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-[28rem] w-full" />
      </div>
    );
  }

  if (auctionQuery.isError && !auctionQuery.data) {
    return <RequestError message="Unable to load auction." onRetry={() => { void auctionQuery.refetch(); }} />;
  }

  if (!auctionQuery.data) {
    return <EmptyState title="Auction not found" description="The requested auction could not be loaded." />;
  }

  const sellTokenCount = auctionQuery.data.from_tokens.length;
  const hasSingleSellToken = sellTokenCount === 1;

  return (
    <div className="space-y-4">
      {auctionQuery.isError && <RequestError message="Could not refresh auction. Showing previously loaded data." onRetry={() => { void auctionQuery.refetch(); }} />}
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
        {roundsQuery.isError && <RequestError message={roundsQuery.data ? "Could not refresh rounds. Showing previously loaded data." : "Unable to load rounds."} onRetry={() => { void roundsQuery.refetch(); }} />}
        {roundsQuery.isLoading ? (
          <div className="space-y-2 p-3">
            {Array.from({ length: 8 }).map((_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        ) : roundsQuery.isError && !roundsQuery.data ? null : roundsQuery.data?.rounds.length ? (
          <AuctionRoundsTable
            rounds={roundsQuery.data.rounds}
            kickedDisplayMode={kickedDisplayMode}
            onToggleKickedDisplayMode={() =>
              setKickedDisplayMode(toggleKickedDisplayMode)
            }
            progressDisplayMode={progressDisplayMode}
            onToggleProgressDisplayMode={() =>
              setProgressDisplayMode((current) => toggleProgressDisplayMode(current))
            }
            onRoundClick={(event, round) =>
              handleRowNavigation(
                event,
                buildRoundPathWithSource(round.chain_id, round.auction_address, round.occurrence, roundModalSource),
                (to) => navigate(to, { state: withBackgroundLocation(location) }),
              )
            }
            onOpenRound={(round) =>
              navigate(
                buildRoundPathWithSource(round.chain_id, round.auction_address, round.occurrence, roundModalSource),
                { state: withBackgroundLocation(location) },
              )
            }
          />
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
            <div className="font-mono text-meta text-tertiary">{recentTakesQuery.data?.takes.length ?? "—"}</div>
          </div>
        </div>
        {selectedTakeNotice}
        {recentTakesQuery.isError && <RequestError message={recentTakesQuery.data ? "Could not refresh takes. Showing previously loaded data." : "Unable to load takes."} onRetry={() => { void recentTakesQuery.refetch(); }} />}
        {recentTakesQuery.isLoading ? (
          <div className="space-y-2 p-3">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-14 w-full" />
            ))}
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
