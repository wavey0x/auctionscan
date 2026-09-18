import type { ReactNode } from "react";

import { formatAmount, formatCompactDateTime, formatDateTime, formatPrice, formatUsd } from "../lib/format";
import { getTakePricingBySource, DEFAULT_PRICE_SOURCE } from "../lib/pricingSource";
import type { TakeDetail } from "../types/api";
import AddressValue from "./AddressValue";
import TokenAmountValue from "./TokenAmountValue";
import TokenValue from "./TokenValue";
import TxHashValue from "./TxHashValue";

function TakeExpandedField({
  label,
  value,
}: {
  label: string;
  value: ReactNode;
}) {
  return (
    <div className="min-w-0">
      <div className="metric-label">{label}</div>
      <div className="mt-1 min-w-0 text-data text-primary">{value}</div>
    </div>
  );
}

export default function TakeExpandedContent({
  take,
  priceSource = DEFAULT_PRICE_SOURCE,
}: {
  take: TakeDetail;
  priceSource?: string;
}) {
  const pricing = getTakePricingBySource(take, priceSource);

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <TakeExpandedField
        label="Taker"
        value={<AddressValue address={take.taker} chainId={take.chain_id} />}
      />
      <TakeExpandedField
        label="Time"
        value={
          <div className="font-mono" title={formatDateTime(take.timestamp)}>
            {formatCompactDateTime(take.timestamp)}
          </div>
        }
      />
      <TakeExpandedField
        label="Sold"
        value={
          <TokenValue
            address={take.from_token}
            symbol={`${formatAmount(take.amount_taken)} ${take.from_token_symbol || ""}`.trim()}
            logoUrl={take.from_token_logo_url}
            chainId={take.chain_id}
          />
        }
      />
      <TakeExpandedField
        label="Received"
        value={
          <TokenAmountValue
            amount={take.amount_paid}
            estimatedAmount={take.expected_amount_paid}
            address={take.to_token}
            symbol={take.to_token_symbol}
            logoUrl={take.to_token_logo_url}
            chainId={take.chain_id}
          />
        }
      />
      <TakeExpandedField
        label="Execution price"
        value={<div className="font-mono">{formatPrice(take.price)}</div>}
      />
      <TakeExpandedField
        label="Delta"
        value={
          <div className="font-mono">
            {pricing.pnl_usd ? formatUsd(pricing.pnl_usd) : "—"}
            {pricing.pnl_percent !== null && pricing.pnl_percent !== undefined
              ? ` (${pricing.pnl_percent.toFixed(2)}%)`
              : ""}
          </div>
        }
      />
      <TakeExpandedField
        label="Transaction"
        value={<TxHashValue txHash={take.tx_hash} chainId={take.chain_id} />}
      />
    </div>
  );
}
