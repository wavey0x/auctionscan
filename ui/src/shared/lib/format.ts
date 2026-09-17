import clsx, { type ClassValue } from "clsx";
import { format, formatDistanceToNowStrict, fromUnixTime } from "date-fns";
import { getAddress, isAddress } from "viem";

export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

export function parseTimestamp(value: string | number | Date | null | undefined): Date | null {
  if (value === null || value === undefined) {
    return null;
  }
  if (value instanceof Date) {
    return value;
  }
  if (typeof value === "number") {
    return fromUnixTime(value);
  }
  if (/^\d+$/.test(value)) {
    return fromUnixTime(Number(value));
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string | number | Date | null | undefined): string {
  const date = parseTimestamp(value);
  return date ? format(date, "MMM dd, yyyy HH:mm:ss") : "—";
}

export function formatCompactDateTime(value: string | number | Date | null | undefined): string {
  const date = parseTimestamp(value);
  return date ? format(date, "MMM d HH:mm") : "—";
}

export function formatLongRelativeTime(value: string | number | Date | null | undefined): string {
  const date = parseTimestamp(value);
  if (!date) return "—";

  const deltaMs = date.getTime() - Date.now();
  if (Math.abs(deltaMs) < 60_000) {
    return deltaMs >= 0 ? "in less than a minute" : "less than a minute ago";
  }

  return formatDistanceToNowStrict(date, { addSuffix: true });
}

export function formatCompactRelativeTime(value: string | number | Date | null | undefined): string {
  const date = parseTimestamp(value);
  if (!date) return "—";

  const deltaMs = Date.now() - date.getTime();
  const absMs = Math.abs(deltaMs);

  if (absMs < 60_000) {
    return "now";
  }

  const minuteMs = 60_000;
  const hourMs = 60 * minuteMs;
  const dayMs = 24 * hourMs;
  const weekMs = 7 * dayMs;
  const monthMs = 30 * dayMs;
  const yearMs = 365 * dayMs;

  const formatUnit = (ms: number, suffix: string) => `${Math.floor(absMs / ms)}${suffix}`;

  if (absMs < hourMs) return formatUnit(minuteMs, "m");
  if (absMs < dayMs) return formatUnit(hourMs, "h");
  if (absMs < weekMs) return formatUnit(dayMs, "d");
  if (absMs < monthMs) return formatUnit(weekMs, "w");
  if (absMs < yearMs) return formatUnit(monthMs, "mo");
  return formatUnit(yearMs, "y");
}

export function formatAmount(value: string | number | null | undefined, maximumFractionDigits = 4): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return String(value);
  }

  const abs = Math.abs(numeric);
  if (abs >= 1_000_000_000) return `${(numeric / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${(numeric / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${(numeric / 1_000).toFixed(2)}K`;

  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits,
  }).format(numeric);
}

export function formatFullAmount(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return String(value);
  }
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 18,
  }).format(numeric);
}

export function formatPrice(value: string | number | null | undefined, maximumFractionDigits = 6): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return String(value);
  }

  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits,
  }).format(numeric);
}

export function formatUsd(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return String(value);
  }

  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: numeric >= 100 ? 0 : 2,
    maximumFractionDigits: numeric >= 100 ? 0 : 2,
  }).format(numeric);
}

export function formatMiddleEllipsis(
  value: string | null | undefined,
  leading = 6,
  trailing = 4,
): string {
  if (!value) return "—";
  if (trailing <= 0) {
    return value.length <= leading ? value : `${value.slice(0, leading)}…`;
  }
  if (value.length <= leading + trailing + 1) {
    return value;
  }
  return `${value.slice(0, leading)}…${value.slice(-trailing)}`;
}

export function formatAddress(
  value: string | null | undefined,
  width = 6,
  tailWidth = 4,
): string {
  if (!value) return "—";
  const display = isAddress(value) ? getAddress(value) : value;
  return formatMiddleEllipsis(display, width, tailWidth);
}

export function formatHash(value: string | null | undefined, width = 8): string {
  if (!value) return "—";
  return formatMiddleEllipsis(value, width, 4);
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) {
    return "—";
  }

  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ${minutes % 60}m`;
  const days = Math.floor(hours / 24);
  return `${days}d ${hours % 24}h`;
}

export type KickedDisplayMode = "relative" | "absolute";

export function toggleKickedDisplayMode(current: KickedDisplayMode): KickedDisplayMode {
  return current === "relative" ? "absolute" : "relative";
}

export function renderKickedValue(value: string, mode: KickedDisplayMode): string {
  if (mode !== "relative") {
    return formatCompactDateTime(value);
  }
  const relative = formatCompactRelativeTime(value);
  return relative === "now" ? relative : `${relative} ago`;
}

export function formatUnsignedPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "—";
  }
  return `${new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(Math.abs(value))}%`;
}

export function formatSignedUsdDelta(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "" || Number.isNaN(Number(value))) {
    return "—";
  }
  const numeric = Number(value);
  if (numeric > 0) return `+${formatUsd(Math.abs(numeric))}`;
  if (numeric < 0) return `-${formatUsd(Math.abs(numeric))}`;
  return formatUsd(0);
}

export function signedMetricTone(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "text-tertiary";
  }
  if (value > 0) return "text-positive";
  if (value < 0) return "text-negative";
  return "text-primary";
}
