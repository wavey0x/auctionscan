import { cn } from "../lib/format";
import { versionLabel } from "../lib/protocol";

interface AuctionVersionBadgeProps {
  version?: string | null;
  className?: string;
}

export default function AuctionVersionBadge({ version, className }: AuctionVersionBadgeProps) {
  const displayVersion = versionLabel(version);
  if (!displayVersion) {
    return null;
  }

  return <span className={cn("version-badge font-mono", className)}>{displayVersion}</span>;
}
