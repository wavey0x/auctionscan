import { Fragment, type MouseEvent, type ReactNode } from "react";
import { ArrowUpRight, ChevronRight } from "lucide-react";

import { api } from "../../../shared/api/client";
import { buildExplorerUrl, useChainInfo } from "../../../shared/lib/chains";
import type { Denomination } from "../../../shared/lib/denomination";
import { cn, formatAmount, formatCompactDateTime, formatDateTime, formatDuration, formatFullAmount, formatPrice, formatUsd, parseTimestamp } from "../../../shared/lib/format";
import { linkRowKeyDown } from "../../../shared/lib/openRound";
import { getTakePricingBySource } from "../../../shared/lib/pricingSource";
import { occurrenceKey } from "../../../shared/lib/routes";
import type { TakeListItem } from "../../../shared/types/api";
import PnlValue from "../../../shared/ui/PnlValue";
import TakeExpandedRow from "../../../shared/ui/TakeExpandedRow";
import TakerAddressValue from "../../../shared/ui/TakerAddressValue";
import { TableHoverScope } from "../../../shared/ui/TableHoverContext";
import TxHashValue from "../../../shared/ui/TxHashValue";

/** How long after the kick a take landed, which in a Dutch auction is also where on the price path. */
function sinceKick(kickedAt: string, timestamp: string): string | null {
  const kick = parseTimestamp(kickedAt);
  const taken = parseTimestamp(timestamp);
  if (!kick || !taken) return null;
  const seconds = Math.round((taken.getTime() - kick.getTime()) / 1000);
  return seconds >= 0 ? `+${formatDuration(seconds)}` : null;
}

const dash = <span className="text-faint">—</span>;

/**
 * A take's label, which is also the way out to its transaction: the number
 * with the outbound mark beside it. The transaction is what a reader wants
 * most from a take, so the mark is on every row at every width instead of
 * surfacing on hover, and it takes no column of its own. Following it leaves
 * the row as it was.
 */
function TakeLabel({ seq, txHash, chainId }: { seq: number; txHash?: string | null; chainId: number }) {
  const { chain } = useChainInfo(chainId);
  const href = buildExplorerUrl(chain, "tx", txHash);
  if (!href || !txHash) return <>T{seq}</>;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="tx-link"
      title={`Open transaction ${txHash} in explorer`}
      onClick={(event: MouseEvent<HTMLElement>) => event.stopPropagation()}
    >
      <span>T{seq}</span>
      <ArrowUpRight className="h-3 w-3" strokeWidth={1.8} aria-hidden="true" />
    </a>
  );
}

/**
 * A round's takes, one line each. The round has one pair, so amounts are bare
 * figures under a header that names the token. The narrow drawer keeps take,
 * taker, time, received and PnL; the expanded workspace adds the transaction
 * hash, the amount sold and the execution price. Every figure is given once,
 * in the round's tokens or in dollars; a column header switches between them.
 */
export default function RoundTakesTable({
  takes,
  kickedAt,
  fromSymbol,
  wantSymbol,
  priceSource,
  denomination,
  onToggleDenomination,
  selectedOccurrenceKey,
  selectedTake,
  isSelectedTakeLoading,
  onSelect,
}: {
  takes: TakeListItem[];
  kickedAt: string;
  fromSymbol: string;
  wantSymbol: string;
  priceSource: string;
  denomination: Denomination;
  onToggleDenomination: () => void;
  selectedOccurrenceKey?: string | null;
  selectedTake?: Awaited<ReturnType<typeof api.getTake>>;
  isSelectedTakeLoading: boolean;
  onSelect: (key: string) => void;
}) {
  const inUsd = denomination === "usd";
  const figureHead = (label: string, unit?: ReactNode) => (
    <button
      type="button"
      className="header-toggle"
      title={inUsd ? "Show token amounts" : "Show dollar values"}
      onClick={onToggleDenomination}
    >
      {label}
      {unit}
    </button>
  );

  return (
    <div className="table-wrap">
      <TableHoverScope>
        <table className="data-table takes-table">
          <thead>
            <tr>
              <th className="fit">Take</th>
              <th className="col-md">Tx</th>
              <th>Taker</th>
              <th className="col-xs">Time</th>
              <th className="col-md num">{figureHead("Sold", inUsd ? null : <span className="th-unit">{fromSymbol}</span>)}</th>
              <th className="num">{figureHead("Received", inUsd ? null : <span className="th-unit col-md">{wantSymbol}</span>)}</th>
              <th className="col-md num">Price</th>
              <th className="num">{figureHead("PnL")}</th>
              <th className="open-cell"><span className="sr-only">Expand</span></th>
            </tr>
          </thead>
          <tbody>
            {takes.map((take) => {
              const key = occurrenceKey(take.occurrence);
              const isSelected = key === selectedOccurrenceKey;
              const takePricing = getTakePricingBySource(take, priceSource);
              const elapsed = sinceKick(kickedAt, take.timestamp) ?? formatCompactDateTime(take.timestamp);
              const isEstimate = take.amount_paid == null && take.expected_amount_paid != null;
              const paid = isEstimate ? take.expected_amount_paid : take.amount_paid;
              const soldUsd = takePricing.market_quote_out_usd;
              const paidUsd = take.amount_paid_usd;

              return (
                <Fragment key={`${take.chain_id}:${key}`}>
                  <tr
                    className={cn("data-row", isSelected && "is-open")}
                    tabIndex={0}
                    data-row=""
                    aria-expanded={isSelected}
                    onClick={() => onSelect(key)}
                    onKeyDown={linkRowKeyDown(() => onSelect(key))}
                  >
                    <td className="mono fit pr-3 text-secondary" title={formatDateTime(take.timestamp)}>
                      <TakeLabel seq={take.take_seq} txHash={take.tx_hash} chainId={take.chain_id} />
                    </td>
                    <td className="col-md fit pr-3">
                      <TxHashValue txHash={take.tx_hash} chainId={take.chain_id} width={6} />
                    </td>
                    <td>
                      <TakerAddressValue address={take.taker} chainId={take.chain_id} showBlockie blockieSize={14} />
                      <div className="sub-xs">{elapsed}</div>
                    </td>
                    <td className="col-xs mono fit pr-3 text-secondary" title={formatDateTime(take.timestamp)}>
                      {elapsed}
                      <span className="col-md ml-2 text-tertiary">{formatCompactDateTime(take.timestamp)}</span>
                    </td>
                    <td
                      className="col-md num"
                      title={[`${formatFullAmount(take.amount_taken)} ${fromSymbol}`, soldUsd ? `market quote ${formatUsd(soldUsd)}` : null].filter(Boolean).join(" · ")}
                    >
                      {inUsd ? (soldUsd ? formatUsd(soldUsd) : dash) : formatAmount(take.amount_taken)}
                    </td>
                    <td
                      className="num"
                      title={[`${isEstimate ? "Estimated " : ""}${formatFullAmount(paid)} ${wantSymbol}`, paidUsd ? formatUsd(paidUsd) : null].filter(Boolean).join(" · ")}
                    >
                      {inUsd ? (paidUsd ? formatUsd(paidUsd) : dash) : (
                        <>
                          {isEstimate ? <span className="text-tertiary">est. </span> : null}
                          {formatAmount(paid)}
                        </>
                      )}
                    </td>
                    <td className="col-md num">{formatPrice(take.price)}</td>
                    <td className="num">
                      <PnlValue percent={takePricing.pnl_percent} usd={takePricing.pnl_usd} show={inUsd ? "usd" : "percent"} align="right" />
                    </td>
                    <td className="open-cell" aria-hidden="true">
                      <ChevronRight className={cn("h-3.5 w-3.5", isSelected && "rotate-90")} strokeWidth={1.6} />
                    </td>
                  </tr>
                  {isSelected ? (
                    <TakeExpandedRow
                      colSpan={9}
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
  );
}
