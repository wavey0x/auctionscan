import type { CSSProperties } from "react";
import { CheckCircle2 } from "lucide-react";

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
 * Each ending has its own shape as well as its tone: a live round is the one
 * mark that moves, a sold round carries a small muted check, an expired lot is
 * the one that warns, and a settled round is a hollow ring.
 */
const toneMap: Record<StatusKind, { tone: string; ring?: boolean; live?: boolean; check?: boolean }> = {
  active: { tone: "var(--color-active-mark)", live: true },
  live: { tone: "var(--color-active-mark)", live: true },
  completed: { tone: "var(--color-primary)" },
  sold_out: { tone: "var(--color-sold-mark)", check: true },
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
  // Every mark sits in the same slot, so the words line up down a column.
  return (
    <span aria-hidden="true" className={cn("status-mark", className)}>
      {tone.check ? (
        <CheckCircle2 className="status-check" strokeWidth={1.7} style={{ color: tone.tone }} />
      ) : (
        <span
          className={cn("status-dot", tone.ring && "is-ring", tone.live && "is-live")}
          style={{ "--tone": tone.tone } as CSSProperties}
        />
      )}
    </span>
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
