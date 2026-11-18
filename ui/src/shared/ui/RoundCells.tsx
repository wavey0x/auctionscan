import { formatAmount, formatCompactUsd, formatFullAmount } from "../lib/format";
import type { RoundListItem } from "../types/api";
import TokenValue from "./TokenValue";

/** The lot a round put up: amount and symbol, with its kick-time value in a quieter figure. */
export function RoundLotCell({ round, showUsd = true }: { round: RoundListItem; showUsd?: boolean }) {
  const lotUsd = round.kick_market_quote_usd ?? round.total_market_quote_usd ?? null;
  const lotAmount = round.initial_available ?? round.sold_amount;
  const lotAmountLabel = [formatAmount(lotAmount), round.from_token_symbol].filter(Boolean).join(" ").trim() || "—";
  const title = [
    `Lot: ${[formatFullAmount(lotAmount), round.from_token_symbol].filter(Boolean).join(" ")}`,
    lotUsd ? `Value: ~${formatCompactUsd(lotUsd)} (${round.kick_market_quote_usd ? "kick-time estimate" : "take-time quote total"})` : null,
  ].filter(Boolean).join("\n");

  return (
    <span className="inline-flex min-w-0 max-w-full items-center gap-2 whitespace-nowrap" title={title}>
      <TokenValue
        address={round.from_token}
        symbol={lotAmountLabel}
        logoUrl={round.from_token_logo_url}
        chainId={round.chain_id}
        showCopy={false}
        className="min-w-0"
      />
      {showUsd && lotUsd ? <span className="usd-note shrink-0">{formatCompactUsd(lotUsd)}</span> : null}
    </span>
  );
}
