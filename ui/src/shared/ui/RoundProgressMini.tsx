import type { CSSProperties } from "react";

import { cn } from "../lib/format";
import { formatPercent, getRoundProgressMetrics, type RoundProgressStatus } from "../lib/roundProgress";

export type RoundProgressMiniMode = "time" | "take";

export function toggleProgressDisplayMode(current: RoundProgressMiniMode): RoundProgressMiniMode {
  return current === "time" ? "take" : "time";
}

interface RoundProgressMiniProps {
  status: RoundProgressStatus;
  kickedAt: string;
  scheduledEndAt?: string | null;
  endAt?: string | null;
  availableAmount?: string | null;
  initialAvailable?: string | null;
  soldAmount?: string | null;
  fromTokenSymbol?: string | null;
  takeCount?: number | null;
  mode?: RoundProgressMiniMode;
  width?: number;
  className?: string;
  showFigure?: boolean;
}

/** The meter keeps the round's own tone: live green, an unsold expiry amber, the rest neutral. */
function meterTone(status: RoundProgressStatus, mode: RoundProgressMiniMode, soldOut: boolean): string | undefined {
  if (status === "live") return "var(--color-active-mark)";
  if (status === "expired" && !(mode === "take" && soldOut)) return "var(--color-warning-mark)";
  return undefined;
}

export default function RoundProgressMini({
  status,
  kickedAt,
  scheduledEndAt,
  endAt,
  availableAmount,
  initialAvailable,
  soldAmount,
  fromTokenSymbol,
  takeCount,
  mode = "time",
  width = 72,
  className,
  showFigure = true,
}: RoundProgressMiniProps) {
  const {
    timePercent,
    elapsedSeconds,
    scheduledDurationSeconds,
    soldPercent,
    soldDetail,
    timeDetail,
    showEarlyMarker,
    showSoldCompleteMarker,
  } = getRoundProgressMetrics({
    status,
    kickedAt,
    scheduledEndAt,
    endAt,
    availableAmount,
    initialAvailable,
    soldAmount,
    fromTokenSymbol,
  });

  // A round that sells out in seconds would otherwise draw an empty bar; a
  // small visual floor keeps an early close legible. The title keeps the truth.
  const visualFloor =
    showEarlyMarker && elapsedSeconds !== null && scheduledDurationSeconds
      ? (Math.min(60 * 60, scheduledDurationSeconds) / scheduledDurationSeconds) * 100
      : 0;
  const displayTimePercent = showEarlyMarker ? Math.max(timePercent, visualFloor) : timePercent;
  const displayPercent = mode === "take" ? soldPercent : displayTimePercent;
  const showMarker = mode === "time" && showEarlyMarker;
  const takeLabel = mode === "take" && takeCount !== null && takeCount !== undefined
    ? ` · ${takeCount} ${takeCount === 1 ? "take" : "takes"}`
    : "";
  const title = mode === "take" ? `${soldDetail}${takeLabel}` : timeDetail;

  return (
    <span className={cn("meter", className)} title={title}>
      <span className="bar" style={{ width, "--tone": meterTone(status, mode, showSoldCompleteMarker) } as CSSProperties}>
        <i style={{ width: `${displayPercent}%` }} />
        {showMarker ? <span className="bar-mark" style={{ left: `${displayPercent}%` }} aria-hidden="true" /> : null}
      </span>
      {showFigure ? <span className="meter-figure">{formatPercent(displayPercent)}</span> : null}
    </span>
  );
}
