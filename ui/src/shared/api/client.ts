import type { paths } from "../types/generated";

import type {
  AuctionDetails,
  AuctionVersionsResponse,
  AuctionTakesResponse,
  ChainsResponse,
  HealthResponse,
  RoundDetailResponse,
  RoundLivePrice,
  RoundsResponse,
  SearchResponse,
  TxResolveResponse,
  TakeDetail,
  SourceOccurrence,
  TakerDetail,
  TakerListResponse,
  TakerTakesResponse,
} from "../types/api";

function normalizeApiBase(rawBaseUrl: string | undefined): string {
  const baseUrl = (rawBaseUrl || "/api").trim();
  if (!baseUrl) {
    return "/api";
  }
  return baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
}

const BASE_URL = normalizeApiBase(import.meta.env.VITE_API_BASE_URL);

type QueryValue = string | number | readonly (string | number)[] | undefined | null;

function buildQuery(params: Record<string, QueryValue>) {
  const search = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    if (Array.isArray(value)) {
      value.forEach((item) => {
        if (item !== "") {
          search.append(key, String(item));
        }
      });
      return;
    }
    search.set(key, String(value));
  });

  return search.toString();
}

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) { super(message); }
}

async function fetchJson<T>(path: string, signal?: AbortSignal, cache?: RequestCache): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, { signal, cache });

  if (!response.ok) {
    throw new ApiError(response.status, `${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

export const api = {
  getHealth(signal?: AbortSignal): Promise<HealthResponse> {
    return fetchJson<HealthResponse>("/health", signal);
  },

  getChains(signal?: AbortSignal): Promise<ChainsResponse> {
    return fetchJson<ChainsResponse>("/chains", signal);
  },

  getRounds(params: NonNullable<paths["/api/rounds"]["get"]["parameters"]["query"]>, signal?: AbortSignal): Promise<RoundsResponse> {
    const query = buildQuery(params);
    return fetchJson<RoundsResponse>(`/rounds${query ? `?${query}` : ""}`, signal);
  },

  getRoundDetail(chainId: number, auctionAddress: string, roundId: number, signal?: AbortSignal): Promise<RoundDetailResponse> {
    return fetchJson<RoundDetailResponse>(`/rounds/${chainId}/${auctionAddress}/${roundId}`, signal, "no-store");
  },

  getAuction(chainId: number, address: string, signal?: AbortSignal): Promise<AuctionDetails | null> {
    return fetchJson<AuctionDetails | null>(`/auctions/${address}?${buildQuery({ chain_id: chainId })}`, signal);
  },


  getAuctionVersions(chainId?: number, signal?: AbortSignal): Promise<AuctionVersionsResponse> {
    const query = buildQuery({ chain_id: chainId });
    return fetchJson<AuctionVersionsResponse>(`/auction-versions${query ? `?${query}` : ""}`, signal);
  },

  getRoundLivePrice(occurrence: SourceOccurrence, snapshot: Pick<RoundLivePrice, "indexed_block" | "indexed_block_hash" | "indexed_timestamp">, signal?: AbortSignal): Promise<RoundLivePrice> {
    return fetchJson<RoundLivePrice>(`/rounds/${occurrence.chain_id}/${occurrence.block_hash}/${occurrence.tx_hash}/${occurrence.log_index}/live-price?${buildQuery(snapshot)}`, signal, "no-store");
  },

  getAuctionTakes(chainId: number, address: string, occurrence?: SourceOccurrence, limit = 200, signal?: AbortSignal): Promise<AuctionTakesResponse> {
    const query = buildQuery({
      chain_id: chainId,
      kick_block_hash: occurrence?.block_hash,
      kick_tx_hash: occurrence?.tx_hash,
      kick_log_index: occurrence?.log_index,
      limit,
    });
    return fetchJson<AuctionTakesResponse>(`/auctions/${address}/takes?${query}`, signal);
  },

  getTake(occurrence: SourceOccurrence, signal?: AbortSignal): Promise<TakeDetail> {
    return fetchJson<TakeDetail>(`/takes/${occurrence.chain_id}/${occurrence.block_hash}/${occurrence.tx_hash}/${occurrence.log_index}`, signal);
  },

  getTakers(params: NonNullable<paths["/api/takers"]["get"]["parameters"]["query"]>, signal?: AbortSignal): Promise<TakerListResponse> {
    const query = buildQuery(params);
    return fetchJson<TakerListResponse>(`/takers${query ? `?${query}` : ""}`, signal);
  },

  getTaker(address: string, signal?: AbortSignal): Promise<TakerDetail | null> {
    return fetchJson<TakerDetail | null>(`/takers/${address}`, signal);
  },

  getTakerTakes(address: string, params: NonNullable<paths["/api/takers/{taker_address}/takes"]["get"]["parameters"]["query"]>, signal?: AbortSignal): Promise<TakerTakesResponse> {
    const query = buildQuery(params);
    return fetchJson<TakerTakesResponse>(`/takers/${address}/takes${query ? `?${query}` : ""}`, signal);
  },

  search(query: string, limit = 20, signal?: AbortSignal): Promise<SearchResponse> {
    return fetchJson<SearchResponse>(`/search?${buildQuery({ q: query, limit })}`, signal);
  },

  resolveTransaction(txHash: string, signal?: AbortSignal): Promise<TxResolveResponse> {
    return fetchJson<TxResolveResponse>(`/tx/${encodeURIComponent(txHash)}/resolve`, signal);
  },

};
