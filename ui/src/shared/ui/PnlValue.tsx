import { cn, formatSignedUsdDelta, formatUnsignedPercent, signedMetricTone } from "../lib/format";

function coerceFiniteNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export default function PnlValue({
  percent,
  usd,
  align = "left",
  compact = false,
  className,
}: {
  percent: string | number | null | undefined;
  usd: string | number | null | undefined;
  align?: "left" | "right";
  compact?: boolean;
  className?: string;
}) {
  const pnlPercent = coerceFiniteNumber(percent);
  const pnlUsdValue = coerceFiniteNumber(usd);
  const directionValue = pnlPercent ?? pnlUsdValue;
  const alignClass = align === "right" ? "items-end text-right" : "items-start text-left";

  return (
    <div className={cn("flex flex-col gap-[2px] font-mono leading-[0.92rem]", alignClass, className)}>
      <div
        className={cn(
          "w-full truncate whitespace-nowrap leading-none",
          compact ? "text-[12px]" : "text-[13px]",
          signedMetricTone(directionValue),
        )}
      >
        {formatUnsignedPercent(pnlPercent)}
      </div>
      <div className="w-full truncate whitespace-nowrap font-mono text-[10px] leading-none text-tertiary">
        {formatSignedUsdDelta(pnlUsdValue)}
      </div>
    </div>
  );
}
