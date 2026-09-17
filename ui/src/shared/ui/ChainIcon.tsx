import ethereumIcon from "../assets/ethereum.svg";
import { useChainInfo } from "../lib/chains";
import { cn } from "../lib/format";

interface ChainIconProps {
  chainId: number;
  className?: string;
  size?: "xs" | "sm" | "md";
}

const sizeClasses = {
  xs: "h-3 w-3 text-[8px]",
  sm: "h-4 w-4 text-[10px]",
  md: "h-5 w-5 text-[11px]",
};

export default function ChainIcon({ chainId, className, size = "sm" }: ChainIconProps) {
  const { chain } = useChainInfo(chainId);
  const label = chain?.short_name || chain?.name || `Chain ${chainId}`;
  const isEthereum = chainId === 1;
  const icon = isEthereum ? ethereumIcon : chain?.icon;

  if (icon) {
    return (
      <img
        src={icon}
        alt={label}
        title={label}
        className={cn(
          "shrink-0",
          isEthereum ? "object-contain dark:invert" : "rounded-full border border-divider-subtle object-cover",
          sizeClasses[size],
          className,
        )}
      />
    );
  }

  return (
    <span
      title={label}
      className={cn(
        "inline-flex items-center justify-center rounded-full border border-divider-strong text-tertiary",
        sizeClasses[size],
        className,
      )}
    >
      {label.slice(0, 1).toUpperCase()}
    </span>
  );
}
