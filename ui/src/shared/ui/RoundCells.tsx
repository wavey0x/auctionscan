import { formatAddress, formatAmount, formatCompactUsd, formatFullAmount } from "../lib/format";
import { roundMarketValue } from "../lib/pricingSource";
import { lotNeedsTokenAddress } from "../lib/protocol";
import type { RoundListItem } from "../types/api";
import TokenValue from "./TokenValue";

/**
 * The lot a round put up: amount and symbol, with its market value in a
 * quieter figure: what sold, valued when it sold, so the figure is the one
 * the round's PnL is measured against; a lot nothing has been taken from is
 * valued as put up. The value keeps one place, the far edge of the lot's
 * measure and well clear of the next column, so the dollar figures of a list
 * line up under the word `value` in the column's head; a lot with no quote
 * leaves the place empty. Where a symbol does not say which
 * token it is, the token's short address follows it and gives way first when
 * the cell is tight.
 */
export function RoundLotCell({ round, showUsd = true }: { round: RoundListItem; showUsd?: boolean }) {
  const { usd: lotUsd, at: valuedAt } = roundMarketValue(round, round.total_market_quote_usd);
  const lotAmount = round.initial_available ?? round.sold_amount;
  const lotAmountLabel = [formatAmount(lotAmount), round.from_token_symbol].filter(Boolean).join(" ").trim() || "—";
  const tokenAddress = lotNeedsTokenAddress(round.protocol) ? round.from_token : null;
  const title = [
    `Lot: ${[formatFullAmount(lotAmount), round.from_token_symbol].filter(Boolean).join(" ")}`,
    tokenAddress ? `Token: ${tokenAddress}` : null,
    lotUsd ? `Value: ~${formatCompactUsd(lotUsd)} (${valuedAt === "take" ? "market quote for what sold, at take time" : "market quote at kick"})` : null,
    lotUsd && valuedAt === "take" && round.usd_priced_take_count < round.take_count
      ? `Market value known for ${round.usd_priced_take_count} of ${round.take_count} takes`
      : null,
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
