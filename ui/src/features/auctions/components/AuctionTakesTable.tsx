import { Fragment } from "react";
import { ChevronRight } from "lucide-react";

import { api } from "../../../shared/api/client";
import { cn, formatAmount, formatCompactDateTime, formatDateTime, formatPrice } from "../../../shared/lib/format";
import { linkRowKeyDown } from "../../../shared/lib/openRound";
import { getTakePricingBySource } from "../../../shared/lib/pricingSource";
import { occurrenceKey } from "../../../shared/lib/routes";
import EmptyState from "../../../shared/ui/EmptyState";
import PnlValue from "../../../shared/ui/PnlValue";
import TakerAddressValue from "../../../shared/ui/TakerAddressValue";
import TakeExpandedRow from "../../../shared/ui/TakeExpandedRow";
import TokenAmountValue from "../../../shared/ui/TokenAmountValue";

export default function AuctionTakesTable({
  takes,
  priceSource,
  selectedOccurrenceKey,
  selectedTake,
  isSelectedTakeLoading,
  onOpenTake,
}: {
  takes: Awaited<ReturnType<typeof api.getAuctionTakes>>["takes"];
  priceSource: string;
  selectedOccurrenceKey?: string | null;
  selectedTake?: Awaited<ReturnType<typeof api.getTake>>;
  isSelectedTakeLoading: boolean;
  onOpenTake: (key: string) => void;
}) {
  if (!takes.length) {
    return <EmptyState title="No recent takes" description="This auction has no indexed take activity yet." />;
  }

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th className="fit">Round</th>
            <th className="col-lo fit">Take</th>
            <th className="col-lo">Time</th>
            <th>Taker</th>
            <th className="col-md">Sold</th>
            <th className="col-lo">Paid</th>
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

            return (
              <Fragment key={`${take.chain_id}:${key}`}>
                <tr
                  className={cn("data-row", isSelected && "is-open")}
                  tabIndex={0}
                  data-row=""
                  aria-expanded={isSelected}
                  onClick={() => onOpenTake(key)}
                  onKeyDown={linkRowKeyDown(() => onOpenTake(key))}
                >
                  <td className="mono fit pr-3 text-secondary">R{take.round_id}</td>
                  <td className="col-lo mono fit pr-3 text-secondary">T{take.take_seq}</td>
                  <td className="col-lo mono dim fit pr-4" title={formatDateTime(take.timestamp)}>
                    {formatCompactDateTime(take.timestamp)}
                  </td>
                  <td>
                    <TakerAddressValue address={take.taker} chainId={take.chain_id} showBlockie blockieSize={14} />
                    <div className="sub-line">
                      <span className="sub-lo">{`T${take.take_seq} · ${[formatAmount(take.amount_paid ?? take.expected_amount_paid), take.to_token_symbol].filter(Boolean).join(" ")}`}</span>
                    </div>
                  </td>
                  <td className="col-md">
                    <div className="cell-clip"><TokenAmountValue
                      amount={take.amount_taken}
                      address={take.from_token}
                      symbol={take.from_token_symbol}
                      logoUrl={take.from_token_logo_url}
                      chainId={take.chain_id}
                    /></div>
                  </td>
                  <td className="col-lo">
                    <div className="cell-clip"><TokenAmountValue
                      amount={take.amount_paid}
                      estimatedAmount={take.expected_amount_paid}
                      address={take.to_token}
                      symbol={take.to_token_symbol}
                      logoUrl={take.to_token_logo_url}
                      chainId={take.chain_id}
                    /></div>
                  </td>
                  <td className="col-md num">{formatPrice(take.price)}</td>
                  <td className="num">
                    <PnlValue percent={takePricing.pnl_percent} usd={takePricing.pnl_usd} align="right" />
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
    </div>
  );
}
