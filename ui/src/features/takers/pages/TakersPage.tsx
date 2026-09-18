import MetricCoverage from "../../../shared/ui/MetricCoverage";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpDown } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../../../shared/api/client";
import { useChainsQuery } from "../../../shared/lib/chains";
import { formatCompactDateTime, formatDateTime, formatUsd } from "../../../shared/lib/format";
import { handleRowNavigation } from "../../../shared/lib/rowNavigation";
import ChainIcon from "../../../shared/ui/ChainIcon";
import EmptyState from "../../../shared/ui/EmptyState";
import RequestError from "../../../shared/ui/RequestError";
import Pagination from "../../../shared/ui/Pagination";
import Panel from "../../../shared/ui/Panel";
import Skeleton from "../../../shared/ui/Skeleton";
import StackedListRow from "../../../shared/ui/StackedListRow";
import TakerAddressValue from "../../../shared/ui/TakerAddressValue";

const PAGE_SIZE = 15;
const MAX_CHAIN_ICONS = 5;
const SORTABLE_COLUMNS = {
  taker: "Taker",
  chains: "Chains",
  volume: "Volume",
  takes: "Takes",
  auctions: "Auctions",
  recent: "Last take",
} as const;

type TakerSortKey = keyof typeof SORTABLE_COLUMNS;

function TakerChainStrip({ chainIds }: { chainIds: number[] }) {
  const visibleChains = chainIds.slice(0, MAX_CHAIN_ICONS);
  const hiddenCount = Math.max(0, chainIds.length - visibleChains.length);

  return (
    <div className="flex items-center gap-1.5">
      {visibleChains.map((id) => (
        <ChainIcon key={id} chainId={id} size="sm" />
      ))}
      {hiddenCount > 0 ? (
        <span className="inline-flex h-4 min-w-[1.25rem] items-center justify-center rounded-full border border-divider-subtle px-1 font-mono text-[10px] leading-none text-tertiary">
          +{hiddenCount}
        </span>
      ) : null}
    </div>
  );
}

export default function TakersPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, Number(searchParams.get("page") || "1"));
  const sortBy = ((searchParams.get("sort") as TakerSortKey | null) || "volume");
  const chainId = searchParams.get("chain") ? Number(searchParams.get("chain")) : undefined;
  const query = searchParams.get("q") || "";

  const chainsQuery = useChainsQuery();
  const chainsData = chainsQuery.data;

  const takersQuery = useQuery({
    queryKey: ["takers", page, sortBy, chainId, query],
    queryFn: ({ signal }) => api.getTakers({ page, limit: PAGE_SIZE, sort_by: sortBy, chain_id: chainId, q: query }, signal),
  });

  const setSort = (nextSort: TakerSortKey) => {
    const next = new URLSearchParams(searchParams);
    if (nextSort === "volume") {
      next.delete("sort");
    } else {
      next.set("sort", nextSort);
    }
    next.delete("page");
    setSearchParams(next);
  };

  const sortableHeader = (sortKey: TakerSortKey, label: string, className?: string) => {
    const isActive = sortBy === sortKey;
    return (
      <th className={className}>
        <button
          type="button"
          className={`inline-flex items-center gap-1 transition-colors ${isActive ? "text-primary" : "text-tertiary hover:text-primary"}`}
          onClick={() => setSort(sortKey)}
          title={`Sort by ${label.toLowerCase()}`}
        >
          <span>{label}</span>
          <ArrowUpDown className="h-3 w-3" strokeWidth={1.8} />
        </button>
      </th>
    );
  };

  return (
    <div className="space-y-4">
      <Panel className="space-y-3">
        <div className="text-title text-primary">Takers</div>
        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-[minmax(0,15rem)_11rem] lg:max-w-[27rem]">
          <label className="space-y-1">
            <span className="metric-label">Address</span>
            <input
              className="filter-input"
              type="text"
              inputMode="text"
              autoComplete="off"
              spellCheck={false}
              placeholder="0x address"
              value={query}
              onChange={(event) => {
                const next = new URLSearchParams(searchParams);
                if (event.target.value.trim()) {
                  next.set("q", event.target.value);
                } else {
                  next.delete("q");
                }
                next.delete("page");
                setSearchParams(next);
              }}
            />
          </label>
          <label className="space-y-1">
            <span className="metric-label">Chain</span>
            <select
              className="filter-select w-full"
              value={chainId || ""}
              onChange={(event) => {
                const next = new URLSearchParams(searchParams);
                if (event.target.value) next.set("chain", event.target.value);
                else next.delete("chain");
                next.delete("page");
                setSearchParams(next);
              }}
            >
              <option value="">All chains</option>
              {Object.values(chainsData?.chains || {}).map((chain) => (
                <option key={chain.chain_id} value={chain.chain_id}>
                  {chain.short_name || chain.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {chainsQuery.isError && <RequestError message={chainsData ? "Could not refresh network filters. Showing previously loaded data." : "Unable to load network filters."} onRetry={() => { void chainsQuery.refetch(); }} />}
        {takersQuery.data ? (
          <div className="text-meta text-tertiary">
            {takersQuery.data.total.toLocaleString()} results found
          </div>
        ) : null}
      </Panel>

      <Panel padded={false}>
        {takersQuery.isError && <RequestError message={takersQuery.data ? "Could not refresh takers. Showing previously loaded data." : "Unable to load takers."} onRetry={() => { void takersQuery.refetch(); }} />}
        {takersQuery.isLoading ? (
          <div className="space-y-2 p-3">
            {Array.from({ length: 10 }).map((_, index) => (
              <Skeleton key={index} className="h-10 w-full" />
            ))}
          </div>
        ) : takersQuery.isError && !takersQuery.data ? null : takersQuery.data?.takers.length ? (
          <>
            <div className="md:hidden">
              {takersQuery.data.takers.map((taker) => (
                <StackedListRow
                  key={`mobile-${taker.taker}`}
                  interactive
                  className="space-y-2"
                  onClick={(event) => handleRowNavigation(event, `/taker/${taker.taker}`, navigate)}
                  onAuxClick={(event) => handleRowNavigation(event, `/taker/${taker.taker}`, navigate)}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <TakerAddressValue
                        address={taker.taker}
                        chainId={taker.active_chains[0]}
                        showBlockie
                        blockieSize={22}
                        width={8}
                        className="[&_.identity-link]:text-[14px] [&_.identity-link]:text-primary [&_.copy-trigger]:md:h-3.5 [&_.copy-trigger]:md:w-3.5"
                      />
                    </div>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                      <span className="metric-label">Chains</span>
                      <TakerChainStrip chainIds={taker.active_chains} />
                    </div>
                    <div className="shrink-0 font-mono text-data text-primary">{formatUsd(taker.total_volume_usd)} <MetricCoverage count={taker.paid_usd_take_count} total={taker.total_takes} /></div>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-meta text-tertiary">
                    <span className="font-mono">{taker.total_takes.toLocaleString()} takes</span>
                    <span className="font-mono">{taker.unique_auctions.toLocaleString()} auctions</span>
                    <span className="font-mono">{taker.unique_chains.toLocaleString()} chains</span>
                    <div className="font-mono text-meta text-tertiary" title={formatDateTime(taker.last_take)}>
                      {formatCompactDateTime(taker.last_take)}
                    </div>
                  </div>
                </StackedListRow>
              ))}
            </div>
            <div className="hidden md:block table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    {sortableHeader("taker", "Taker", "w-[16rem]")}
                    {sortableHeader("chains", "Chains", "w-[7rem]")}
                    {sortableHeader("volume", "Volume", "w-[8rem] text-right")}
                    {sortableHeader("takes", "Takes", "w-[6rem] text-right")}
                    {sortableHeader("auctions", "Auctions", "w-[6rem] text-right")}
                    {sortableHeader("recent", "Last take", "w-[9rem]")}
                  </tr>
                </thead>
                <tbody>
                  {takersQuery.data.takers.map((taker) => (
                    <tr
                      key={taker.taker}
                      className="data-row"
                      onClick={(event) => handleRowNavigation(event, `/taker/${taker.taker}`, navigate)}
                      onAuxClick={(event) => handleRowNavigation(event, `/taker/${taker.taker}`, navigate)}
                    >
                      <td>
                        <TakerAddressValue
                          address={taker.taker}
                          chainId={taker.active_chains[0]}
                          showBlockie
                          blockieSize={22}
                          width={8}
                          className="[&_.identity-link]:text-[14px] [&_.identity-link]:text-primary [&_.copy-trigger]:md:h-3.5 [&_.copy-trigger]:md:w-3.5"
                        />
                      </td>
                      <td>
                        <TakerChainStrip chainIds={taker.active_chains} />
                      </td>
                      <td className="text-right font-mono text-primary">{formatUsd(taker.total_volume_usd)} <MetricCoverage count={taker.paid_usd_take_count} total={taker.total_takes} /></td>
                      <td className="text-right font-mono text-primary">{taker.total_takes.toLocaleString()}</td>
                      <td className="text-right font-mono text-primary">{taker.unique_auctions.toLocaleString()}</td>
                      <td className="font-mono text-primary" title={formatDateTime(taker.last_take)}>
                        {formatCompactDateTime(taker.last_take)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <div className="p-3">
            <EmptyState title="No takers found" description="The current ranking filters returned no taker activity." />
          </div>
        )}
        {takersQuery.data ? (
          <div className="px-3 pb-3 pt-2 md:px-4">
            <Pagination
              page={page}
              hasNext={takersQuery.data.has_next}
              onPageChange={(nextPage) => {
                const next = new URLSearchParams(searchParams);
                if (nextPage <= 1) next.delete("page");
                else next.set("page", String(nextPage));
                setSearchParams(next);
              }}
            />
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
