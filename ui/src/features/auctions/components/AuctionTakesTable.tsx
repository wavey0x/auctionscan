import { Fragment } from "react";

import { api } from "../../../shared/api/client";
import { formatCompactDateTime, formatDateTime, formatPrice } from "../../../shared/lib/format";
import { getTakePricingBySource } from "../../../shared/lib/pricingSource";
import { occurrenceKey } from "../../../shared/lib/routes";
import EmptyState from "../../../shared/ui/EmptyState";
import PnlValue from "../../../shared/ui/PnlValue";
import Skeleton from "../../../shared/ui/Skeleton";
import StackedListRow from "../../../shared/ui/StackedListRow";
import TakeExpandedContent from "../../../shared/ui/TakeExpandedContent";
import TakerAddressValue from "../../../shared/ui/TakerAddressValue";
import TakeExpandedRow from "../../../shared/ui/TakeExpandedRow";
import TokenAmountValue from "../../../shared/ui/TokenAmountValue";
import TxHashValue from "../../../shared/ui/TxHashValue";

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
    return (
      <div className="p-3">
        <EmptyState title="No recent takes" description="This auction has no indexed take activity yet." />
      </div>
    );
  }

  return (
    <>
      <div className="md:hidden">
        {takes.map((take) => {
          const isSelected = occurrenceKey(take.occurrence) === selectedOccurrenceKey;
          const takePricing = getTakePricingBySource(take, priceSource);

          return (
            <StackedListRow
              key={`${take.chain_id}:${occurrenceKey(take.occurrence)}`}
              interactive
              className="space-y-2"
              onClick={() => onOpenTake(occurrenceKey(take.occurrence))}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-primary">R{take.round_id}</span>
                  <span className="font-mono text-tertiary">T{take.take_seq}</span>
                </div>
                <div className="font-mono text-meta text-tertiary" title={formatDateTime(take.timestamp)}>
                  {formatCompactDateTime(take.timestamp)}
                </div>
              </div>
              <div className="flex min-w-0 items-center justify-between gap-3">
                <div className="min-w-0">
                  <TakerAddressValue address={take.taker} chainId={take.chain_id} />
                </div>
                <TxHashValue txHash={take.tx_hash} chainId={take.chain_id} width={6} />
              </div>
              <div className="space-y-1">
                <div className="flex min-w-0 items-center gap-1.5">
                  <span className="metric-label shrink-0">Sold</span>
                  <TokenAmountValue
                    amount={take.amount_taken}
                    address={take.from_token}
                    symbol={take.from_token_symbol}
                    logoUrl={take.from_token_logo_url}
                    chainId={take.chain_id}
                    className="min-w-0 w-auto"
                  />
                </div>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <div className="flex min-w-0 items-center gap-1.5">
                    <span className="metric-label shrink-0">Paid</span>
                    <TokenAmountValue
                      amount={take.amount_paid}
                      estimatedAmount={take.expected_amount_paid}
                      address={take.to_token}
                      symbol={take.to_token_symbol}
                      logoUrl={take.to_token_logo_url}
                      chainId={take.chain_id}
                      className="min-w-0 w-auto"
                    />
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="metric-label shrink-0">Price</span>
                    <span className="font-mono text-primary">{formatPrice(take.price)}</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="metric-label shrink-0">PnL</span>
                    <PnlValue percent={takePricing.pnl_percent} usd={takePricing.pnl_usd} compact />
                  </div>
                </div>
              </div>
              {isSelected ? (
                <div className="rounded-md border border-divider-subtle bg-background px-3 py-3">
                  {isSelectedTakeLoading ? (
                    <Skeleton className="h-32 w-full" />
                  ) : selectedTake ? (
                    <TakeExpandedContent take={selectedTake} priceSource={priceSource} />
                  ) : null}
                </div>
              ) : null}
            </StackedListRow>
          );
        })}
      </div>
      <div className="hidden md:block table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Round</th>
              <th>Take</th>
              <th>Time</th>
              <th>Taker</th>
              <th>Sold</th>
              <th>Paid</th>
              <th>Price</th>
              <th>PnL</th>
            </tr>
          </thead>
          <tbody>
            {takes.map((take) => {
              const isSelected = occurrenceKey(take.occurrence) === selectedOccurrenceKey;
              const takePricing = getTakePricingBySource(take, priceSource);

              return (
                <Fragment key={`${take.chain_id}:${occurrenceKey(take.occurrence)}`}>
                  <tr
                    className={`data-row ${isSelected ? "bg-surface" : ""}`}
                    onClick={() => onOpenTake(occurrenceKey(take.occurrence))}
                  >
                    <td className="font-mono text-primary">R{take.round_id}</td>
                    <td className="font-mono text-primary">T{take.take_seq}</td>
                    <td className="font-mono text-primary" title={formatDateTime(take.timestamp)}>
                      {formatCompactDateTime(take.timestamp)}
                    </td>
                    <td>
                      <TakerAddressValue address={take.taker} chainId={take.chain_id} />
                    </td>
                    <td className="text-primary">
                      <TokenAmountValue
                        amount={take.amount_taken}
                        address={take.from_token}
                        symbol={take.from_token_symbol}
                        logoUrl={take.from_token_logo_url}
                        chainId={take.chain_id}
                      />
                    </td>
                    <td className="text-primary">
                      <TokenAmountValue
                        amount={take.amount_paid}
                        estimatedAmount={take.expected_amount_paid}
                        address={take.to_token}
                        symbol={take.to_token_symbol}
                        logoUrl={take.to_token_logo_url}
                        chainId={take.chain_id}
                      />
                    </td>
                    <td className="font-mono text-primary">{formatPrice(take.price)}</td>
                    <td>
                      <PnlValue percent={takePricing.pnl_percent} usd={takePricing.pnl_usd} className="w-[4.8rem]" />
                    </td>
                  </tr>
                  {isSelected ? (
                    <TakeExpandedRow
                      colSpan={8}
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
    </>
  );
}

