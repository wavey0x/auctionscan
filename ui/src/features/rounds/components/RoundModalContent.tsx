import { buildRoundPath, occurrenceKey, parseOccurrence } from "../../../shared/lib/routes";
import MetricCoverage from "../../../shared/ui/MetricCoverage";
import { Fragment, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError, api } from "../../../shared/api/client";
import {
  cn,
  formatAmount,
  formatCompactDateTime,
  formatDateTime,
  formatDuration,
  formatFullAmount,
  formatPrice,
  formatUsd,
  renderKickedValue,
  toggleKickedDisplayMode,
} from "../../../shared/lib/format";
import type { KickedDisplayMode } from "../../../shared/lib/format";
import { DEFAULT_PRICE_SOURCE, getRoundPricingBySource, getTakePricingBySource, resolvePriceSource, shouldShowPriceSourceSelector } from "../../../shared/lib/pricingSource";
import type { RoundListItem, RoundLivePrice, TakeListItem } from "../../../shared/types/api";
import AddressValue from "../../../shared/ui/AddressValue";
import AuctionAddressValue from "../../../shared/ui/AuctionAddressValue";
import EmptyState from "../../../shared/ui/EmptyState";
import InlineSpinner from "../../../shared/ui/InlineSpinner";
import Panel from "../../../shared/ui/Panel";
import PnlValue from "../../../shared/ui/PnlValue";
import PriceSourceSelect from "../../../shared/ui/PriceSourceSelect";
import Skeleton from "../../../shared/ui/Skeleton";
import StackedListRow from "../../../shared/ui/StackedListRow";
import StatusBadge from "../../../shared/ui/StatusBadge";
import TakeExpandedContent from "../../../shared/ui/TakeExpandedContent";
import TakeExpandedRow from "../../../shared/ui/TakeExpandedRow";
import TakerAddressValue from "../../../shared/ui/TakerAddressValue";
import { TableHoverScope } from "../../../shared/ui/TableHoverContext";
import TokenAmountValue from "../../../shared/ui/TokenAmountValue";
import TokenValue from "../../../shared/ui/TokenValue";
import TxHashValue from "../../../shared/ui/TxHashValue";

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

function livePriceErrorMessage(error: unknown): string | null {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string" && error.trim()) {
    return error;
  }
  return null;
}

function PriceStatusMarker() {
  return (
    <span className="progress-marker flex h-[10px] w-[10px] items-center justify-center rounded-full border text-white shadow-sm">
      <Check className="h-[7px] w-[7px]" strokeWidth={2.5} />
    </span>
  );
}

function PriceValue({
  children,
  className,
  title,
}: {
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      className={cn("inline-flex min-w-0 items-center gap-2 font-mono text-data", className)}
      title={title}
    >
      {children}
    </span>
  );
}

function LiveLabelMarker() {
  return (
    <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.24)]" />
  );
}

function RoundSettingsPanel({
  round,
  chainId,
  startingPricePerUnit,
  minimumPrice,
  duration,
  stepDuration,
  decay,
  livePrice,
  isLivePriceLoading,
  isLivePriceError,
  livePriceError,
}: {
  round: RoundListItem;
  chainId: number;
  startingPricePerUnit?: string | null;
  minimumPrice?: string | null;
  duration?: number | null;
  stepDuration?: number | null;
  decay?: string | null;
  livePrice?: RoundLivePrice;
  isLivePriceLoading: boolean;
  isLivePriceError: boolean;
  livePriceError?: unknown;
}) {
  const livePriceValue = livePrice?.current_price ? formatPrice(livePrice.current_price, 8) : null;
  const livePriceErrorDetail = livePriceErrorMessage(livePriceError);
  const showLivePrice = round.is_active && livePrice?.is_active !== false && Boolean(livePriceValue);
  const livePriceTitle = livePrice
    ? `Price at indexed block ${livePrice.indexed_block} · ${formatDateTime(new Date(livePrice.indexed_timestamp * 1000).toISOString())}`
    : "Price at the displayed indexed block";
  const executionPriceValue = round.avg_execution_price ? formatPrice(round.avg_execution_price, 8) : null;
  const showExecutionPriceRow = !round.is_active && round.take_count > 0;
  const showMinimumPrice = minimumPrice !== null && minimumPrice !== undefined;
  const showDuration = duration !== null && duration !== undefined;
  const expectedPriceValue = round.expected_price_per_unit ? formatPrice(round.expected_price_per_unit, 8) : null;
  const lotUsd = round.kick_market_quote_usd ?? round.total_market_quote_usd;
  const lotAmount = round.initial_available ?? round.sold_amount;
  const lotAmountLabel = [formatAmount(lotAmount), round.from_token_symbol].filter(Boolean).join(" ").trim() || "—";
  const lotAmountTooltip = [formatFullAmount(lotAmount), round.from_token_symbol].filter(Boolean).join(" ").trim() || null;

  return (
    <Panel className="overflow-hidden p-0">
      <div className="space-y-2 px-3 py-3 md:px-4">
        <div className="text-heading text-primary">Round Settings</div>
      </div>

      <div className="divide-y divide-divider-subtle border-t border-divider-subtle">
        <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-3 px-3 py-2 md:px-4">
          <div className="metric-label">Lot</div>
          <div className="flex min-w-0 items-center gap-1.5">
            <TokenValue
              address={round.from_token}
              symbol={lotAmountLabel}
              logoUrl={round.from_token_logo_url}
              chainId={round.chain_id}
              className="min-w-0"
              showCopy={false}
              tooltip={lotAmountTooltip}
            />
            <span className="shrink-0 font-mono text-[10px] leading-none text-tertiary">
              {lotUsd ? `~${formatUsd(lotUsd)}` : "—"}
            </span>
          </div>
        </div>

        <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-3 px-3 py-2 md:px-4">
          <div className="metric-label">Start</div>
          <PriceValue className={startingPricePerUnit ? "text-primary" : "text-tertiary"} title="Start price per unit">
            {startingPricePerUnit ? formatPrice(startingPricePerUnit, 8) : "—"}
          </PriceValue>
        </div>

        <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-3 px-3 py-2 md:px-4">
          <div className="metric-label">Kick quote</div>
          <PriceValue className={expectedPriceValue ? "text-primary" : "text-tertiary"} title="Stored kick-time quote per unit">
            {expectedPriceValue ?? "—"}
          </PriceValue>
        </div>

        <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-3 px-3 py-2 md:px-4">
          <div className="metric-label">Cutoff</div>
          <div className={cn("font-mono text-data", showMinimumPrice || showDuration ? "text-primary" : "text-tertiary")}>
            {showMinimumPrice ? `< ${formatPrice(minimumPrice, 8)}` : null}
            {showMinimumPrice && showDuration ? <span className="text-tertiary"> or </span> : null}
            {showDuration ? <span className={showMinimumPrice ? "text-tertiary" : undefined}>{`after ${formatDuration(duration)}`}</span> : null}
            {!showMinimumPrice && !showDuration ? "—" : null}
          </div>
        </div>

        <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-3 px-3 py-2 md:px-4">
          <div className="metric-label">Decay</div>
          <div className="font-mono text-data text-primary">
            {decay ?? "—"}
            {decay && stepDuration !== null && stepDuration !== undefined ? (
              <span className="text-tertiary">{` / ${formatDuration(stepDuration)}`}</span>
            ) : null}
          </div>
        </div>

        {round.is_active ? (
          <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-3 px-3 py-2 md:px-4">
            <div className="metric-label inline-flex items-center gap-1.5">
              <LiveLabelMarker />
              <span>Live</span>
            </div>
            <PriceValue className={showLivePrice ? "text-primary" : "text-tertiary"} title={livePriceTitle}>
              {showLivePrice ? (
                <span>{livePriceValue}<span className="ml-2 text-[10px] text-tertiary">{formatCompactDateTime(new Date(livePrice!.indexed_timestamp * 1000).toISOString())}</span></span>
              ) : isLivePriceError ? (
                <span title={livePriceErrorDetail ?? undefined}>unavailable</span>
              ) : isLivePriceLoading ? (
                <InlineSpinner />
              ) : (
                "—"
              )}
            </PriceValue>
          </div>
        ) : null}

        {showExecutionPriceRow ? (
          <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-3 px-3 py-2 md:px-4">
            <div className="metric-label">Execution</div>
            <PriceValue className={executionPriceValue ? "text-primary" : "text-tertiary"} title={`Average execution price from ${round.paid_take_count}/${round.take_count} takes with observed payment`}>
              {executionPriceValue ? (
                <span className="inline-flex items-center gap-2">
                  <span>{executionPriceValue}</span>
                  <PriceStatusMarker />
                </span>
              ) : "—"}
            </PriceValue>
          </div>
        ) : null}

        <div className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-3 px-3 py-2 md:px-4">
          <div className="metric-label">Receiver</div>
          <div className="min-w-0">
            <AddressValue address={round.receiver} chainId={chainId} label={round.receiver_name} />
          </div>
        </div>
      </div>
    </Panel>
  );
}

function TakeTable({
  takes,
  priceSource,
  selectedOccurrenceKey,
  selectedTake,
  isSelectedTakeLoading,
  onSelect,
}: {
  takes: TakeListItem[];
  priceSource: string;
  selectedOccurrenceKey?: string | null;
  selectedTake?: Awaited<ReturnType<typeof api.getTake>>;
  isSelectedTakeLoading: boolean;
  onSelect: (key: string) => void;
}) {
  if (!takes.length) {
    return (
      <div className="p-3">
        <EmptyState title="No takes in this round" titleClassName="text-tertiary" />
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
              onClick={() => onSelect(occurrenceKey(take.occurrence))}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-primary">T{take.take_seq}</span>
                  <TxHashValue txHash={take.tx_hash} chainId={take.chain_id} width={6} />
                </div>
                <div className="font-mono text-meta text-tertiary" title={formatDateTime(take.timestamp)}>
                  {formatCompactDateTime(take.timestamp)}
                </div>
              </div>
              <div className="min-w-0">
                <TakerAddressValue address={take.taker} chainId={take.chain_id} />
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
                    <span className="metric-label shrink-0">Recv</span>
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
              {takes.map((take) => {
                const isSelected = occurrenceKey(take.occurrence) === selectedOccurrenceKey;
                const takePricing = getTakePricingBySource(take, priceSource);

                return (
                  <Fragment key={`${take.chain_id}:${occurrenceKey(take.occurrence)}`}>
                    <tr
                      className={`data-row ${isSelected ? "bg-surface" : ""}`}
                      onClick={() => onSelect(occurrenceKey(take.occurrence))}
                    >
                      <td className="font-mono text-primary">T{take.take_seq}</td>
                      <td>
                        <TxHashValue txHash={take.tx_hash} chainId={take.chain_id} width={6} />
                      </td>
                      <td>
                        <TakerAddressValue address={take.taker} chainId={take.chain_id} />
                      </td>
                      <td className="font-mono text-primary" title={formatDateTime(take.timestamp)}>
                        {formatCompactDateTime(take.timestamp)}
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
        </TableHoverScope>
      </div>
    </>
  );
}

export default function RoundModalContent({
  onClose,
}: {
  onClose: () => void;
}) {
  const { chainId, auctionAddress, occurrence: occurrenceParam } = useParams<{
    chainId: string;
    auctionAddress: string;
    occurrence: string;
  }>();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [kickedDisplayMode, setKickedDisplayMode] = useState<KickedDisplayMode>("absolute");

  const chain = Number(chainId);
  const occurrence = parseOccurrence(chain, occurrenceParam);
  const selectedTakeParam = searchParams.get("take");
  const requestedPriceSource = searchParams.get("priceSource");
  const selectedOccurrence = parseOccurrence(chain, selectedTakeParam);
  const mismatchRetryAfter = useRef(0);

  const roundQuery = useQuery({
    queryKey: ["round-detail", occurrence],
    queryFn: ({ signal }) => api.getRoundDetail(occurrence!, signal),
    enabled: Boolean(occurrence) && !!auctionAddress,
  });

  const auctionQuery = useQuery({
    queryKey: ["auction", chain, auctionAddress],
    queryFn: ({ signal }) => api.getAuction(chain, auctionAddress!, signal),
    enabled: Number.isFinite(chain) && !!auctionAddress,
  });

  const takesQuery = useQuery({
    queryKey: ["round-takes", occurrence],
    queryFn: ({ signal }) => api.getAuctionTakes(chain, auctionAddress!, occurrence!, 200, signal),
    enabled: Boolean(occurrence) && !!auctionAddress,
  });

  const selectedTakeQuery = useQuery({
    queryKey: ["take-detail", selectedOccurrence],
    queryFn: ({ signal }) => api.getTake(selectedOccurrence!, signal),
    enabled: Boolean(occurrence && selectedOccurrence),
  });

  useEffect(() => {
    const take = selectedTakeQuery.isError ? undefined : selectedTakeQuery.data;
    if (!take || !occurrence || occurrenceKey(take.round_occurrence) === occurrenceKey(occurrence)) return;
    // The transfer remains the identity even if corrected inference moves it to another round.
    navigate({ pathname: buildRoundPath(chain, take.auction, take.round_occurrence), search: location.search }, { replace: true, state: location.state });
  }, [selectedTakeQuery.data, selectedTakeQuery.isError, occurrenceParam, chain, location.search, location.state, navigate]);

  const round = !roundQuery.isError && roundQuery.data && roundQuery.data.round.auction_address.toLowerCase() === auctionAddress?.toLowerCase() ? roundQuery.data.round : undefined;
  const selectedTake = !selectedTakeQuery.isError && selectedTakeQuery.data && occurrence && occurrenceKey(selectedTakeQuery.data.round_occurrence) === occurrenceKey(occurrence) ? selectedTakeQuery.data : undefined;
  const checkpoint = roundQuery.data?.as_of[chain];
  const priceReference = checkpoint?.indexed_block != null && checkpoint.indexed_block_hash && checkpoint.indexed_timestamp != null
    ? { indexed_block: checkpoint.indexed_block, indexed_block_hash: checkpoint.indexed_block_hash, indexed_timestamp: checkpoint.indexed_timestamp }
    : null;
  const livePriceQuery = useQuery({
    queryKey: ["round-live-price", occurrence, priceReference],
    queryFn: async ({ signal }) => {
      try {
        return await api.getRoundLivePrice(occurrence!, priceReference!, signal);
      } catch (error) {
        if (error instanceof ApiError && error.status === 409 && Date.now() >= mismatchRetryAfter.current) {
          // Refresh once. The new snapshot key triggers the retry; further mismatches
          // wait for normal polling instead of recursively refreshing during catch-up.
          mismatchRetryAfter.current = Date.now() + 3_000;
          await roundQuery.refetch();
        }
        throw error;
      }
    },
    enabled: Boolean(occurrence && priceReference && round?.is_active),
    retry: false,
    refetchInterval: 3_000,
    refetchIntervalInBackground: false,
  });
  const price = livePriceQuery.isError ? undefined : livePriceQuery.data;
  const displayedLivePrice = price && priceReference && occurrence
    && price.indexed_block_hash === priceReference.indexed_block_hash
    && price.indexed_block === priceReference.indexed_block
    && price.indexed_timestamp === priceReference.indexed_timestamp
    && occurrenceKey(price.occurrence) === occurrenceKey(occurrence)
    ? price : undefined;

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

  const takes = takesQuery.isError ? [] : takesQuery.data?.takes || [];
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

  if (occurrence && (roundQuery.isLoading || auctionQuery.isLoading || takesQuery.isLoading)) {
    return <RoundModalLoadingState onClose={onClose} />;
  }

  if (!round || !auctionQuery.data) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-divider-strong bg-background/95 px-3 py-3 backdrop-blur-sm md:px-4">
          <div className="text-heading text-primary">Round detail</div>
          <ModalCloseButton onClose={onClose} autoFocus />
        </div>
        <div data-round-modal-scroll-root="true" className="flex-1 overflow-y-auto overscroll-y-contain p-3 md:p-4">
          <EmptyState title="Round not found" description="The requested round could not be built from indexed data." />
        </div>
      </div>
    );
  }

  const roundPricing = getRoundPricingBySource(round, selectedPriceSource);
  const soldUsd = roundPricing.total_market_quote_usd ? `~${formatUsd(roundPricing.total_market_quote_usd)}` : "—";
  const receivedUsd = round.total_actual_paid_usd ? formatUsd(round.total_actual_paid_usd) : "—";
  const displayVersion = formatDisplayVersion(round.version ?? auctionQuery.data.version);

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
              value={<AuctionAddressValue address={auctionQuery.data.address} chainId={round.chain_id} showCowExplorerIcon />}
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
            isLivePriceError={livePriceQuery.isError || !priceReference}
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
            {selectedTakeParam && !selectedTakeQuery.isFetching && !selectedTake ? <EmptyState title="Take unavailable" description="This occurrence is absent from the indexed round." /> : null}
            <TakeTable
              takes={takes}
              priceSource={selectedPriceSource}
              selectedOccurrenceKey={selectedTakeParam}
              selectedTake={selectedTake}
              isSelectedTakeLoading={selectedTakeQuery.isLoading}
              onSelect={(key) => setSelectedTake(selectedTakeParam === key ? undefined : key)}
            />
          </Panel>
        </div>
      </div>
    </div>
  );
}
