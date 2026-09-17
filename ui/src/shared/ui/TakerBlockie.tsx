import { blo } from "blo";
import { getAddress } from "viem";

import { cn } from "../lib/format";

const blockieSrcCache = new Map<string, string>();

function normalizeBlockieAddress(address?: string | null): `0x${string}` | null {
  if (!address) {
    return null;
  }

  const trimmed = address.trim();
  if (!trimmed || !trimmed.startsWith("0x")) {
    return null;
  }

  try {
    return getAddress(trimmed).toLowerCase() as `0x${string}`;
  } catch {
    return trimmed.toLowerCase() as `0x${string}`;
  }
}

function blockieSrc(address?: string | null, size = 32): string | null {
  const normalized = normalizeBlockieAddress(address);
  if (!normalized) {
    return null;
  }

  const cacheKey = `${normalized}:${size}`;
  const cached = blockieSrcCache.get(cacheKey);
  if (cached) {
    return cached;
  }

  const src = blo(normalized, size);
  blockieSrcCache.set(cacheKey, src);
  return src;
}

interface TakerBlockieProps {
  address?: string | null;
  size?: number;
  className?: string;
}

export default function TakerBlockie({
  address,
  size = 18,
  className,
}: TakerBlockieProps) {
  const src = blockieSrc(address, Math.max(24, size));
  if (!src) {
    return null;
  }

  return (
    <img
      src={src}
      alt=""
      aria-hidden="true"
      width={size}
      height={size}
      className={cn(
        "shrink-0 rounded-[4px] border border-divider-subtle bg-surface",
        className,
      )}
    />
  );
}
