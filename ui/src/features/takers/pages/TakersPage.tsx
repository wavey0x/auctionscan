import { useQuery } from "@tanstack/react-query";
import { ArrowDown } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../../../shared/api/client";
import { useChainsQuery } from "../../../shared/lib/chains";
import { cn, formatCompactDateTime, formatCompactUsd, formatCount, formatDateTime, formatUsd } from "../../../shared/lib/format";
import { linkRowKeyDown } from "../../../shared/lib/openRound";
import { handleRowNavigation } from "../../../shared/lib/rowNavigation";
import ChainIcon from "../../../shared/ui/ChainIcon";
import EmptyState from "../../../shared/ui/EmptyState";
import OpenMark from "../../../shared/ui/OpenMark";
import Pagination from "../../../shared/ui/Pagination";
import RequestError from "../../../shared/ui/RequestError";
import SkeletonRows from "../../../shared/ui/SkeletonRows";
import TakerAddressValue from "../../../shared/ui/TakerAddressValue";
import { ChipGroup, FilterField } from "../../../shared/ui/Toolbar";

const PAGE_SIZE = 20;
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
      {hiddenCount > 0 ? <span className="font-mono text-[11px] text-tertiary">+{hiddenCount}</span> : null}
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

  const update = (mutate: (next: URLSearchParams) => void) => {
    const next = new URLSearchParams(searchParams);
    mutate(next);
    setSearchParams(next);
  };

  const setSort = (nextSort: TakerSortKey) => {
    update((next) => {
      if (nextSort === "volume") next.delete("sort");
      else next.set("sort", nextSort);
      next.delete("page");
    });
  };

  const sortableHeader = (sortKey: TakerSortKey, className?: string) => {
    const isActive = sortBy === sortKey;
    const label = SORTABLE_COLUMNS[sortKey];
    return (
      <th className={className} aria-sort={isActive ? "descending" : undefined}>
        <button
          type="button"
          className={cn("sort-button", isActive && "is-active")}
          onClick={() => setSort(sortKey)}
          title={`Sort by ${label.toLowerCase()}`}
        >
          {className?.includes("num") && isActive ? <ArrowDown className="sort-arrow h-3 w-3" strokeWidth={2} /> : null}
          <span>{label}</span>
          {!className?.includes("num") && isActive ? <ArrowDown className="sort-arrow h-3 w-3" strokeWidth={2} /> : null}
        </button>
      </th>
    );
  };

  const takers = takersQuery.data?.takers ?? [];
  const maxVolume = takers.reduce((max, taker) => Math.max(max, Number(taker.total_volume_usd) || 0), 0);
  const chainOptions = Object.values(chainsData?.chains || {}).map((chain) => ({
    value: chain.chain_id,
    label: <ChainIcon chainId={chain.chain_id} size="sm" />,
    title: chain.short_name || chain.name,
    icon: true,
  }));

  return (
    <div className="space-y-4">
      <div className="page-head">
        <h1 className="page-title m-0">Takers</h1>
        {takersQuery.data ? (
          <span className="font-mono text-meta text-tertiary">{takersQuery.data.total.toLocaleString()} results found</span>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="filter-line">
          <ChipGroup
            label="Chain"
            resetLabel="All chains"
            single
            options={chainOptions}
            selected={chainId ? [chainId] : []}
            onChange={(nextChains) => update((next) => {
              if (nextChains[0]) next.set("chain", String(nextChains[0]));
              else next.delete("chain");
              next.delete("page");
            })}
          />
        </div>
        <FilterField
          label="Find a taker"
          value={query}
          placeholder="Find a taker address"
          onChange={(value) => update((next) => {
            if (value.trim()) next.set("q", value);
            else next.delete("q");
            next.delete("page");
          })}
        />
      </div>
      {chainsQuery.isError && !chainsData && <RequestError message="Unable to load network filters." onRetry={() => { void chainsQuery.refetch(); }} />}

      <section className="card card-clip" aria-label="Takers">
        {takersQuery.isError && !takersQuery.data && <RequestError message="Unable to load takers." onRetry={() => { void takersQuery.refetch(); }} />}
        {takersQuery.isError && !takersQuery.data ? null : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th className="col-lo fit text-right">#</th>
                  {sortableHeader("taker")}
                  {sortableHeader("chains", "col-md")}
                  {sortableHeader("volume", "num")}
                  {sortableHeader("takes", "col-md num")}
                  {sortableHeader("auctions", "col-md num")}
                  {sortableHeader("recent", "col-md num")}
                  <th className="open-cell"><span className="sr-only">Open</span></th>
                </tr>
              </thead>
              <tbody>
                {takersQuery.isLoading ? (
                  <SkeletonRows
                    rows={12}
                    widths={[16, 150, 40, 140, 40, 30, 80, null]}
                    classNames={["col-lo num", undefined, "col-md", "num", "col-md num", "col-md num", "col-md num", "open-cell"]}
                  />
                ) : takers.length ? (
                  takers.map((taker, index) => {
                    const href = `/taker/${taker.taker}`;
                    const volume = Number(taker.total_volume_usd) || 0;
                    const partialVolume = taker.paid_usd_take_count < taker.total_takes;
                    return (
                      <tr
                        key={taker.taker}
                        className="data-row"
                        tabIndex={0}
                        data-row=""
                        onClick={(event) => handleRowNavigation(event, href, navigate)}
                        onAuxClick={(event) => handleRowNavigation(event, href, navigate)}
                        onKeyDown={linkRowKeyDown(() => navigate(href))}
                      >
                        <td className="col-lo num dim fit text-[11px]">{(page - 1) * PAGE_SIZE + index + 1}</td>
                        <td>
                          <TakerAddressValue
                            address={taker.taker}
                            chainId={taker.active_chains[0]}
                            showBlockie
                            blockieSize={18}
                            width={8}
                          />
                          <div className="sub-line pl-[26px]">{`${formatCount(taker.total_takes)} takes · ${formatCompactDateTime(taker.last_take)}`}</div>
                        </td>
                        <td className="col-md"><TakerChainStrip chainIds={taker.active_chains} /></td>
                        <td
                          className="num"
                          title={`${formatUsd(taker.total_volume_usd)}${partialVolume ? ` · USD value known for ${taker.paid_usd_take_count} of ${taker.total_takes} takes` : ""}`}
                        >
                          <span className="inline-flex items-center justify-end gap-3">
                            <span className="col-md bar is-relative w-[88px]" aria-hidden="true">
                              <i style={{ width: `${maxVolume ? Math.max(1, (volume / maxVolume) * 100) : 0}%`, marginLeft: "auto" }} />
                            </span>
                            <span className="min-w-[4.5rem] text-primary">{formatCompactUsd(taker.total_volume_usd)}</span>
                            {partialVolume ? <span className="stat-note">partial</span> : null}
                          </span>
                        </td>
                        <td className="col-md num">{formatCount(taker.total_takes)}</td>
                        <td className="col-md num">{formatCount(taker.unique_auctions)}</td>
                        <td className="col-md num dim" title={formatDateTime(taker.last_take)}>{formatCompactDateTime(taker.last_take)}</td>
                        <OpenMark />
                      </tr>
                    );
                  })
                ) : (
                  <tr>
                    <td colSpan={8}>
                      <EmptyState title="No takers found" description="The current ranking filters returned no taker activity." />
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {takersQuery.data ? (
        <Pagination
          page={page}
          hasNext={takersQuery.data.has_next}
          onPageChange={(nextPage) => update((next) => {
            if (nextPage <= 1) next.delete("page");
            else next.set("page", String(nextPage));
          })}
        />
      ) : null}
    </div>
  );
}
