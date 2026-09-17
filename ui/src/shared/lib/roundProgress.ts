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
  fromTokenSymbol,
}: {
  status: RoundProgressStatus;
  kickedAt: string;
  scheduledEndAt?: string | null;
  endAt?: string | null;
  availableAmount?: string | null;
  initialAvailable?: string | null;
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
  const formattedSold = formatAmount(sold);
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

export function roundProgressSummary(
  round: {
    status: RoundProgressStatus;
    kicked_at: string;
    scheduled_end_at?: string | null;
    end_at?: string | null;
    available_amount?: string | null;
    initial_available?: string | null;
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
    fromTokenSymbol: round.from_token_symbol,
  });

  return mode === "take"
    ? `${formatPercent(metrics.soldPercent)} take`
    : `${formatPercent(metrics.timePercent)} time`;
}
