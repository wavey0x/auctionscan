import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { ChainInfo } from "../types/api";

export function useChainsQuery() {
  return useQuery({
    queryKey: ["chains"],
    queryFn: ({ signal }) => api.getChains(signal),
    staleTime: 60 * 60 * 1000,
  });
}

export function useChainInfo(chainId?: number | null) {
  const query = useChainsQuery();
  return {
    ...query,
    chain: chainId ? query.data?.chains?.[chainId] : undefined,
  };
}

export function buildExplorerUrl(
  chain: ChainInfo | undefined,
  type: "address" | "tx",
  value: string | null | undefined,
): string | null {
  if (!chain?.explorer || chain.explorer === "#" || !value) {
    return null;
  }

  const base = chain.explorer.endsWith("/") ? chain.explorer.slice(0, -1) : chain.explorer;
  return `${base}/${type}/${value}`;
}
