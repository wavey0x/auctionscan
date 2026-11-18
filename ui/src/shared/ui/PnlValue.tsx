import { cn, coerceFiniteNumber, formatSignedPercent, formatSignedUsdDelta, signedMetricTone } from "../lib/format";

/**
 * Auction PnL against the market quote: the percent carries the tone and the
 * sign, the USD delta follows in a quieter figure on the same line.
 */
export default function PnlValue({
  percent,
  usd,
  align = "left",
  stacked = false,
  className,
  title,
}: {
  percent: string | number | null | undefined;
  usd: string | number | null | undefined;
  align?: "left" | "right";
  stacked?: boolean;
  compact?: boolean;
  className?: string;
  title?: string;
}) {
  const pnlPercent = coerceFiniteNumber(percent);
  const pnlUsdValue = coerceFiniteNumber(usd);
  const directionValue = pnlPercent ?? pnlUsdValue;
  const empty = pnlPercent === null && pnlUsdValue === null;

  if (empty) {
    return (
      <span className={cn("font-mono text-faint", align === "right" && "block text-right", className)} title={title}>—</span>
    );
  }

  return (
    <span
      className={cn(
        "inline-flex min-w-0 font-mono",
        stacked ? "flex-col gap-0.5" : "items-baseline gap-1.5",
        align === "right" && (stacked ? "items-end" : "justify-end"),
        className,
      )}
      title={title}
    >
      <span className={cn("whitespace-nowrap", signedMetricTone(directionValue))}>{formatSignedPercent(pnlPercent)}</span>
      <span className="usd-note whitespace-nowrap">{formatSignedUsdDelta(pnlUsdValue)}</span>
    </span>
  );
}
