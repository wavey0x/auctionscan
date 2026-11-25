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
 * A contract version as a reader knows it: `v1.0.5` for Yearn's auctions, and
 * Curve's burner by its own version id (`curve-1`), since its name is already
 * given wherever the auction is.
 */
export function versionLabel(version: string | null | undefined): string | null {
  if (!version) return null;
  if (version.startsWith("curve")) return version;
  return version.startsWith("v") ? version : `v${version}`;
}
