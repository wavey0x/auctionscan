import { Check } from "lucide-react";

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
  fromTokenSymbol?: string | null;
  takeCount?: number | null;
  mode?: RoundProgressMiniMode;
  onToggleMode?: () => void;
}

function timeMeterFillClass(status: RoundProgressStatus) {
  if (status === "expired") {
    return "bg-warning";
  }
  return "bg-complete";
}

function takeMeterFillClass(status: RoundProgressStatus, isComplete: boolean) {
  if (!isComplete && status === "expired") {
    return "bg-warning";
  }
  return "bg-active";
}

export default function RoundProgressMini({
  status,
  kickedAt,
  scheduledEndAt,
  endAt,
  availableAmount,
  initialAvailable,
  fromTokenSymbol,
  takeCount,
  mode = "time",
  onToggleMode,
}: RoundProgressMiniProps) {
  const {
    timePercent,
    elapsedSeconds,
    elapsedDurationLabel,
    scheduledDurationSeconds,
    soldPercent,
    soldDetail,
    showEarlyMarker,
    showSoldCompleteMarker,
  } = getRoundProgressMetrics({
    status,
    kickedAt,
    scheduledEndAt,
    endAt,
    availableAmount,
    initialAvailable,
    fromTokenSymbol,
  });

  // The compact table meter is tiny enough that very fast sold-out rounds can
  // look like they made no progress at all. Apply a small visual floor only to
  // this compact representation so early closes remain legible at a glance.
  // The tooltip still reports the real elapsed duration.
  const compactVisualFloorPercent =
    showEarlyMarker && elapsedSeconds !== null && scheduledDurationSeconds
      ? (Math.min(60 * 60, scheduledDurationSeconds) / scheduledDurationSeconds) * 100
      : 0;
  const displayTimePercent =
    showEarlyMarker
      ? Math.max(timePercent, compactVisualFloorPercent)
      : timePercent;

  const displayPercent = mode === "take" ? soldPercent : displayTimePercent;
  const detailLabel = mode === "take" ? soldDetail : elapsedDurationLabel;
  const tooltipAnchorClass =
    displayPercent >= 92
      ? "right-0 translate-x-0"
      : displayPercent <= 8
        ? "left-0 translate-x-0"
        : "-translate-x-1/2";
  const fillClassName =
    mode === "take"
      ? takeMeterFillClass(status, showSoldCompleteMarker)
      : timeMeterFillClass(status);
  const markerPercent = mode === "take" ? 100 : displayTimePercent;
  const showMarker = mode === "take" ? showSoldCompleteMarker : showEarlyMarker;
  const percentLabel = formatPercent(displayPercent);
  const takeCountLabel = mode === "take" && takeCount !== null && takeCount !== undefined
    ? `(${takeCount})`
    : null;
  const meter = (
    <div className="min-w-[11rem] space-y-1.5">
      <div className="flex items-center gap-1.5">
        <div className="group relative h-1.5 flex-1 overflow-visible rounded-full border border-divider-strong bg-background">
          {detailLabel ? (
            <div
              className={cn(
                "pointer-events-none absolute top-0 z-20 -translate-y-[calc(100%+0.375rem)] opacity-0 transition-opacity duration-150 group-hover:opacity-100",
                tooltipAnchorClass,
              )}
              style={
                displayPercent > 8 && displayPercent < 92
                  ? { left: `${displayPercent}%` }
                  : undefined
              }
            >
              <div className="rounded-md border border-divider-strong bg-background px-2 py-1 font-mono text-[11px] text-primary">
                {detailLabel}
              </div>
            </div>
          ) : null}
          <div
            className={cn("h-full rounded-full transition-[width]", fillClassName)}
            style={{ width: `${displayPercent}%` }}
          />
          {showMarker ? (
            <div
              className="absolute top-1/2 z-10 -translate-y-1/2 -translate-x-1/2"
              style={{ left: `${markerPercent}%` }}
            >
              <div className="progress-marker flex h-[9px] w-[9px] items-center justify-center rounded-full border text-white shadow-sm">
                <Check className="h-1.5 w-1.5" strokeWidth={2.5} />
              </div>
            </div>
          ) : null}
        </div>
        <span className="shrink-0 whitespace-nowrap text-left font-mono text-[11px]">
          <span className="text-primary">{percentLabel}</span>
          {takeCountLabel ? <span className="text-tertiary"> {takeCountLabel}</span> : null}
        </span>
      </div>
    </div>
  );

  if (!onToggleMode) {
    return meter;
  }

  return (
    <button
      type="button"
      className="block text-left"
      title={mode === "time" ? "Show take progress" : "Show time progress"}
      onClick={(event) => {
        event.stopPropagation();
        onToggleMode();
      }}
    >
      {meter}
    </button>
  );
}
