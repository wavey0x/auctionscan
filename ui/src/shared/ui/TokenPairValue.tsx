import { ArrowRight } from "lucide-react";

import { cn } from "../lib/format";
import TokenValue from "./TokenValue";

type TokenLike = {
  address?: string | null;
  symbol?: string | null;
  logo_url?: string | null;
  chain_id?: number | null;
};

interface TokenPairValueProps {
  fromToken?: TokenLike | null;
  toToken?: TokenLike | null;
  chainId?: number | null;
  className?: string;
  showCopy?: boolean;
  size?: "sm" | "md";
}

export default function TokenPairValue({
  fromToken,
  toToken,
  chainId,
  className,
  showCopy = false,
  size = "sm",
}: TokenPairValueProps) {
  return (
    <span className={cn("inline-flex min-w-0 items-center gap-1.5", className)}>
      <TokenValue token={fromToken} chainId={chainId} showCopy={showCopy} size={size} />
      <ArrowRight
        className={cn("shrink-0 text-tertiary", size === "md" ? "h-4 w-4" : "h-3.5 w-3.5")}
        strokeWidth={1.5}
        aria-hidden="true"
      />
      <TokenValue token={toToken} chainId={chainId} showCopy={showCopy} size={size} />
    </span>
  );
}
