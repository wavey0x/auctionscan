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

/** The kick-time settings of a round, as captured facts. */
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
