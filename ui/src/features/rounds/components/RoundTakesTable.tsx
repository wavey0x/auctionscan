import { Fragment } from "react";
import { ChevronRight } from "lucide-react";

import { api } from "../../../shared/api/client";
import { cn, formatAmount, formatCompactDateTime, formatDateTime, formatDuration, formatFullAmount, formatPrice, parseTimestamp } from "../../../shared/lib/format";
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

/**
 * A round's takes, one line each. The round has one pair, so amounts are bare
 * figures under a header that names the token. The narrow drawer keeps take,
 * taker, time, received and PnL; the expanded workspace adds the transaction,
 * the amount sold and the execution price.
 */
export default function RoundTakesTable({
  takes,
  kickedAt,
  fromSymbol,
  wantSymbol,
  priceSource,
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
  selectedOccurrenceKey?: string | null;
  selectedTake?: Awaited<ReturnType<typeof api.getTake>>;
  isSelectedTakeLoading: boolean;
  onSelect: (key: string) => void;
}) {
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
              <th className="col-md num">Sold <span className="th-unit">{fromSymbol}</span></th>
              <th className="num">Received <span className="th-unit col-md">{wantSymbol}</span></th>
              <th className="col-md num">Price</th>
              <th className="num">PnL</th>
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
                    <td className="mono fit pr-3 text-secondary" title={formatDateTime(take.timestamp)}>T{take.take_seq}</td>
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
                    <td className="col-md num" title={`${formatFullAmount(take.amount_taken)} ${fromSymbol}`}>
                      {formatAmount(take.amount_taken)}
                    </td>
                    <td className="num" title={`${isEstimate ? "Estimated " : ""}${formatFullAmount(paid)} ${wantSymbol}`}>
                      {isEstimate ? <span className="text-tertiary">est. </span> : null}
                      {formatAmount(paid)}
                    </td>
                    <td className="col-md num">{formatPrice(take.price)}</td>
                    <td className="num">
                      <PnlValue percent={takePricing.pnl_percent} usd={takePricing.pnl_usd} align="right" className="take-pnl" />
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
