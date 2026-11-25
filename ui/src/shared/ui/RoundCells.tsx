import { formatAddress, formatAmount, formatCompactUsd, formatFullAmount } from "../lib/format";
import { lotNeedsTokenAddress } from "../lib/protocol";
import type { RoundListItem } from "../types/api";
import TokenValue from "./TokenValue";

/**
 * The lot a round put up: amount and symbol, with its kick-time value in a
 * quieter figure. The value keeps one place, the far edge of the lot's
 * measure and well clear of the next column, so the dollar figures of a list
 * line up under the word `value` in the column's head; a lot with no quote
 * leaves the place empty. Where a symbol does not say which
 * token it is, the token's short address follows it and gives way first when
 * the cell is tight.
 */
export function RoundLotCell({ round, showUsd = true }: { round: RoundListItem; showUsd?: boolean }) {
  const lotUsd = round.kick_market_quote_usd ?? round.total_market_quote_usd ?? null;
  const lotAmount = round.initial_available ?? round.sold_amount;
  const lotAmountLabel = [formatAmount(lotAmount), round.from_token_symbol].filter(Boolean).join(" ").trim() || "—";
  const tokenAddress = lotNeedsTokenAddress(round.protocol) ? round.from_token : null;
  const title = [
    `Lot: ${[formatFullAmount(lotAmount), round.from_token_symbol].filter(Boolean).join(" ")}`,
    tokenAddress ? `Token: ${tokenAddress}` : null,
    lotUsd ? `Value: ~${formatCompactUsd(lotUsd)} (${round.kick_market_quote_usd ? "kick-time estimate" : "take-time quote total"})` : null,
  ].filter(Boolean).join("\n");

  return (
    <span className="lot-cell" title={title}>
      <TokenValue
        address={round.from_token}
        symbol={lotAmountLabel}
        logoUrl={round.from_token_logo_url}
        chainId={round.chain_id}
        showCopy={false}
        className="min-w-0"
      />
      {tokenAddress ? (
        <span className="min-w-0 shrink-[100] truncate font-mono text-[10px] text-tertiary">
          {`(${formatAddress(tokenAddress, 6, 0)})`}
        </span>
      ) : null}
      {showUsd && lotUsd ? <span className="usd-note lot-usd">{formatCompactUsd(lotUsd)}</span> : null}
    </span>
  );
}
