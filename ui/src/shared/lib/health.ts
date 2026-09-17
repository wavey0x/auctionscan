import type { HealthChain } from "../types/api";

export type ChainHealthTone = "healthy" | "indexing" | "degraded" | "error" | "disabled";

export function getChainHealthTone(chain: HealthChain): ChainHealthTone {
  if (!chain.indexed) {
    return "disabled";
  }
  if (chain.health === "error" || chain.last_error) {
    return "error";
  }
  if (chain.health === "stale" || chain.health === "degraded") {
    return "degraded";
  }
  if ((chain.block_lag ?? 0) > 0) {
    return "indexing";
  }
  return "healthy";
}

export function getChainHealthLabel(chain: HealthChain): string {
  const tone = getChainHealthTone(chain);
  if (tone === "disabled") {
    return "Disabled";
  }
  if (tone === "error") {
    return "Error";
  }
  if (tone === "degraded") {
    return chain.health === "stale" ? "Stale" : "Delayed";
  }
  if (tone === "indexing") {
    return "Indexing";
  }
  return "Healthy";
}

export function summarizeNetworkHealth(
  chains: HealthChain[] | undefined,
  hasError: boolean,
): ChainHealthTone {
  if (hasError) {
    return "error";
  }
  if (!chains || chains.length === 0) {
    return "disabled";
  }
  const activeChains = chains.filter((chain) => chain.indexed);
  if (activeChains.length === 0) {
    return "disabled";
  }
  if (activeChains.some((chain) => getChainHealthTone(chain) === "error")) {
    return "error";
  }
  if (activeChains.some((chain) => getChainHealthTone(chain) === "degraded")) {
    return "degraded";
  }
  if (activeChains.some((chain) => getChainHealthTone(chain) === "indexing")) {
    return "indexing";
  }
  return "healthy";
}
