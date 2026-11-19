import type { ReactNode } from "react";

import { cn, formatDuration, formatPrice } from "../../../shared/lib/format";
import type { RoundListItem } from "../../../shared/types/api";
import AddressValue from "../../../shared/ui/AddressValue";

function Row({ label, children, title }: { label: ReactNode; children: ReactNode; title?: string }) {
  return (
    <div className="kv reveal-row" title={title}>
      <span>{label}</span>
      <span className="truncate">{children}</span>
    </div>
  );
}

/**
 * A round's reference rows: its kick-time settings as captured facts, and the
 * prices the chart draws without stating. Start, kick quote and average take
 * sit on consecutive rows so the three can be compared down one edge.
 */
export default function RoundSettingsPanel({
  round,
  chainId,
  startingPricePerUnit,
  minimumPrice,
  duration,
  stepDuration,
  decay,
  version,
}: {
  round: RoundListItem;
  chainId: number;
  startingPricePerUnit?: string | null;
  minimumPrice?: string | null;
  duration?: number | null;
  stepDuration?: number | null;
  decay?: string | null;
  version?: string | null;
}) {
  const showMinimumPrice = minimumPrice !== null && minimumPrice !== undefined;
  const showDuration = duration !== null && duration !== undefined;
  const expectedPriceValue = round.expected_price_per_unit ? formatPrice(round.expected_price_per_unit, 8) : null;

  return (
    <div>
      <Row label="Start" title="Start price per unit">
        <span className={startingPricePerUnit ? undefined : "text-faint"}>{startingPricePerUnit ? formatPrice(startingPricePerUnit, 8) : "—"}</span>
      </Row>

      <Row label="Kick quote" title="Stored kick-time market quote per unit">
        <span className={expectedPriceValue ? undefined : "text-faint"}>{expectedPriceValue ?? "—"}</span>
      </Row>

      {round.take_count > 0 ? (
        <Row label={round.take_count === 1 ? "Take" : "Avg take"} title={`Average execution price from ${round.paid_take_count} of ${round.take_count} takes with observed payment`}>
          <span className={round.avg_execution_price ? undefined : "text-faint"}>{round.avg_execution_price ? formatPrice(round.avg_execution_price, 8) : "—"}</span>
        </Row>
      ) : null}

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

      {version ? (
        <Row label="Version" title="Auction contract version">
          {version.startsWith("v") ? version : `v${version}`}
        </Row>
      ) : null}
    </div>
  );
}
