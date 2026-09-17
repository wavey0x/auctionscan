import { cn, formatAddress } from "../lib/format";
import CopyIconButton from "./CopyIconButton";
import { useTableHover } from "./TableHoverContext";
import TokenLogo from "./TokenLogo";

type TokenLike = {
  address?: string | null;
  symbol?: string | null;
  logo_url?: string | null;
  chain_id?: number | null;
};

interface TokenValueProps {
  token?: TokenLike | null;
  address?: string | null;
  symbol?: string | null;
  logoUrl?: string | null;
  chainId?: number | null;
  className?: string;
  showCopy?: boolean;
  size?: "sm" | "md";
  tooltip?: string | null;
}

const textSizeClasses = {
  sm: "text-primary",
  md: "text-[1.05rem] leading-none text-primary",
};

export default function TokenValue({
  token,
  address,
  symbol,
  logoUrl,
  className,
  showCopy = true,
  size = "sm",
  tooltip,
}: TokenValueProps) {
  const tokenAddress = address ?? token?.address ?? null;
  const tokenSymbol = symbol ?? token?.symbol ?? (tokenAddress ? formatAddress(tokenAddress, 6) : "—");
  const tokenLogoUrl = logoUrl ?? token?.logo_url ?? null;
  const hover = useTableHover("token", tokenAddress);

  return (
    <span
      className={cn(
        "identity-inline",
        className,
        hover.inScope ? "hover-match-target" : null,
        hover.isHovered ? "hover-match-active" : null,
      )}
      data-tooltip={tooltip || undefined}
      onMouseEnter={hover.bind?.onMouseEnter}
      onMouseLeave={hover.bind?.onMouseLeave}
      onFocusCapture={hover.bind?.onFocusCapture}
      onBlurCapture={hover.bind?.onBlurCapture}
    >
      <TokenLogo logoUrl={tokenLogoUrl} symbol={tokenSymbol} size={size} />
      <span className={cn("font-mono", textSizeClasses[size])}>{tokenSymbol || "—"}</span>
      {showCopy && tokenAddress ? (
        <CopyIconButton
          valueToCopy={tokenAddress}
          title={`Copy token address ${tokenAddress}`}
          ariaLabel={`Copy token address ${tokenAddress}`}
        />
      ) : null}
    </span>
  );
}
