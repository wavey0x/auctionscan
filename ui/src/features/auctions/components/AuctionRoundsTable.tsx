import type { RoundListItem } from "../../../shared/types/api";

import { formatAmount, formatCompactDateTime, formatDateTime, renderKickedValue } from "../../../shared/lib/format";
import type { KickedDisplayMode } from "../../../shared/lib/format";
import { useRoundRows } from "../../../shared/lib/openRound";
import { roundPnlCoverageTitle } from "../../../shared/lib/pricingSource";
import { occurrenceKey } from "../../../shared/lib/routes";
import OpenMark from "../../../shared/ui/OpenMark";
import PnlValue from "../../../shared/ui/PnlValue";
import RoundProgressMini, { type RoundProgressMiniMode } from "../../../shared/ui/RoundProgressMini";
import StatusBadge from "../../../shared/ui/StatusBadge";
import { TableHoverScope } from "../../../shared/ui/TableHoverContext";
import TokenAmountValue from "../../../shared/ui/TokenAmountValue";

/** An auction's rounds: one line each, opening the round drawer over the auction page. */
export default function AuctionRoundsTable({
  rounds,
  kickedDisplayMode,
  onToggleKickedDisplayMode,
  progressDisplayMode,
  onToggleProgressDisplayMode,
}: {
  rounds: RoundListItem[];
  kickedDisplayMode: KickedDisplayMode;
  onToggleKickedDisplayMode: () => void;
  progressDisplayMode: RoundProgressMiniMode;
  onToggleProgressDisplayMode: () => void;
}) {
  const { rowProps } = useRoundRows(rounds);

  return (
    <div className="table-wrap">
      <TableHoverScope>
        <table className="data-table">
          <thead>
            <tr>
              <th>Round</th>
              <th className="col-md">
                <button
                  type="button"
                  className="header-toggle"
                  title={`Show ${progressDisplayMode === "time" ? "share of the lot sold" : "time elapsed"}`}
                  onClick={onToggleProgressDisplayMode}
                >
                  Progress <em>{progressDisplayMode === "time" ? "time" : "sold"}</em>
                </button>
              </th>
              <th className="col-md">
                <button
                  type="button"
                  className="header-toggle"
                  title={kickedDisplayMode === "relative" ? "Show kick times" : "Show time since kick"}
                  onClick={onToggleKickedDisplayMode}
                >
                  Kicked
                </button>
              </th>
              <th className="col-xl">Closed</th>
              <th className="col-md num">Takes</th>
              <th className="col-lo">Sold</th>
              <th className="col-lo">Received</th>
              <th className="num">PnL</th>
              <th className="open-cell"><span className="sr-only">Open</span></th>
            </tr>
          </thead>
          <tbody>
            {rounds.map((round) => (
              <tr key={`${round.chain_id}:${occurrenceKey(round.occurrence)}`} {...rowProps(round)}>
                <td className="fit pr-5">
                  <span className="inline-flex items-center gap-3">
                    <span className="w-9 font-mono text-secondary">R{round.round_id}</span>
                    <StatusBadge status={round.status} />
                  </span>
                  <div className="sub-line pl-12">
                    {renderKickedValue(round.kicked_at, "relative")}
                    <span className="sub-lo">{` · ${[formatAmount(round.sold_amount), round.from_token_symbol].filter(Boolean).join(" ")}`}</span>
                  </div>
                </td>
                <td className="col-md fit pr-4">
                  <RoundProgressMini
                    status={round.status}
                    kickedAt={round.kicked_at}
                    scheduledEndAt={round.scheduled_end_at}
                    endAt={round.end_at}
                    availableAmount={round.available_amount}
                    initialAvailable={round.initial_available}
                    soldAmount={round.sold_amount}
                    fromTokenSymbol={round.from_token_symbol}
                    takeCount={round.take_count}
                    mode={progressDisplayMode}
                  />
                </td>
                <td className="col-md mono dim fit pr-4" title={formatDateTime(round.kicked_at)}>
                  {renderKickedValue(round.kicked_at, kickedDisplayMode)}
                </td>
                <td className="col-xl mono dim fit pr-4" title={formatDateTime(round.end_at || round.last_take_at)}>
                  {formatCompactDateTime(round.end_at || round.last_take_at)}
                </td>
                <td className="col-md num fit pr-4">{round.take_count}</td>
                <td className="col-lo">
                  <div className="cell-clip"><TokenAmountValue
                    amount={round.sold_amount}
                    address={round.from_token}
                    symbol={round.from_token_symbol}
                    logoUrl={round.from_token_logo_url}
                    chainId={round.chain_id}
                  /></div>
                </td>
                <td className="col-lo">
                  <div className="cell-clip"><TokenAmountValue
                    amount={round.paid_amount}
                    coverage={{ count: round.paid_take_count, total: round.take_count }}
                    address={round.want_token}
                    symbol={round.want_token_symbol}
                    logoUrl={round.want_token_logo_url}
                    chainId={round.chain_id}
                  /></div>
                </td>
                <td className="num">
                  <PnlValue
                    percent={round.total_auction_profit_bps}
                    usd={round.total_auction_profit_usd}
                    title={roundPnlCoverageTitle(round)}
                    align="right"
                  />
                </td>
                <OpenMark />
              </tr>
            ))}
          </tbody>
        </table>
      </TableHoverScope>
    </div>
  );
}
