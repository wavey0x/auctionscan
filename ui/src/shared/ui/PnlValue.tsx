import { cn, coerceFiniteNumber, formatSignedPercent, formatSignedUsdDelta, signedMetricTone } from "../lib/format";

/**
 * Auction PnL against the market quote: the percent carries the tone and the
 * sign, the USD delta follows in a quieter figure on the same line. Where a
 * view states each figure once, `show` picks the one it gives; that figure
 * then carries the tone and the sign alone.
 */
export default function PnlValue({
  percent,
  usd,
  align = "left",
  stacked = false,
  show = "both",
  className,
  title,
}: {
  percent: string | number | null | undefined;
  usd: string | number | null | undefined;
  align?: "left" | "right";
  stacked?: boolean;
  show?: "both" | "percent" | "usd";
  className?: string;
  title?: string;
}) {
  const pnlPercent = coerceFiniteNumber(percent);
  const pnlUsdValue = coerceFiniteNumber(usd);
  const single = show === "percent" ? pnlPercent : show === "usd" ? pnlUsdValue : undefined;
  const empty = single === undefined ? pnlPercent === null && pnlUsdValue === null : single === null;

  if (empty) {
    return (
      <span className={cn("font-mono text-faint", align === "right" && "block text-right", className)} title={title}>—</span>
    );
  }

  if (single !== undefined) {
    return (
      <span
        className={cn("whitespace-nowrap font-mono", signedMetricTone(single), align === "right" && "block text-right", className)}
        title={title}
      >
        {show === "usd" ? formatSignedUsdDelta(single) : formatSignedPercent(single)}
      </span>
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
      <span className={cn("whitespace-nowrap", signedMetricTone(pnlPercent ?? pnlUsdValue))}>{formatSignedPercent(pnlPercent)}</span>
      <span className="usd-note whitespace-nowrap">{formatSignedUsdDelta(pnlUsdValue)}</span>
    </span>
  );
}
