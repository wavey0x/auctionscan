import type { SearchResult } from "../types/api";

export function searchTypeLabel(type: SearchResult["type"], plural = true): string {
  switch (type) {
    case "auction":
      return plural ? "Auctions" : "Auction";
    case "taker":
      return plural ? "Takers" : "Taker";
    case "transaction":
      return plural ? "Take transactions" : "Take tx";
    case "kick_transaction":
      return plural ? "Kick transactions" : "Kick tx";
    case "token":
      return plural ? "Tokens" : "Token";
    default:
      return type;
  }
}

export function searchResultRoute(result: SearchResult): string {
  if (result.type === "auction") {
    return `/auction/${result.chain_id}/${result.address_or_hash}`;
  }
  if (result.type === "taker") {
    return `/taker/${result.address_or_hash}`;
  }
  if (result.type === "token") {
    return `/?chain=${result.chain_id}&filter=${encodeURIComponent(String(result.metadata?.symbol || result.address_or_hash))}`;
  }
  return `/tx/${result.address_or_hash}`;
}

/** A round destination opens the drawer over the page the reader came from. */
export function searchResultOpensRound(result: SearchResult): boolean {
  return result.type !== "auction" && result.type !== "taker" && result.type !== "token";
}
