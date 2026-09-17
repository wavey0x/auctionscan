import { useChainInfo } from "../lib/chains";
import { cn } from "../lib/format";
import ChainIcon from "./ChainIcon";

interface ChainPillProps {
  chainId: number;
  className?: string;
  size?: "xs" | "sm" | "md";
}

const sizeClasses = {
  xs: {
    root: "gap-1 text-[11px] leading-none text-tertiary",
    icon: "opacity-70",
  },
  sm: {
    root: "gap-2 text-data text-primary",
    icon: "",
  },
  md: {
    root: "gap-2 text-body text-primary",
    icon: "",
  },
};

export default function ChainPill({ chainId, className, size = "sm" }: ChainPillProps) {
  const { chain } = useChainInfo(chainId);
  const label = chain?.short_name || chain?.name || `Chain ${chainId}`;
  const classes = sizeClasses[size];

  return (
    <span className={cn("inline-flex items-center", classes.root, className)}>
      <ChainIcon chainId={chainId} size={size} className={classes.icon} />
      <span>{label}</span>
    </span>
  );
}
