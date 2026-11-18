import type { CSSProperties } from "react";

import { cn } from "../lib/format";

export type StatusKind =
  | "active"
  | "completed"
  | "kickable"
  | "idle"
  | "degraded"
  | "live"
  | "sold_out"
  | "expired"
  | "settled";

interface StatusBadgeProps {
  status: StatusKind;
  className?: string;
  /** Hide the word and keep the dot, for the narrowest layouts. The word stays in the title. */
  dotOnly?: boolean;
}

const labelMap: Record<StatusKind, string> = {
  active: "Live",
  completed: "Complete",
  kickable: "Kickable",
  idle: "Waiting",
  degraded: "Alert",
  live: "Live",
  sold_out: "Sold",
  expired: "Expired",
  settled: "Settled",
};

/**
 * Quiet normal, loud exception: a live round is the one mark that moves, an
 * expired lot is the one that warns, and finished rounds stay neutral.
 */
const toneMap: Record<StatusKind, { tone: string; ring?: boolean; live?: boolean }> = {
  active: { tone: "var(--color-active-mark)", live: true },
  live: { tone: "var(--color-active-mark)", live: true },
  completed: { tone: "var(--color-primary)" },
  sold_out: { tone: "color-mix(in srgb, var(--color-primary) 62%, transparent)" },
  settled: { tone: "var(--color-faint)", ring: true },
  expired: { tone: "var(--color-warning-mark)" },
  kickable: { tone: "var(--color-kickable)" },
  idle: { tone: "var(--color-faint)", ring: true },
  degraded: { tone: "var(--color-negative)" },
};

export function statusLabel(status: StatusKind): string {
  return labelMap[status];
}

export function StatusDot({ status, className }: { status: StatusKind; className?: string }) {
  const tone = toneMap[status];
  return (
    <span
      aria-hidden="true"
      className={cn("status-dot", tone.ring && "is-ring", tone.live && "is-live", className)}
      style={{ "--tone": tone.tone } as CSSProperties}
    />
  );
}

export default function StatusBadge({ status, className, dotOnly = false }: StatusBadgeProps) {
  return (
    <span className={cn("status", className)} title={dotOnly ? labelMap[status] : undefined}>
      <StatusDot status={status} />
      {dotOnly ? <span className="sr-only">{labelMap[status]}</span> : <span>{labelMap[status]}</span>}
    </span>
  );
}
