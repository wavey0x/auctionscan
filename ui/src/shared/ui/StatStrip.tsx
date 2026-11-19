import type { CSSProperties, ReactNode } from "react";

import { cn } from "../lib/format";

export function Stat({
  label,
  value,
  suffix,
  note,
  title,
  className,
  loading = false,
}: {
  label: ReactNode;
  value: ReactNode;
  suffix?: ReactNode;
  note?: ReactNode;
  title?: string;
  className?: string;
  loading?: boolean;
}) {
  return (
    <div className={cn("stat", className)} title={title}>
      <div className="stat-label"><span>{label}</span></div>
      {loading ? (
        <div className="flex h-[26px] items-center"><span className="skeleton-bar w-20" /></div>
      ) : (
        <div className="stat-value">
          {value}
          {suffix ? <small>{suffix}</small> : null}
          {note ? <span className="stat-note">{note}</span> : null}
        </div>
      )}
    </div>
  );
}

/** One card of at most five figures: totals for the filters in scope. */
export default function StatStrip({
  children,
  count,
  className,
  label,
}: {
  children: ReactNode;
  count: number;
  className?: string;
  label: string;
}) {
  return (
    <section aria-label={label} className={cn("strip", className)} style={{ "--n": count } as CSSProperties}>
      {children}
    </section>
  );
}
