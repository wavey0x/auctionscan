/** Who runs an auction: Yearn's factory auctions or Curve's fee burner. */
export type Protocol = "yearn" | "curve";

export const PROTOCOLS: readonly Protocol[] = ["yearn", "curve"];

export const PROTOCOL_LABELS: Record<Protocol, string> = {
  yearn: "Yearn",
  curve: "Curve",
};

export function parseProtocol(value: string | null): Protocol | undefined {
  return (PROTOCOLS as readonly string[]).includes(value ?? "") ? (value as Protocol) : undefined;
}

/**
 * A name for an auction whose address says nothing on its own. Curve has one
 * burner per chain selling every fee token, so its rows name it rather than
 * repeat one address.
 */
export function auctionLabel(protocol: string | null | undefined): string | null {
  return protocol === "curve" ? "Curve burner" : null;
}

/**
 * Whether a round's number says anything in a list of rounds. A Yearn auction
 * counts its own kicks, so `R66` places a round in its auction's history.
 * Curve's burner numbers every lot it has ever staged in one run, across every
 * token: the number places nothing, and a lot is known by its token and week.
 */
export function roundNumberIsMeaningful(protocol: string | null | undefined): boolean {
  return protocol !== "curve";
}

/**
 * Whether a lot's symbol needs its token's address beside it. Curve's burner
 * sells whatever fee tokens reach it, and many share a symbol: two dozen pool
 * tokens are all `SPT-PT/IBT-f`. A Yearn auction's token is named by its pair.
 */
export function lotNeedsTokenAddress(protocol: string | null | undefined): boolean {
  return protocol === "curve";
}

/**
 * A contract version as a reader knows it: `v1.0.5` for Yearn's auctions, and
 * Curve's burner by its own version id (`curve-1`), since its name is already
 * given wherever the auction is.
 */
export function versionLabel(version: string | null | undefined): string | null {
  if (!version) return null;
  if (version.startsWith("curve")) return version;
  return version.startsWith("v") ? version : `v${version}`;
}
