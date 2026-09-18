import type { ReactNode } from "react";
import { Check } from "lucide-react";

import { cn, formatAmount, formatCompactDateTime, formatDateTime, formatDuration, formatFullAmount, formatPrice, formatUsd } from "../../../shared/lib/format";
import type { RoundListItem, RoundLivePrice } from "../../../shared/types/api";
import AddressValue from "../../../shared/ui/AddressValue";
import InlineSpinner from "../../../shared/ui/InlineSpinner";
import Panel from "../../../shared/ui/Panel";
import TokenValue from "../../../shared/ui/TokenValue";

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

export default function RoundSettingsPanel({
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

