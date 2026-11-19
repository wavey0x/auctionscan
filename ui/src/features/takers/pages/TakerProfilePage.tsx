import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { ArrowLeft } from "lucide-react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../../../shared/api/client";
import { formatCompactDateTime, formatCompactUsd, formatCount, formatDateTime, formatPrice, formatUsd } from "../../../shared/lib/format";
import { linkRowKeyDown } from "../../../shared/lib/openRound";
import { DEFAULT_PRICE_SOURCE, getTakerTakePricingBySource, resolvePriceSource, shouldShowPriceSourceSelector } from "../../../shared/lib/pricingSource";
import { handleRowNavigation } from "../../../shared/lib/rowNavigation";
import { buildTakePath, withBackgroundLocation } from "../../../shared/lib/routes";
import AuctionAddressValue from "../../../shared/ui/AuctionAddressValue";
import ChainIcon from "../../../shared/ui/ChainIcon";
import EmptyState from "../../../shared/ui/EmptyState";
import OpenMark from "../../../shared/ui/OpenMark";
import Pagination from "../../../shared/ui/Pagination";
import PnlValue from "../../../shared/ui/PnlValue";
import PriceSourceSelect from "../../../shared/ui/PriceSourceSelect";
import RequestError from "../../../shared/ui/RequestError";
import SkeletonRows from "../../../shared/ui/SkeletonRows";
import StatStrip, { Stat } from "../../../shared/ui/StatStrip";
import { TableHoverScope } from "../../../shared/ui/TableHoverContext";
import TakerAddressValue from "../../../shared/ui/TakerAddressValue";

const PAGE_SIZE = 20;

export default function TakerProfilePage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { address } = useParams<{ address: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const page = Math.max(1, Number(searchParams.get("page") || "1"));
  const requestedPriceSource = searchParams.get("priceSource");

  const detailQuery = useQuery({
    queryKey: ["taker", address],
    queryFn: ({ signal }) => api.getTaker(address!, signal),
    enabled: !!address,
  });

  const takesQuery = useQuery({
    queryKey: ["taker-takes", address, page],
    queryFn: ({ signal }) => api.getTakerTakes(address!, { page, limit: PAGE_SIZE }, signal),
    enabled: !!address,
  });

  const setPriceSource = (sourceId: string) => {
    const next = new URLSearchParams(searchParams);
    if (sourceId === DEFAULT_PRICE_SOURCE) {
      next.delete("priceSource");
    } else {
      next.set("priceSource", sourceId);
    }
    setSearchParams(next, { replace: true });
  };

  const sourceOptions = takesQuery.data?.available_price_sources || [];
  const selectedPriceSource = resolvePriceSource(requestedPriceSource, sourceOptions);
  const showPriceSourceSelector = shouldShowPriceSourceSelector(sourceOptions);

  useEffect(() => {
    if (!sourceOptions.length) {
      return;
    }
    const normalized = requestedPriceSource?.trim().toLowerCase() || DEFAULT_PRICE_SOURCE;
    if (normalized === selectedPriceSource) {
      return;
    }
    setPriceSource(selectedPriceSource);
  }, [requestedPriceSource, selectedPriceSource, sourceOptions.length]);

  if (detailQuery.isLoading) {
    return (
      <div className="space-y-4" aria-busy="true">
        <span className="skeleton-bar w-24" />
        <div className="card space-y-3 p-5">
          <span className="skeleton-bar w-16" />
          <span className="skeleton-bar h-4 w-72 max-w-full" />
        </div>
      </div>
    );
  }

  if (detailQuery.isError && !detailQuery.data) {
    return <RequestError message="Unable to load taker profile." onRetry={() => { void detailQuery.refetch(); }} />;
  }

  if (!detailQuery.data) {
    return <EmptyState title="Taker not found" description="The requested taker profile could not be loaded." />;
  }

  const taker = detailQuery.data;
  const partialVolume = taker.paid_usd_take_count < taker.total_takes;

  return (
    <div className="space-y-4">
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 text-meta text-tertiary">
        <Link to="/takers" className="inline-flex items-center gap-1.5 transition-colors hover:text-primary">
          <ArrowLeft className="h-3.5 w-3.5" strokeWidth={1.6} />
          Takers
        </Link>
        <span className="text-faint">/</span>
        <span className="text-secondary">Taker</span>
      </nav>

      <section className="card px-4 py-4 md:px-5" aria-label="Taker">
        <div className="label">Taker profile</div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-2">
          <h1 className="m-0 text-heading font-normal [&_.identity-link]:text-heading">
            <TakerAddressValue
              address={taker.taker}
              chainId={taker.active_chains[0]}
              width={10}
              showBlockie
              blockieSize={24}
            />
          </h1>
          <span className="flex items-center gap-1.5">
            {taker.active_chains.map((chainId) => (
              <ChainIcon key={chainId} chainId={chainId} size="sm" />
            ))}
          </span>
        </div>
      </section>

      <StatStrip label="Taker totals" count={5}>
        <Stat label="Total takes" value={formatCount(taker.total_takes)} />
        <Stat label="Auctions" value={formatCount(taker.unique_auctions)} />
        <Stat label="Chains" value={formatCount(taker.unique_chains)} />
        <Stat
          label="Volume"
          value={formatCompactUsd(taker.total_volume_usd)}
          note={partialVolume ? "partial" : null}
          title={`${formatUsd(taker.total_volume_usd)}${partialVolume ? ` · USD value known for ${taker.paid_usd_take_count} of ${taker.total_takes} takes` : ""}`}
        />
        <Stat label="Last take" value={formatCompactDateTime(taker.last_take)} title={formatDateTime(taker.last_take)} />
      </StatStrip>

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-2">
          <section className="card card-clip" aria-label="Recent takes">
            <div className="card-title">
              <span className="inline-flex items-center gap-3">
                Recent takes
                {showPriceSourceSelector ? (
                  <PriceSourceSelect value={selectedPriceSource} options={sourceOptions} onChange={setPriceSource} />
                ) : null}
              </span>
              <strong>{takesQuery.data ? formatCount(takesQuery.data.total_count) : ""}</strong>
            </div>
            {takesQuery.isError && !takesQuery.data && <RequestError message="Unable to load takes." onRetry={() => { void takesQuery.refetch(); }} />}
            {takesQuery.isError && !takesQuery.data ? null : (
              <div className="table-wrap">
                <TableHoverScope>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th className="fit">Round</th>
                        <th>Auction</th>
                        <th className="col-lo">Time</th>
                        <th className="col-md num">Price</th>
                        <th className="num">PnL</th>
                        <th className="open-cell"><span className="sr-only">Open</span></th>
                      </tr>
                    </thead>
                    <tbody>
                      {takesQuery.isLoading ? (
                        <SkeletonRows rows={8} widths={[40, 140, 80, 70, 70, null]} classNames={[undefined, undefined, "col-lo", "col-md num", "num", "open-cell"]} />
                      ) : takesQuery.data?.takes.length ? (
                        takesQuery.data.takes.map((take, index) => {
                          const pricing = getTakerTakePricingBySource(take, selectedPriceSource);
                          const href = buildTakePath(take);
                          const open = () => navigate(href, { state: withBackgroundLocation(location) });
                          return (
                            <tr
                              key={`${take.tx_hash}-${index}`}
                              className="data-row"
                              tabIndex={0}
                              data-row=""
                              onClick={(event) => handleRowNavigation(event, href, open)}
                              onAuxClick={(event) => handleRowNavigation(event, href, open)}
                              onKeyDown={linkRowKeyDown(open)}
                            >
                              <td className="mono fit pr-4 text-secondary">R{take.round_id}</td>
                              <td>
                                <span className="inline-flex min-w-0 items-center gap-2">
                                  <ChainIcon chainId={take.chain_id} size="xs" />
                                  <AuctionAddressValue address={take.auction_address} chainId={take.chain_id} />
                                </span>
                              </td>
                              <td className="col-lo mono dim" title={formatDateTime(take.timestamp)}>{formatCompactDateTime(take.timestamp)}</td>
                              <td className="col-md num">{formatPrice(take.price)}</td>
                              <td className="num"><PnlValue percent={pricing.pnl_percent} usd={pricing.pnl_usd} align="right" /></td>
                              <OpenMark />
                            </tr>
                          );
                        })
                      ) : (
                        <tr>
                          <td colSpan={6}><EmptyState title="No takes" description="This taker has no indexed takes yet." /></td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </TableHoverScope>
              </div>
            )}
          </section>
          {takesQuery.data ? (
            <Pagination
              page={page}
              hasNext={page < takesQuery.data.total_pages}
              onPageChange={(nextPage) => {
                const next = new URLSearchParams(searchParams);
                if (nextPage <= 1) next.delete("page");
                else next.set("page", String(nextPage));
                setSearchParams(next);
              }}
              summary={`${takesQuery.data.total_count.toLocaleString()} takes`}
            />
          ) : null}
        </div>

        <section className="card card-clip" aria-label="Auction breakdown">
          <div className="card-title">
            <span>Auction breakdown</span>
            <strong>{formatCount(taker.auction_breakdown.length)}</strong>
          </div>
          {taker.auction_breakdown.length ? (
            <ul className="m-0 list-none p-0 pb-1">
              {taker.auction_breakdown.map((auction) => {
                const href = `/auction/${auction.chain_id}/${auction.auction_address}`;
                return (
                  <li
                    key={`${auction.chain_id}-${auction.auction_address}`}
                    className="data-row reveal-row flex items-center gap-3 border-b border-divider-subtle px-4 py-2.5 last:border-b-0"
                    tabIndex={0}
                    data-row=""
                    onClick={(event) => handleRowNavigation(event, href, navigate)}
                    onKeyDown={linkRowKeyDown(() => navigate(href))}
                  >
                    <ChainIcon chainId={auction.chain_id} size="xs" />
                    <div className="min-w-0 flex-1">
                      <AuctionAddressValue address={auction.auction_address} chainId={auction.chain_id} />
                      <div className="mt-0.5 font-mono text-[11px] text-tertiary" title={formatDateTime(auction.last_take)}>
                        {formatCount(auction.takes_count)} takes · {formatCompactDateTime(auction.last_take)}
                      </div>
                    </div>
                    <span className="text-data" title={formatUsd(auction.volume_usd)}>
                      {formatCompactUsd(auction.volume_usd)}
                      {auction.paid_usd_take_count < auction.takes_count ? <span className="stat-note">partial</span> : null}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState title="No auctions yet" />
          )}
        </section>
      </div>
    </div>
  );
}
