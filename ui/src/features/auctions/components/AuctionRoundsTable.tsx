import type { MouseEvent } from "react";
import type { RoundListItem } from "../../../shared/types/api";
import MetricCoverage from "../../../shared/ui/MetricCoverage";

import { formatCompactDateTime, formatDateTime, renderKickedValue } from "../../../shared/lib/format";
import type { KickedDisplayMode } from "../../../shared/lib/format";
import { roundProgressSummary } from "../../../shared/lib/roundProgress";
import { occurrenceKey } from "../../../shared/lib/routes";
import PnlValue from "../../../shared/ui/PnlValue";
import RoundProgressMini, { type RoundProgressMiniMode } from "../../../shared/ui/RoundProgressMini";
import StackedListRow from "../../../shared/ui/StackedListRow";
import StatusBadge from "../../../shared/ui/StatusBadge";
import { TableHoverScope } from "../../../shared/ui/TableHoverContext";
import TokenAmountValue from "../../../shared/ui/TokenAmountValue";

function RecentRoundsMobileList({
  rounds,
  kickedDisplayMode,
  onToggleKickedDisplayMode,
  progressDisplayMode,
  onToggleProgressDisplayMode,
  onOpenRound,
}: {
  rounds: RoundListItem[];
  kickedDisplayMode: KickedDisplayMode;
  onToggleKickedDisplayMode: () => void;
  progressDisplayMode: RoundProgressMiniMode;
  onToggleProgressDisplayMode: () => void;
  onOpenRound: (round: RoundListItem) => void;
}) {
  return (
    <div className="md:hidden">
      {rounds.map((round) => (
        <StackedListRow
          key={`${round.chain_id}:${occurrenceKey(round.occurrence)}`}
          interactive
          className="space-y-2"
          onClick={() => onOpenRound(round)}
        >
          <div className="flex items-start justify-between gap-3">
            <div className="grid grid-cols-[auto_auto] items-center gap-1">
              <span className="font-mono text-primary">R{round.round_id}</span>
              <StatusBadge status={round.status} className="min-w-[3.9rem] px-1" />
            </div>
            <div className="font-mono text-meta text-tertiary">{round.take_count} takes</div>
          </div>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-meta text-tertiary">
            <button
              type="button"
              className="font-mono underline-offset-4 transition-colors hover:text-primary hover:underline"
              title={formatDateTime(round.kicked_at)}
              onClick={(event) => {
                event.stopPropagation();
                onToggleKickedDisplayMode();
              }}
            >
              {renderKickedValue(round.kicked_at, kickedDisplayMode)}
            </button>
            <span aria-hidden="true">·</span>
            <button
              type="button"
              className="font-mono underline-offset-4 transition-colors hover:text-primary hover:underline"
              onClick={(event) => {
                event.stopPropagation();
                onToggleProgressDisplayMode();
              }}
            >
              {roundProgressSummary(round, progressDisplayMode)}
            </button>
            <span aria-hidden="true">·</span>
            <span className="font-mono" title={formatDateTime(round.end_at || round.last_take_at)}>
              {formatCompactDateTime(round.end_at || round.last_take_at)}
            </span>
          </div>
          <div className="space-y-1">
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="metric-label shrink-0">Sold</span>
              <TokenAmountValue
                amount={round.sold_amount}
                address={round.from_token}
                symbol={round.from_token_symbol}
                logoUrl={round.from_token_logo_url}
                chainId={round.chain_id}
                className="min-w-0 w-auto"
              />
            </div>
            <div className="flex min-w-0 items-center gap-1.5">
              <span className="metric-label shrink-0">Recv</span>
              <TokenAmountValue
                amount={round.paid_amount}
                coverage={{ count: round.paid_take_count, total: round.take_count }}
                address={round.want_token}
                symbol={round.want_token_symbol}
                logoUrl={round.want_token_logo_url}
                chainId={round.chain_id}
                className="min-w-0 w-auto"
              />
            </div>
            <div className="flex items-center gap-1.5">
              <span className="metric-label shrink-0">PnL</span>
              <PnlValue
                percent={round.total_auction_profit_bps}
                usd={round.total_auction_profit_usd}
                compact
              />
              <MetricCoverage count={round.priced_take_count ?? 0} total={round.take_count} label="quoted" />
              {round.usd_priced_take_count !== (round.priced_take_count ?? 0) ? <MetricCoverage count={round.usd_priced_take_count} total={round.take_count} label="USD" /> : null}
            </div>
          </div>
        </StackedListRow>
      ))}
    </div>
  );
}

export default function AuctionRoundsTable({
  rounds,
  kickedDisplayMode,
  onToggleKickedDisplayMode,
  progressDisplayMode,
  onToggleProgressDisplayMode,
  onOpenRound,
  onRoundClick,
}: {
  rounds: RoundListItem[];
  kickedDisplayMode: KickedDisplayMode;
  onToggleKickedDisplayMode: () => void;
  progressDisplayMode: RoundProgressMiniMode;
  onToggleProgressDisplayMode: () => void;
  onOpenRound: (round: RoundListItem) => void;
  onRoundClick: (event: MouseEvent<HTMLTableRowElement>, round: RoundListItem) => void;
}) {
  return (
    <>
      <RecentRoundsMobileList
        rounds={rounds}
        kickedDisplayMode={kickedDisplayMode}
        onToggleKickedDisplayMode={onToggleKickedDisplayMode}
        progressDisplayMode={progressDisplayMode}
        onToggleProgressDisplayMode={onToggleProgressDisplayMode}
        onOpenRound={onOpenRound}
      />
      <div className="hidden md:block table-wrap">
        <TableHoverScope>
          <table className="data-table">
            <thead>
              <tr>
                <th className="w-[7.5rem] whitespace-nowrap">Round Status</th>
                <th>
                  <button
                    type="button"
                    className="font-inherit normal-case text-inherit underline-offset-4 transition-colors hover:text-primary hover:underline"
                    onClick={onToggleProgressDisplayMode}
                  >
                    Progress ({progressDisplayMode === "time" ? "Time" : "Take"})
                  </button>
                </th>
                <th>
                  <button
                    type="button"
                    className="font-inherit uppercase text-inherit underline-offset-4 transition-colors hover:text-primary hover:underline"
                    onClick={onToggleKickedDisplayMode}
                  >
                    Kicked
                  </button>
                </th>
                <th>Closed</th>
                <th className="text-right">Takes</th>
                <th>Sold</th>
                <th>Received</th>
                <th className="w-[4.8rem] pr-1 leading-none">PnL</th>
              </tr>
            </thead>
            <tbody>
              {rounds.map((round) => (
                <tr
                  key={`${round.chain_id}:${occurrenceKey(round.occurrence)}`}
                  className="data-row"
                  onClick={(event) => onRoundClick(event, round)}
                  onAuxClick={(event) => onRoundClick(event, round)}
                >
                  <td className="w-[7.5rem]">
                    <div className="grid grid-cols-[2.35rem_minmax(0,1fr)] items-center gap-1">
                      <span className="font-mono text-primary">R{round.round_id}</span>
                      <StatusBadge status={round.status} className="min-w-[3.9rem] px-1" />
                    </div>
                  </td>
                  <td>
                    <RoundProgressMini
                      status={round.status}
                      kickedAt={round.kicked_at}
                      scheduledEndAt={round.scheduled_end_at}
                      endAt={round.end_at}
                      availableAmount={round.available_amount}
                      initialAvailable={round.initial_available}
                      fromTokenSymbol={round.from_token_symbol}
                      mode={progressDisplayMode}
                      onToggleMode={onToggleProgressDisplayMode}
                    />
                  </td>
                  <td title={formatDateTime(round.kicked_at)}>
                    <button
                      type="button"
                      className="font-mono text-primary underline-offset-4 transition-colors hover:text-primary hover:underline"
                      onClick={(event) => {
                        event.stopPropagation();
                        onToggleKickedDisplayMode();
                      }}
                    >
                      {renderKickedValue(round.kicked_at, kickedDisplayMode)}
                    </button>
                  </td>
                  <td className="font-mono text-primary" title={formatDateTime(round.end_at || round.last_take_at)}>
                    {formatCompactDateTime(round.end_at || round.last_take_at)}
                  </td>
                  <td className="text-right font-mono text-primary">{round.take_count}</td>
                  <td className="text-primary">
                    <TokenAmountValue
                      amount={round.sold_amount}
                      address={round.from_token}
                      symbol={round.from_token_symbol}
                      logoUrl={round.from_token_logo_url}
                      chainId={round.chain_id}
                    />
                  </td>
                  <td className="text-primary">
                    <TokenAmountValue
                      amount={round.paid_amount}
                      coverage={{ count: round.paid_take_count, total: round.take_count }}
                      address={round.want_token}
                      symbol={round.want_token_symbol}
                      logoUrl={round.want_token_logo_url}
                      chainId={round.chain_id}
                    />
                  </td>
                  <td className="w-[4.8rem] pr-1">
                    <PnlValue
                      percent={round.total_auction_profit_bps}
                      usd={round.total_auction_profit_usd}
                      className="w-[4.8rem]"
                    />
                    <MetricCoverage count={round.priced_take_count ?? 0} total={round.take_count} label="quoted" />
                    {round.usd_priced_take_count !== (round.priced_take_count ?? 0) ? <MetricCoverage count={round.usd_priced_take_count} total={round.take_count} label="USD" /> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableHoverScope>
      </div>
    </>
  );
}
