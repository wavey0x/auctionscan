import type { SourceOccurrence } from "../types/api";
import type { Location } from "react-router-dom";

export type RoundModalSource = "rounds" | "auction" | "search" | "tx";

export interface RouteLocationTarget {
  pathname: string;
  search: string;
}

export function buildAuctionPath(
  chainId: number | string,
  auctionAddress: string,
): string {
  return `/auction/${chainId}/${auctionAddress}`;
}

export function buildRoundPath(
  chainId: number | string,
  auctionAddress: string,
  roundId: number,
): string {
  return `/round/${chainId}/${auctionAddress}/${roundId}`;
}

export function parseRoundId(value: string | null | undefined): number | null {
  if (!value || !/^[1-9]\d*$/.test(value)) return null;
  const roundId = Number(value);
  return Number.isSafeInteger(roundId) ? roundId : null;
}

export function parseRoundModalSource(value: string | null | undefined): RoundModalSource | null {
  switch ((value || "").trim().toLowerCase()) {
    case "rounds":
    case "auction":
    case "search":
    case "tx":
      return (value || "").trim().toLowerCase() as RoundModalSource;
    default:
      return null;
  }
}

export function normalizeTransactionHash(value: string | null | undefined): string | null {
  const text = (value || "").trim().toLowerCase();
  if (!text) {
    return null;
  }
  if (/^[0-9a-f]{64}$/.test(text)) {
    return `0x${text}`;
  }
  if (/^0x[0-9a-f]{64}$/.test(text)) {
    return text;
  }
  return null;
}

export function buildTxFilterSearch(txHash: string): string {
  return `?filter=${encodeURIComponent(txHash)}`;
}

export function roundModalSourceFromLocation(location: Pick<Location, "pathname">): RoundModalSource | null {
  if (location.pathname === "/") {
    return "rounds";
  }
  if (location.pathname.startsWith("/auction/")) {
    return "auction";
  }
  if (location.pathname === "/search") {
    return "search";
  }
  return null;
}

export function buildRoundPathWithSource(
  chainId: number | string,
  auctionAddress: string,
  roundId: number,
  source: RoundModalSource | null | undefined,
): string {
  const path = buildRoundPath(chainId, auctionAddress, roundId);
  if (!source || source === "rounds" || source === "tx") {
    return path;
  }
  return `${path}?from=${source}`;
}

export function buildRoundPathFromTransaction(
  chainId: number | string,
  auctionAddress: string,
  roundId: number,
  txHash: string,
  takeOccurrence?: SourceOccurrence | null,
): string {
  const normalizedTxHash = normalizeTransactionHash(txHash);
  if (!normalizedTxHash) {
    return buildRoundPath(chainId, auctionAddress, roundId);
  }
  const params = new URLSearchParams({
    from: "tx",
    tx: normalizedTxHash,
  });
  if (takeOccurrence) params.set("take", occurrenceKey(takeOccurrence));
  return `${buildRoundPath(chainId, auctionAddress, roundId)}?${params.toString()}`;
}

export function resolveRoundModalBackgroundLocation(
  source: RoundModalSource | null | undefined,
  chainId: number | string,
  auctionAddress: string,
  txHash?: string | null,
): RouteLocationTarget {
  if (!source || source === "rounds") {
    return { pathname: "/", search: "" };
  }
  if (source === "auction") {
    return { pathname: buildAuctionPath(chainId, auctionAddress), search: "" };
  }
  if (source === "search") {
    return { pathname: "/search", search: "" };
  }
  if (source === "tx") {
    const normalizedTxHash = normalizeTransactionHash(txHash);
    return {
      pathname: "/",
      search: normalizedTxHash ? buildTxFilterSearch(normalizedTxHash) : "",
    };
  }
  return { pathname: "/", search: "" };
}

export function buildLocationHref(location: RouteLocationTarget): string {
  return `${location.pathname}${location.search}`;
}

export function withBackgroundLocation(location: Location) {
  return { backgroundLocation: location };
}

export function occurrenceKey(occurrence: SourceOccurrence): string {
  return `${occurrence.block_hash}.${occurrence.tx_hash}.${occurrence.log_index}`;
}

export function parseOccurrence(chainId: number, value: string | null | undefined): SourceOccurrence | null {
  const match = value?.match(/^(0x[a-fA-F0-9]{64})\.(0x[a-fA-F0-9]{64})\.(\d+)$/);
  if (!match || !Number.isSafeInteger(chainId) || chainId <= 0) return null;
  const logIndex = Number(match[3]);
  if (!Number.isSafeInteger(logIndex)) return null;
  return { chain_id: chainId, block_hash: match[1].toLowerCase(), tx_hash: match[2].toLowerCase(), log_index: logIndex };
}

export function buildTakePath(take: { chain_id: number; auction_address: string; round_id: number; occurrence: SourceOccurrence }): string {
  return `${buildRoundPath(take.chain_id, take.auction_address, take.round_id)}?take=${occurrenceKey(take.occurrence)}`;
}
