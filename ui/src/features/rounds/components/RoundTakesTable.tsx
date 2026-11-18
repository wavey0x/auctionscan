import { Fragment } from "react";
import { ChevronRight } from "lucide-react";

import { api } from "../../../shared/api/client";
import { cn, formatCompactDateTime, formatDateTime } from "../../../shared/lib/format";
import { linkRowKeyDown } from "../../../shared/lib/openRound";
import { getTakePricingBySource } from "../../../shared/lib/pricingSource";
import { occurrenceKey } from "../../../shared/lib/routes";
import type { TakeListItem } from "../../../shared/types/api";
import EmptyState from "../../../shared/ui/EmptyState";
import PnlValue from "../../../shared/ui/PnlValue";
import TakeExpandedRow from "../../../shared/ui/TakeExpandedRow";
import TakerAddressValue from "../../../shared/ui/TakerAddressValue";
import { TableHoverScope } from "../../../shared/ui/TableHoverContext";
import TokenAmountValue from "../../../shared/ui/TokenAmountValue";

/** A round's takes inside the drawer: four columns, and a row opens its detail in place. */
export default function RoundTakesTable({
  takes,
  priceSource,
  selectedOccurrenceKey,
  selectedTake,
  isSelectedTakeLoading,
  onSelect,
}: {
  takes: TakeListItem[];
  priceSource: string;
  selectedOccurrenceKey?: string | null;
  selectedTake?: Awaited<ReturnType<typeof api.getTake>>;
  isSelectedTakeLoading: boolean;
  onSelect: (key: string) => void;
}) {
  if (!takes.length) {
    return <EmptyState title="No takes in this round" titleClassName="text-tertiary" className="py-6" />;
  }

  return (
    <div className="table-wrap">
      <TableHoverScope>
        <table className="data-table">
          <thead>
            <tr>
              <th className="fit">Take</th>
              <th>Taker</th>
              <th>Received</th>
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
                    onClick={() => onSelect(key)}
                    onKeyDown={linkRowKeyDown(() => onSelect(key))}
                  >
                    <td className="mono fit pr-3 text-secondary" title={formatDateTime(take.timestamp)}>T{take.take_seq}</td>
                    <td className="max-w-[9rem]">
                      <TakerAddressValue address={take.taker} chainId={take.chain_id} showBlockie blockieSize={14} />
                      <div className="sub-line !block">{formatCompactDateTime(take.timestamp)}</div>
                    </td>
                    <td className="max-w-[11rem]">
                      <TokenAmountValue
                        amount={take.amount_paid}
                        estimatedAmount={take.expected_amount_paid}
                        address={take.to_token}
                        symbol={take.to_token_symbol}
                        logoUrl={take.to_token_logo_url}
                        chainId={take.chain_id}
                      />
                    </td>
                    <td className="num">
                      <PnlValue percent={takePricing.pnl_percent} usd={takePricing.pnl_usd} align="right" stacked />
                    </td>
                    <td className="open-cell" aria-hidden="true">
                      <ChevronRight className={cn("h-3.5 w-3.5", isSelected && "rotate-90")} strokeWidth={1.6} />
                    </td>
                  </tr>
                  {isSelected ? (
                    <TakeExpandedRow
                      colSpan={5}
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
