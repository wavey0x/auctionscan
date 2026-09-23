import { ApiError } from "../../../shared/api/client";
import { useRoundDetails } from "../useRoundDetails";
import { buildRoundPath, parseOccurrence, parseRoundId } from "../../../shared/lib/routes";
import MetricCoverage from "../../../shared/ui/MetricCoverage";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { X } from "lucide-react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { cn, formatAmount, formatDateTime, formatFullAmount, formatUsd, renderKickedValue, toggleKickedDisplayMode } from "../../../shared/lib/format";
import type { KickedDisplayMode } from "../../../shared/lib/format";
import { DEFAULT_PRICE_SOURCE, getRoundPricingBySource, resolvePriceSource, shouldShowPriceSourceSelector } from "../../../shared/lib/pricingSource";
import AuctionAddressValue from "../../../shared/ui/AuctionAddressValue";
import EmptyState from "../../../shared/ui/EmptyState";
import RequestError from "../../../shared/ui/RequestError";
import Panel from "../../../shared/ui/Panel";
import PnlValue from "../../../shared/ui/PnlValue";
import PriceSourceSelect from "../../../shared/ui/PriceSourceSelect";
import Skeleton from "../../../shared/ui/Skeleton";
import StackedListRow from "../../../shared/ui/StackedListRow";
import StatusBadge from "../../../shared/ui/StatusBadge";
import { TableHoverScope } from "../../../shared/ui/TableHoverContext";
import TokenValue from "../../../shared/ui/TokenValue";

import RoundSettingsPanel from "./RoundSettingsPanel";
import RoundTakesTable from "./RoundTakesTable";

function HeaderMetric({
  label,
  value,
  detail,
  valueClassName,
  detailClassName,
}: {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  valueClassName?: string;
  detailClassName?: string;
}) {
  return (
    <div className="min-w-0 space-y-1">
      <div className="metric-label">{label}</div>
      <div className={cn("min-w-0 font-mono text-data", valueClassName ?? "text-primary")}>{value}</div>
      {detail ? (
        <div className={cn("truncate font-mono text-[10px] leading-none text-tertiary", detailClassName)}>
          {detail}
        </div>
      ) : null}
    </div>
  );
}

function formatDisplayVersion(version?: string | null): string | null {
  if (!version) {
    return null;
  }

  return version.startsWith("v") ? version : `v${version}`;
}

function ModalCloseButton({
  onClose,
  autoFocus = false,
}: {
  onClose: () => void;
  autoFocus?: boolean;
}) {
  return (
    <button
      type="button"
      className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-divider-strong text-tertiary transition-colors hover:bg-surface hover:text-primary"
      aria-label="Close round detail"
      data-autofocus={autoFocus ? "true" : undefined}
      onClick={onClose}
    >
      <X className="h-4 w-4" strokeWidth={1.8} />
    </button>
  );
}

function LoadingSettingsRow({
  label,
  valueWidth,
  noteWidth,
}: {
  label: string;
  valueWidth: string;
  noteWidth?: string;
}) {
  return (
    <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-3 px-3 py-2 md:px-4">
      <div className="metric-label">{label}</div>
      <div className="flex min-w-0 items-center gap-1.5">
        <Skeleton className={cn("h-4", valueWidth)} />
        {noteWidth ? <Skeleton className={cn("h-2.5", noteWidth)} /> : null}
      </div>
    </div>
  );
}

function RoundSettingsLoadingPanel() {
  return (
    <Panel className="min-h-[16rem] overflow-hidden p-0">
      <div className="space-y-2 px-3 py-3 md:px-4">
        <div className="text-heading text-primary">Round Settings</div>
      </div>

      <div className="divide-y divide-divider-subtle border-t border-divider-subtle">
        <LoadingSettingsRow label="Lot" valueWidth="w-32 max-w-full" noteWidth="w-12" />
        <LoadingSettingsRow label="Start" valueWidth="w-20" />
        <LoadingSettingsRow label="Kick quote" valueWidth="w-20" />
        <LoadingSettingsRow label="Cutoff" valueWidth="w-40 max-w-full" />
        <LoadingSettingsRow label="Decay" valueWidth="w-24" />
        <LoadingSettingsRow label="Live" valueWidth="w-20" />
        <LoadingSettingsRow label="Execution" valueWidth="w-20" />
        <LoadingSettingsRow label="Receiver" valueWidth="w-40 max-w-full" />
      </div>
    </Panel>
  );
}

function TakesLoadingPanel() {
  return (
    <Panel className="space-y-3 min-h-[12rem]" padded={false}>
      <div className="px-3 pt-3 md:px-4">
        <div className="text-heading text-primary">Takes</div>
      </div>

      <div className="md:hidden">
        {Array.from({ length: 3 }).map((_, index) => (
          <StackedListRow key={`take-loading-mobile-${index}`} className="space-y-2">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-2">
                <Skeleton className="h-4 w-8" />
                <Skeleton className="h-4 w-20" />
              </div>
              <Skeleton className="h-3 w-14" />
            </div>
            <Skeleton className="h-4 w-32 max-w-full" />
            <div className="space-y-1.5">
              <div className="flex items-center gap-1.5">
                <Skeleton className="h-3 w-7" />
                <Skeleton className="h-4 w-36 max-w-full" />
              </div>
              <div className="flex items-center gap-1.5">
                <Skeleton className="h-3 w-8" />
                <Skeleton className="h-4 w-40 max-w-full" />
              </div>
            </div>
          </StackedListRow>
        ))}
      </div>

      <div className="hidden md:block table-wrap">
        <TableHoverScope>
          <table className="data-table">
            <thead>
              <tr>
                <th>Take</th>
                <th>Tx</th>
                <th>Taker</th>
                <th>Time</th>
                <th>Sold</th>
                <th>Received</th>
                <th>Price</th>
                <th>PnL</th>
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 4 }).map((_, index) => (
                <tr key={`take-loading-desktop-${index}`}>
                  <td><Skeleton className="h-4 w-6" /></td>
                  <td><Skeleton className="h-4 w-20" /></td>
                  <td><Skeleton className="h-4 w-24" /></td>
                  <td><Skeleton className="h-4 w-14" /></td>
                  <td><Skeleton className="h-4 w-28" /></td>
                  <td><Skeleton className="h-4 w-32" /></td>
                  <td><Skeleton className="ml-auto h-4 w-14" /></td>
                  <td><Skeleton className="h-4 w-12" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableHoverScope>
      </div>
    </Panel>
  );
}

function RoundModalLoadingState({ onClose }: { onClose: () => void }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="sticky top-0 z-10 border-b border-divider-strong bg-background/95 px-3 pb-3 pt-2 backdrop-blur-sm md:px-4">
        <div className="relative space-y-2 pr-10">
          <div className="absolute right-0 top-0">
            <ModalCloseButton onClose={onClose} autoFocus />
          </div>
          <div className="grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
            <HeaderMetric
              label="Auction"
              value={<Skeleton className="h-4 w-24" />}
              detail={<Skeleton className="h-2.5 w-10" />}
            />
            <HeaderMetric
              label="Round"
              value={
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Skeleton className="h-4 w-8" />
                    <Skeleton className="h-5 w-14 rounded-[4px]" />
                  </div>
                  <Skeleton className="h-2.5 w-16" />
                </div>
              }
            />
            <HeaderMetric
              label="Total Sold / Received"
              value={
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1.5">
                    <Skeleton className="h-4 w-32 max-w-full" />
                    <Skeleton className="h-2.5 w-12" />
                  </div>
                  <div className="flex items-center gap-1.5">
                    <Skeleton className="h-4 w-36 max-w-full" />
                    <Skeleton className="h-2.5 w-12" />
                  </div>
                </div>
              }
            />
            <HeaderMetric
              label="PnL"
              value={<Skeleton className="h-4 w-12" />}
              detail={<Skeleton className="h-2.5 w-10" />}
            />
          </div>
        </div>
      </div>

      <div data-round-modal-scroll-root="true" className="min-h-0 flex-1 overflow-y-auto overscroll-y-contain p-3 md:p-4">
        <div className="min-h-[29rem] space-y-4 md:min-h-[31rem]">
          <RoundSettingsLoadingPanel />
          <TakesLoadingPanel />
        </div>
      </div>
    </div>
  );
}

export default function RoundModalContent({
  onClose,
}: {
  onClose: () => void;
}) {
  const { chainId, auctionAddress, roundId: roundIdParam } = useParams<{
    chainId: string;
    auctionAddress: string;
    roundId: string;
  }>();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [kickedDisplayMode, setKickedDisplayMode] = useState<KickedDisplayMode>("absolute");

  const chain = Number(chainId);
  const roundId = parseRoundId(roundIdParam);
  const validRound = Number.isSafeInteger(chain) && chain > 0 && roundId !== null && !!auctionAddress;
  const selectedTakeParam = searchParams.get("take");
  const requestedPriceSource = searchParams.get("priceSource");
  const selectedOccurrence = parseOccurrence(chain, selectedTakeParam);
  const {
    roundQuery,
    auctionQuery,
    takesQuery,
    selectedTakeQuery,
    livePriceQuery,
    round,
    selectedTake,
    roundNotFound,
    selectedTakeNotFound,
    priceReference,
    displayedLivePrice,
  } = useRoundDetails(chain, auctionAddress, roundId, selectedOccurrence);

  useEffect(() => {
    const take = selectedTakeQuery.isError ? undefined : selectedTakeQuery.data;
    if (!take || !validRound || (take.round_id === roundId && take.auction.toLowerCase() === auctionAddress?.toLowerCase())) return;
    // The transfer remains the identity even if corrected inference moves it to another round.
    navigate({ pathname: buildRoundPath(chain, take.auction, take.round_id), search: location.search }, { replace: true, state: location.state });
  }, [selectedTakeQuery.data, selectedTakeQuery.isError, roundId, auctionAddress, validRound, chain, location.search, location.state, navigate]);

  const replaceModalSearchParams = (next: URLSearchParams) => {
    setSearchParams(next, { replace: true, state: location.state });
  };

  const setSelectedTake = (key?: string) => {
    const next = new URLSearchParams(searchParams);
    if (!key) {
      next.delete("take");
    } else {
      next.set("take", key);
    }
    replaceModalSearchParams(next);
  };

  const setPriceSource = (sourceId: string) => {
    const next = new URLSearchParams(searchParams);
    if (sourceId === DEFAULT_PRICE_SOURCE) {
      next.delete("priceSource");
    } else {
      next.set("priceSource", sourceId);
    }
    replaceModalSearchParams(next);
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }

      event.preventDefault();
      if (selectedTakeParam) {
        setSelectedTake(undefined);
        return;
      }

      onClose();
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, searchParams, selectedTakeParam, setSearchParams]);

  const takesNotFound = takesQuery.error instanceof ApiError && takesQuery.error.status === 404;
  const takes = takesNotFound ? [] : takesQuery.data?.takes || [];
  const selectedTakeNotice = !selectedTakeParam ? null : !selectedOccurrence ? (
    <EmptyState title="Invalid take link" />
  ) : selectedTakeNotFound || (selectedTakeQuery.isSuccess && !selectedTake) ? (
    <EmptyState title="Take not found" description="This occurrence is absent from the indexed round." />
  ) : selectedTakeQuery.isError ? (
    <RequestError message={selectedTake ? "Could not refresh take. Showing previously loaded data." : "Unable to load take."} onRetry={() => { void selectedTakeQuery.refetch(); }} />
  ) : null;
  const sourceOptions = takesQuery.data?.available_price_sources || [];
  const selectedPriceSource = resolvePriceSource(requestedPriceSource, sourceOptions);
  const showPriceSourceSelector = shouldShowPriceSourceSelector(sourceOptions);

  useEffect(() => {
    if (!sourceOptions.length) {
      return;
    }
    const normalized = requestedPriceSource?.trim().toLowerCase() || DEFAULT_PRICE_SOURCE;
    if (normalized === selectedPriceSource) {
      return;
    }
    setPriceSource(selectedPriceSource);
  }, [requestedPriceSource, selectedPriceSource, sourceOptions.length]);

  if (validRound && roundQuery.isLoading) {
    return <RoundModalLoadingState onClose={onClose} />;
  }

  if (!round) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-divider-strong bg-background/95 px-3 py-3 backdrop-blur-sm md:px-4">
          <div className="text-heading text-primary">Round detail</div>
          <ModalCloseButton onClose={onClose} autoFocus />
        </div>
        <div data-round-modal-scroll-root="true" className="flex-1 overflow-y-auto overscroll-y-contain p-3 md:p-4">
          {!validRound ? <EmptyState title="Invalid round link" /> : roundQuery.isError && !roundNotFound ? (
            <RequestError message="Unable to load round." onRetry={() => { void roundQuery.refetch(); }} />
          ) : <EmptyState title="Round not found" description="This round is absent from the indexed auction." />}
        </div>
      </div>
    );
  }

  const roundPricing = getRoundPricingBySource(round, selectedPriceSource);
  const soldUsd = roundPricing.total_market_quote_usd ? `~${formatUsd(roundPricing.total_market_quote_usd)}` : "—";
  const receivedUsd = round.total_actual_paid_usd ? formatUsd(round.total_actual_paid_usd) : "—";
  const displayVersion = formatDisplayVersion(round.version ?? auctionQuery.data?.version);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="sticky top-0 z-10 border-b border-divider-strong bg-background/95 px-3 pb-3 pt-2 backdrop-blur-sm md:px-4">
        <div className="relative space-y-2 pr-10">
          <div className="absolute right-0 top-0">
            <ModalCloseButton onClose={onClose} autoFocus />
          </div>
          <div className="grid gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
            <HeaderMetric
              label="Auction"
              value={<AuctionAddressValue address={round.auction_address} chainId={round.chain_id} showCowExplorerIcon />}
              detail={displayVersion}
            />
            <HeaderMetric
              label="Round"
              value={
                <div className="space-y-1">
                  <span className="inline-flex items-center gap-2">
                    <span>R{round.round_id}</span>
                    <StatusBadge status={round.status} />
                  </span>
                  <button
                    type="button"
                    className="block font-mono text-[10px] leading-none text-tertiary underline-offset-4 transition-colors hover:text-secondary hover:underline"
                    title={formatDateTime(round.kicked_at)}
                    onClick={() =>
                      setKickedDisplayMode(toggleKickedDisplayMode)
                    }
                  >
                    {renderKickedValue(round.kicked_at, kickedDisplayMode)}
                  </button>
                </div>
              }
            />
            <HeaderMetric
              label="Total Sold / Received"
              detail={<span className="flex gap-2"><MetricCoverage count={round.paid_take_count} total={round.take_count} label="paid" /><MetricCoverage count={round.paid_usd_take_count} total={round.take_count} label="USD" /></span>}
              value={
                <div className="space-y-1.5">
                  <div className="flex min-w-0 items-center gap-1.5">
                    <TokenValue
                      address={round.from_token}
                      symbol={[formatAmount(round.sold_amount), round.from_token_symbol].filter(Boolean).join(" ").trim() || "—"}
                      logoUrl={round.from_token_logo_url}
                      chainId={round.chain_id}
                      className="min-w-0"
                      showCopy={false}
                      tooltip={[formatFullAmount(round.sold_amount), round.from_token_symbol].filter(Boolean).join(" ").trim() || null}
                    />
                    <span className="shrink-0 font-mono text-[10px] leading-none text-tertiary">{soldUsd}<MetricCoverage count={roundPricing.usd_priced_take_count} total={round.take_count} /></span>
                  </div>
                  <div className="flex min-w-0 items-center gap-1.5">
                    <TokenValue
                      address={round.want_token}
                      symbol={[formatAmount(round.paid_amount), round.want_token_symbol].filter(Boolean).join(" ").trim() || "—"}
                      logoUrl={round.want_token_logo_url}
                      chainId={round.chain_id}
                      className="min-w-0"
                      showCopy={false}
                      tooltip={[formatFullAmount(round.paid_amount), round.want_token_symbol].filter(Boolean).join(" ").trim() || null}
                    />
                    <span className="shrink-0 font-mono text-[10px] leading-none text-tertiary">{receivedUsd}</span>
                  </div>
                </div>
              }
            />
            <HeaderMetric
              label="PnL"
              value={<PnlValue percent={roundPricing.total_auction_profit_bps} usd={roundPricing.total_auction_profit_usd} />}
              detail={<span className="flex gap-2"><MetricCoverage count={roundPricing.priced_take_count} total={round.take_count} label="quoted" /><MetricCoverage count={roundPricing.usd_priced_take_count} total={round.take_count} label="USD" /></span>}
            />
          </div>
        </div>
      </div>

      <div data-round-modal-scroll-root="true" className="min-h-0 flex-1 overflow-y-auto overscroll-y-contain p-3 md:p-4">
        <div className="space-y-4">
          {roundQuery.isError && <RequestError message="Could not refresh round. Showing previously loaded data." onRetry={() => { void roundQuery.refetch(); }} />}
          {auctionQuery.isError && <RequestError message={auctionQuery.data ? "Could not refresh auction. Showing previously loaded data." : "Unable to load auction details."} onRetry={() => { void auctionQuery.refetch(); }} />}
          {auctionQuery.isSuccess && auctionQuery.data === null && <EmptyState title="Auction not found" />}
          <RoundSettingsPanel
            round={round}
            chainId={chain}
            startingPricePerUnit={round.starting_price_per_unit}
            minimumPrice={round.minimum_price}
            duration={round.auction_length}
            stepDuration={round.update_interval}
            decay={round.decay_percent}
            livePrice={displayedLivePrice}
            isLivePriceLoading={livePriceQuery.isLoading}
            isLivePriceError={roundQuery.isError || livePriceQuery.isError || !priceReference}
            livePriceError={livePriceQuery.error}
          />

          <Panel className="space-y-3" padded={false}>
            <div className="flex items-center justify-between gap-3 px-3 pt-3 md:px-4">
              <div className="text-heading text-primary">Takes</div>
              {showPriceSourceSelector ? (
                <PriceSourceSelect
                  value={selectedPriceSource}
                  options={sourceOptions}
                  onChange={setPriceSource}
                />
              ) : null}
            </div>
            {selectedTakeNotice}
            {takesNotFound ? <EmptyState title="Round not found" description="Takes are unavailable for this occurrence." /> : takesQuery.isError ? <RequestError message={takesQuery.data ? "Could not refresh takes. Showing previously loaded data." : "Unable to load takes."} onRetry={() => { void takesQuery.refetch(); }} /> : null}
            {takesQuery.isLoading ? <div className="p-3"><Skeleton className="h-32 w-full" /></div> : takesNotFound || (takesQuery.isError && !takesQuery.data) ? null : <RoundTakesTable
              takes={takes}
              priceSource={selectedPriceSource}
              selectedOccurrenceKey={selectedTakeParam}
              selectedTake={selectedTake}
              isSelectedTakeLoading={selectedTakeQuery.isLoading}
              onSelect={(key) => setSelectedTake(selectedTakeParam === key ? undefined : key)}
            />}
          </Panel>
        </div>
      </div>
    </div>
  );
}
