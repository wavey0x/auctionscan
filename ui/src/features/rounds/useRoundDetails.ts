import { useRef } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiError, api } from "../../shared/api/client";
import { occurrenceKey } from "../../shared/lib/routes";
import type { SourceOccurrence } from "../../shared/types/api";

export function useRoundDetails(
  chain: number,
  auctionAddress: string | undefined,
  roundId: number | null,
  selectedOccurrence: SourceOccurrence | null,
) {
  const mismatchRetryAfter = useRef(0);
  const validRound = Number.isSafeInteger(chain) && chain > 0 && !!auctionAddress && roundId !== null;

  const roundQuery = useQuery({
    queryKey: ["round-detail", chain, auctionAddress?.toLowerCase(), roundId],
    queryFn: ({ signal }) => api.getRoundDetail(chain, auctionAddress!, roundId!, signal),
    enabled: validRound,
  });
  const roundNotFound = roundQuery.error instanceof ApiError && roundQuery.error.status === 404;
  const candidate = roundNotFound ? undefined : roundQuery.data?.round;
  const round = candidate?.chain_id === chain && candidate.round_id === roundId
    && candidate.auction_address.toLowerCase() === auctionAddress?.toLowerCase() ? candidate : undefined;
  const occurrence = round?.occurrence;

  const auctionQuery = useQuery({
    queryKey: ["auction", chain, auctionAddress],
    queryFn: ({ signal }) => api.getAuction(chain, auctionAddress!, signal),
    enabled: Number.isFinite(chain) && !!auctionAddress,
  });

  const takesQuery = useQuery({
    queryKey: ["round-takes", occurrence],
    queryFn: ({ signal }) => api.getAuctionTakes(chain, auctionAddress!, occurrence!, 200, signal),
    enabled: Boolean(occurrence) && !!auctionAddress,
  });

  const selectedTakeQuery = useQuery({
    queryKey: ["take-detail", selectedOccurrence],
    queryFn: ({ signal }) => api.getTake(selectedOccurrence!, signal),
    enabled: validRound && Boolean(selectedOccurrence),
  });

  const selectedTakeNotFound = selectedTakeQuery.error instanceof ApiError && selectedTakeQuery.error.status === 404;
  const selectedTake = !selectedTakeNotFound && selectedTakeQuery.data && occurrence && occurrenceKey(selectedTakeQuery.data.round_occurrence) === occurrenceKey(occurrence) ? selectedTakeQuery.data : undefined;
  const checkpoint = roundQuery.data?.as_of[chain];
  const priceReference = checkpoint?.indexed_block != null && checkpoint.indexed_block_hash && checkpoint.indexed_timestamp != null
    ? { indexed_block: checkpoint.indexed_block, indexed_block_hash: checkpoint.indexed_block_hash, indexed_timestamp: checkpoint.indexed_timestamp }
    : null;
  const livePriceQuery = useQuery({
    queryKey: ["round-live-price", occurrence, priceReference],
    queryFn: async ({ signal }) => {
      try {
        return await api.getRoundLivePrice(occurrence!, priceReference!, signal);
      } catch (error) {
        if (error instanceof ApiError && error.status === 409 && Date.now() >= mismatchRetryAfter.current) {
          // Refresh once. The new snapshot key triggers the retry; further mismatches
          // wait for normal polling instead of recursively refreshing during catch-up.
          mismatchRetryAfter.current = Date.now() + 3_000;
          await roundQuery.refetch();
        }
        throw error;
      }
    },
    enabled: Boolean(occurrence && priceReference && round?.is_active && !roundQuery.isError),
    retry: false,
    refetchInterval: 3_000,
    refetchIntervalInBackground: false,
  });
  const price = livePriceQuery.isError ? undefined : livePriceQuery.data;
  const displayedLivePrice = !roundQuery.isError && price && priceReference && occurrence
    && price.indexed_block_hash === priceReference.indexed_block_hash
    && price.indexed_block === priceReference.indexed_block
    && price.indexed_timestamp === priceReference.indexed_timestamp
    && occurrenceKey(price.occurrence) === occurrenceKey(occurrence)
    ? price : undefined;

  return {
    roundQuery,
    auctionQuery,
    takesQuery,
    selectedTakeQuery,
    livePriceQuery,
    round,
    selectedTake,
    roundNotFound,
    selectedTakeNotFound,
    priceReference,
    displayedLivePrice,
  };
}
