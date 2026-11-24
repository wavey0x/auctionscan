import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import AuctionTakesTable from "./AuctionTakesTable";
import { ApiError, api } from "../../../shared/api/client";
import { LIVE_REFETCH_INTERVAL_MS } from "../../../shared/lib/polling";
import { resolvePriceSource, shouldShowPriceSourceSelector } from "../../../shared/lib/pricingSource";
import { parseOccurrence } from "../../../shared/lib/routes";
import EmptyState from "../../../shared/ui/EmptyState";
import PriceSourceSelect from "../../../shared/ui/PriceSourceSelect";
import RequestError from "../../../shared/ui/RequestError";
import SkeletonRows from "../../../shared/ui/SkeletonRows";
import { TableHoverScope } from "../../../shared/ui/TableHoverContext";

const RECENT_TAKES_LIMIT = 12;

/**
 * An auction's latest takes across its rounds, beneath its rounds on the list.
 * The opened take and the price source live in the URL beside the list's own
 * filters.
 */
export default function AuctionRecentTakes({ chainId, address }: { chainId: number; address: string }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedTakeParam = searchParams.get("take");
  const requestedPriceSource = searchParams.get("priceSource");
  const selectedOccurrence = parseOccurrence(chainId, selectedTakeParam);

  const recentTakesQuery = useQuery({
    queryKey: ["auction-recent-takes", chainId, address],
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
    queryFn: ({ signal }) => api.getAuctionTakes(chainId, address, undefined, RECENT_TAKES_LIMIT, signal),
  });

  const selectedTakeQuery = useQuery({
    queryKey: ["take-detail", selectedOccurrence],
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
    queryFn: ({ signal }) => api.getTake(selectedOccurrence!, signal),
    enabled: Boolean(selectedOccurrence),
  });

  const takeNotFound = selectedTakeQuery.error instanceof ApiError && selectedTakeQuery.error.status === 404;
  const selectedTake = !takeNotFound && selectedTakeQuery.data?.auction.toLowerCase() === address.toLowerCase() ? selectedTakeQuery.data : undefined;
  const selectedTakeNotice = !selectedTakeParam ? null : !selectedOccurrence ? <EmptyState title="Invalid take link" /> : takeNotFound || (selectedTakeQuery.isSuccess && !selectedTake) ? (
    <EmptyState title="Take not found" description="This occurrence is absent from the indexed auction." />
  ) : selectedTakeQuery.isError && !selectedTake ? (
    <RequestError message="Unable to load take." onRetry={() => { void selectedTakeQuery.refetch(); }} />
  ) : null;

  const setSelectedTake = (key?: string) => {
    const next = new URLSearchParams(searchParams);
    if (!key) next.delete("take");
    else next.set("take", key);
    setSearchParams(next, { replace: true });
  };

  const setPriceSource = (sourceId: string) => {
    const next = new URLSearchParams(searchParams);
    if (sourceId === "canonical") next.delete("priceSource");
    else next.set("priceSource", sourceId);
    setSearchParams(next, { replace: true });
  };

  useEffect(() => {
    if (!selectedTakeParam) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedTake(undefined);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedTakeParam, searchParams, setSearchParams]);

  const sourceOptions = recentTakesQuery.data?.available_price_sources || [];
  const selectedPriceSource = resolvePriceSource(requestedPriceSource, sourceOptions);

  useEffect(() => {
    if (!sourceOptions.length) return;
    const normalized = requestedPriceSource?.trim().toLowerCase() || "canonical";
    if (normalized === selectedPriceSource) return;
    setPriceSource(selectedPriceSource);
  }, [requestedPriceSource, selectedPriceSource, sourceOptions.length]);

  return (
    <section className="card card-clip" aria-label="Recent takes">
      <div className="card-title">
        <span className="inline-flex items-center gap-3">
          Recent takes
          {shouldShowPriceSourceSelector(sourceOptions) ? (
            <PriceSourceSelect value={selectedPriceSource} options={sourceOptions} onChange={setPriceSource} />
          ) : null}
        </span>
        <strong>{recentTakesQuery.data?.takes.length ?? "—"}</strong>
      </div>
      {selectedTakeNotice}
      {recentTakesQuery.isError && !recentTakesQuery.data && <RequestError message="Unable to load takes." onRetry={() => { void recentTakesQuery.refetch(); }} />}
      {recentTakesQuery.isLoading ? (
        <div className="table-wrap">
          <table className="data-table">
            <tbody>
              <SkeletonRows rows={6} widths={[28, 24, 80, 110, 110, 110, 60, 64, null]} classNames={[undefined, undefined, "col-lo", undefined, "col-md", undefined, "col-md num", "num", "open-cell"]} />
            </tbody>
          </table>
        </div>
      ) : recentTakesQuery.isError && !recentTakesQuery.data ? null : (
        <TableHoverScope>
          <AuctionTakesTable
            takes={recentTakesQuery.data?.takes || []}
            priceSource={selectedPriceSource}
            selectedOccurrenceKey={selectedTakeParam}
            selectedTake={selectedTake}
            isSelectedTakeLoading={selectedTakeQuery.isLoading}
            onOpenTake={(key) => setSelectedTake(selectedTakeParam === key ? undefined : key)}
          />
        </TableHoverScope>
      )}
    </section>
  );
}
