import type { ReactNode } from "react";

import { formatAmount, formatDateTime, formatPrice } from "../lib/format";
import { getTakePricingBySource, DEFAULT_PRICE_SOURCE } from "../lib/pricingSource";
import type { TakeDetail } from "../types/api";
import AddressValue from "./AddressValue";
import PnlValue from "./PnlValue";
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
      <div className="label">{label}</div>
      <div className="mt-0.5 min-w-0 text-data text-primary">{value}</div>
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
    <div className="reveal-row grid grid-cols-2 gap-x-4 gap-y-3 xl:grid-cols-4">
      <TakeExpandedField
        label="Taker"
        value={<AddressValue address={take.taker} chainId={take.chain_id} />}
      />
      <TakeExpandedField
        label="Time"
        value={<span className="font-mono">{formatDateTime(take.timestamp)}</span>}
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
        value={<span className="font-mono">{formatPrice(take.price)}</span>}
      />
      <TakeExpandedField
        label="Delta"
        value={<PnlValue percent={pricing.pnl_percent} usd={pricing.pnl_usd} />}
      />
      <TakeExpandedField
        label="Transaction"
        value={<TxHashValue txHash={take.tx_hash} chainId={take.chain_id} />}
      />
    </div>
  );
}
