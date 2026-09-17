import { useEffect, useState, type CSSProperties } from "react";

import { cn } from "../lib/format";

export const TOKEN_LOGO_FALLBACK_URL = "/token-placeholder.svg";

interface TokenLogoProps {
  logoUrl?: string | null;
  symbol?: string | null;
  className?: string;
  size?: "sm" | "md";
}

const sizeMap: Record<NonNullable<TokenLogoProps["size"]>, string> = {
  sm: "0.875rem",
  md: "1rem",
};

export default function TokenLogo({
  logoUrl,
  symbol,
  className,
  size = "sm",
}: TokenLogoProps) {
  const primaryLogoUrl = logoUrl || null;
  const [failedLogoUrl, setFailedLogoUrl] = useState<string | null>(null);
  const isUsingFallback = !primaryLogoUrl || failedLogoUrl === primaryLogoUrl;
  const resolvedLogoUrl = isUsingFallback ? TOKEN_LOGO_FALLBACK_URL : primaryLogoUrl;

  useEffect(() => {
    setFailedLogoUrl(null);
  }, [primaryLogoUrl]);

  return (
    <span
      className={cn("token-logo-slot", className)}
      style={{ "--token-logo-size": sizeMap[size] } as CSSProperties}
      aria-hidden="true"
    >
      <img
        src={resolvedLogoUrl}
        alt={symbol || ""}
        className="token-logo"
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={
          isUsingFallback || !primaryLogoUrl
            ? undefined
            : () => setFailedLogoUrl(primaryLogoUrl)
        }
      />
    </span>
  );
}
