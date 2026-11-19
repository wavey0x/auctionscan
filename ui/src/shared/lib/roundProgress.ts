import { formatAmount, formatDuration, parseTimestamp } from "./format";

export type RoundProgressStatus = "live" | "sold_out" | "expired" | "settled";

function toUnixSeconds(value: string | null | undefined): number | null {
  const parsed = parseTimestamp(value);
  if (!parsed) {
    return null;
  }
  return Math.floor(parsed.getTime() / 1000);
}

export function clampPercent(value: number): number {
  return Math.max(0, Math.min(100, value));
}

export function formatPercent(value: number): string {
  return `${Math.round(clampPercent(value))}%`;
}

export function getRoundProgressMetrics({
  status,
  kickedAt,
  scheduledEndAt,
  endAt,
  availableAmount,
  initialAvailable,
  soldAmount,
  fromTokenSymbol,
}: {
  status: RoundProgressStatus;
  kickedAt: string;
  scheduledEndAt?: string | null;
  endAt?: string | null;
  availableAmount?: string | null;
  initialAvailable?: string | null;
  soldAmount?: string | null;
  fromTokenSymbol?: string | null;
}) {
  const kickedAtSec = toUnixSeconds(kickedAt);
  const scheduledEndAtSec = toUnixSeconds(scheduledEndAt);
  const endAtSec = toUnixSeconds(endAt);
  const nowSec = Math.floor(Date.now() / 1000);

  const hasTimeline = kickedAtSec !== null && scheduledEndAtSec !== null && scheduledEndAtSec > kickedAtSec;
  const scheduledDuration = hasTimeline ? scheduledEndAtSec - kickedAtSec : null;
  const elapsedTime = hasTimeline
    ? Math.max(
        0,
        Math.min(
          (status === "live" ? nowSec : endAtSec ?? scheduledEndAtSec) - kickedAtSec,
          scheduledDuration!,
        ),
      )
    : null;
  const timePercent = hasTimeline && scheduledDuration
    ? clampPercent((elapsedTime! / scheduledDuration) * 100)
    : 0;

  const closedEarly =
    status !== "live" &&
    endAtSec !== null &&
    scheduledEndAtSec !== null &&
    endAtSec < scheduledEndAtSec;
  const showEarlyMarker = closedEarly && (status === "sold_out" || status === "settled");

  const timeDetail = !hasTimeline || scheduledDuration === null || elapsedTime === null
    ? "Schedule unavailable"
    : status === "live"
      ? `${formatDuration(elapsedTime)} of ${formatDuration(scheduledDuration)}`
      : closedEarly
        ? `Closed after ${formatDuration(elapsedTime)}`
        : status === "expired"
          ? "Expired"
          : "Settled";

  const initial = Number(initialAvailable ?? 0);
  const available = Number(availableAmount ?? 0);
  const hasInventory = Number.isFinite(initial) && initial > 0 && Number.isFinite(available);
  const sold = hasInventory
    ? Math.min(initial, Math.max(0, initial - Math.max(0, available)))
    : 0;
  const soldPercent = hasInventory ? clampPercent((sold / initial) * 100) : 0;
  // The API already derives this exactly; only the percentage needs arithmetic.
  const formattedSold = formatAmount(soldAmount ?? sold);
  const formattedInitial = formatAmount(initialAvailable);
  const tokenSuffix = fromTokenSymbol ? ` ${fromTokenSymbol}` : "";
  const soldDetail = hasInventory
    ? `${formattedSold}${tokenSuffix} of ${formattedInitial}${tokenSuffix}`
    : "Inventory unavailable";
  const showSoldCompleteMarker = hasInventory && soldPercent >= 100;

  return {
    timePercent,
    elapsedSeconds: elapsedTime,
    scheduledDurationSeconds: scheduledDuration,
    soldPercent,
    timeDetail,
    elapsedDurationLabel: elapsedTime === null ? null : formatDuration(elapsedTime),
    soldDetail,
    showEarlyMarker,
    showSoldCompleteMarker,
  };
}

/** Sold share at or above this is a lot that cleared but for rounding dust. */
const DUST_SOLD_PERCENT = 99.99;

export type SaleOutcome =
  | { kind: "cleared" }
  | { kind: "none" }
  | { kind: "dust" }
  | { kind: "partial"; percent: number };

/**
 * What became of a round's lot, or null when its inventory is unknown. It is
 * decided on the remaining amount itself: one smallest unit left of a large
 * lot is below what a percentage can resolve.
 */
export function getSaleOutcome(round: {
  initial_available?: string | null;
  available_amount?: string | null;
  take_count: number;
}): SaleOutcome | null {
  const initial = Number(round.initial_available ?? 0);
  const left = Number(round.available_amount ?? 0);
  if (!(initial > 0) || !Number.isFinite(left)) return null;
  if (left <= 0) return { kind: "cleared" };
  if (round.take_count === 0) return { kind: "none" };
  const percent = clampPercent(((initial - left) / initial) * 100);
  return percent >= DUST_SOLD_PERCENT ? { kind: "dust" } : { kind: "partial", percent: Math.floor(percent) };
}

export function roundProgressSummary(
  round: {
    status: RoundProgressStatus;
    kicked_at: string;
    scheduled_end_at?: string | null;
    end_at?: string | null;
    available_amount?: string | null;
    initial_available?: string | null;
    sold_amount?: string | null;
    from_token_symbol?: string | null;
  },
  mode: "time" | "take",
): string {
  const metrics = getRoundProgressMetrics({
    status: round.status,
    kickedAt: round.kicked_at,
    scheduledEndAt: round.scheduled_end_at,
    endAt: round.end_at,
    availableAmount: round.available_amount,
    initialAvailable: round.initial_available,
    soldAmount: round.sold_amount,
    fromTokenSymbol: round.from_token_symbol,
  });

  return mode === "take"
    ? `${formatPercent(metrics.soldPercent)} take`
    : `${formatPercent(metrics.timePercent)} time`;
}
