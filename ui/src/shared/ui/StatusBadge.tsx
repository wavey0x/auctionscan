import type { CSSProperties } from "react";

import { cn } from "../lib/format";

interface StatusBadgeProps {
  status:
    | "active"
    | "completed"
    | "kickable"
    | "idle"
    | "degraded"
    | "live"
    | "sold_out"
    | "expired"
    | "settled";
  className?: string;
}

const labelMap: Record<StatusBadgeProps["status"], string> = {
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

const toneMap: Record<StatusBadgeProps["status"], string> = {
  active: "border-divider-strong text-active",
  completed: "border-divider-strong text-complete",
  kickable: "border-divider-strong text-kickable",
  idle: "border-divider-strong text-secondary",
  degraded: "border-divider-strong text-negative",
  live: "border-divider-strong text-active",
  sold_out: "border-divider-strong text-complete",
  expired: "border-divider-strong text-warning",
  settled: "border-divider-strong",
};

const styleMap: Partial<Record<StatusBadgeProps["status"], CSSProperties>> = {
  settled: { color: "var(--color-settled)" },
};

export default function StatusBadge({ status, className }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex min-w-[4.5rem] items-center justify-center rounded-md border px-1.5 py-0.5 text-[11px] leading-4",
        toneMap[status],
        className,
      )}
      style={styleMap[status]}
    >
      {labelMap[status]}
    </span>
  );
}
