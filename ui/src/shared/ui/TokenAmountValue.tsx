import { cn, formatAmount, formatFullAmount } from "../lib/format";
import MetricCoverage from "./MetricCoverage";
import TokenValue from "./TokenValue";

interface TokenAmountValueProps {
  amount?: string | number | null;
  estimatedAmount?: string | null;
  coverage?: { count: number; total: number };
  address?: string | null;
  symbol?: string | null;
  logoUrl?: string | null;
  chainId?: number | null;
  align?: "start" | "end";
  className?: string;
}

export default function TokenAmountValue({
  amount,
  estimatedAmount,
  coverage,
  address,
  symbol,
  logoUrl,
  chainId,
  align = "start",
  className,
}: TokenAmountValueProps) {
  const isEstimate = amount == null && estimatedAmount != null;
  const displayed = isEstimate ? estimatedAmount : amount;
  const label = [isEstimate ? "Est." : null, formatAmount(displayed), symbol].filter(Boolean).join(" ").trim() || "—";
  const fullLabel = [isEstimate ? "Estimated" : null, formatFullAmount(displayed), symbol].filter(Boolean).join(" ").trim() || null;

  return (
    <span className={cn("flex w-full items-center gap-1.5", align === "end" ? "justify-end" : "justify-start", className)}>
      <TokenValue
        address={address}
        symbol={label}
        tooltip={fullLabel}
        logoUrl={logoUrl}
        chainId={chainId}
        showCopy={false}
      />
      {coverage ? <MetricCoverage {...coverage} /> : null}
    </span>
  );
}
