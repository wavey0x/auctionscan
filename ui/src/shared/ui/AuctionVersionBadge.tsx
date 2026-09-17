import { cn } from "../lib/format";

interface AuctionVersionBadgeProps {
  version?: string | null;
  className?: string;
}

export default function AuctionVersionBadge({ version, className }: AuctionVersionBadgeProps) {
  if (!version) {
    return null;
  }

  const displayVersion = version.startsWith("v") ? version : `v${version}`;

  return <span className={cn("version-badge font-mono", className)}>{displayVersion}</span>;
}
