import type { CSSProperties, ReactNode } from "react";

import { cn, formatCompactDateTime, formatDateTime, formatDuration, formatPrice } from "../../../shared/lib/format";
import type { RoundListItem, RoundLivePrice } from "../../../shared/types/api";
import AddressValue from "../../../shared/ui/AddressValue";
import InlineSpinner from "../../../shared/ui/InlineSpinner";

function livePriceErrorMessage(error: unknown): string | null {
  if (error instanceof Error) {
    return error.message;
  }
  if (typeof error === "string" && error.trim()) {
    return error;
  }
  return null;
}

function Row({ label, children, title }: { label: ReactNode; children: ReactNode; title?: string }) {
  return (
    <div className="kv reveal-row" title={title}>
      <span>{label}</span>
      <span className="truncate">{children}</span>
    </div>
  );
}

/** The kick-time settings of a round, as captured facts, and its live or executed price. */
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

  return (
    <div>
      {round.is_active ? (
        <Row
          title={livePriceTitle}
          label={
            <span className="inline-flex items-center gap-2">
              <span className="status-dot is-live" style={{ "--tone": "var(--color-active-mark)" } as CSSProperties} aria-hidden="true" />
              Live
            </span>
          }
        >
          {showLivePrice ? (
            <span>
              {livePriceValue}
              <span className="ml-2 text-[11px] text-tertiary">{formatCompactDateTime(new Date(livePrice!.indexed_timestamp * 1000).toISOString())}</span>
            </span>
          ) : isLivePriceError ? (
            <span className="text-tertiary" title={livePriceErrorDetail ?? undefined}>unavailable</span>
          ) : isLivePriceLoading ? (
            <InlineSpinner />
          ) : (
            <span className="text-faint">—</span>
          )}
        </Row>
      ) : null}

      {showExecutionPriceRow ? (
        <Row
          label="Execution"
          title={`Average execution price from ${round.paid_take_count}/${round.take_count} takes with observed payment`}
        >
          {executionPriceValue ?? <span className="text-faint">—</span>}
        </Row>
      ) : null}

      <Row label="Start" title="Start price per unit">
        <span className={startingPricePerUnit ? undefined : "text-faint"}>{startingPricePerUnit ? formatPrice(startingPricePerUnit, 8) : "—"}</span>
      </Row>

      <Row label="Kick quote" title="Stored kick-time market quote per unit">
        <span className={expectedPriceValue ? undefined : "text-faint"}>{expectedPriceValue ?? "—"}</span>
      </Row>

      <Row label="Decay">
        {decay ?? <span className="text-faint">—</span>}
        {decay && stepDuration !== null && stepDuration !== undefined ? (
          <span className="text-tertiary">{` every ${formatDuration(stepDuration)}`}</span>
        ) : null}
      </Row>

      <Row label="Cutoff">
        <span className={cn(!showMinimumPrice && !showDuration && "text-faint")}>
          {showMinimumPrice ? `below ${formatPrice(minimumPrice, 8)}` : null}
          {showMinimumPrice && showDuration ? <span className="text-tertiary"> or </span> : null}
          {showDuration ? <span className={showMinimumPrice ? "text-tertiary" : undefined}>{`after ${formatDuration(duration)}`}</span> : null}
          {!showMinimumPrice && !showDuration ? "—" : null}
        </span>
      </Row>

      <div className="kv reveal-row">
        <span>Receiver</span>
        <span className="min-w-0 font-sans">
          <AddressValue address={round.receiver} chainId={chainId} label={round.receiver_name} />
        </span>
      </div>
    </div>
  );
}
