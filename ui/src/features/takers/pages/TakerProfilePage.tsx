import MetricCoverage from "../../../shared/ui/MetricCoverage";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { api } from "../../../shared/api/client";
import { formatCompactDateTime, formatDateTime, formatPrice, formatUsd } from "../../../shared/lib/format";
import { DEFAULT_PRICE_SOURCE, getTakerTakePricingBySource, resolvePriceSource, shouldShowPriceSourceSelector } from "../../../shared/lib/pricingSource";
import { handleRowNavigation } from "../../../shared/lib/rowNavigation";
import { buildTakePath, withBackgroundLocation } from "../../../shared/lib/routes";
import AuctionAddressValue from "../../../shared/ui/AuctionAddressValue";
import ChainIcon from "../../../shared/ui/ChainIcon";
import EmptyState from "../../../shared/ui/EmptyState";
import RequestError from "../../../shared/ui/RequestError";
import Pagination from "../../../shared/ui/Pagination";
import Panel from "../../../shared/ui/Panel";
import PnlValue from "../../../shared/ui/PnlValue";
import PriceSourceSelect from "../../../shared/ui/PriceSourceSelect";
import Skeleton from "../../../shared/ui/Skeleton";
import StackedListRow from "../../../shared/ui/StackedListRow";
import StatGrid from "../../../shared/ui/StatGrid";
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
      <div className="space-y-4">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (detailQuery.isError && !detailQuery.data) {
    return <RequestError message="Unable to load taker profile." onRetry={() => { void detailQuery.refetch(); }} />;
  }

  if (!detailQuery.data) {
    return <EmptyState title="Taker not found" description="The requested taker profile could not be loaded." />;
  }

  return (
    <div className="space-y-4">
      {detailQuery.isError && <RequestError message="Could not refresh taker profile. Showing previously loaded data." onRetry={() => { void detailQuery.refetch(); }} />}
      <Panel className="space-y-4">
        <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
          <div>
            <div className="text-title text-primary">Taker profile</div>
            <div className="mt-1">
              <TakerAddressValue
                address={detailQuery.data.taker}
                chainId={detailQuery.data.active_chains[0]}
                width={8}
                showBlockie
                blockieSize={26}
                className="[&_.identity-link]:text-[14px] [&_.identity-link]:text-primary"
              />
            </div>
          </div>
          <Link to="/takers" className="text-meta text-tertiary underline-offset-4 hover:text-primary hover:underline">
            Back to takers
          </Link>
        </div>

        <StatGrid columns={2} className="xl:grid-cols-5">
          <div>
            <div className="metric-label">Total takes</div>
            <div className="metric-value">{detailQuery.data.total_takes.toLocaleString()}</div>
          </div>
          <div>
            <div className="metric-label">Auctions</div>
            <div className="metric-value">{detailQuery.data.unique_auctions.toLocaleString()}</div>
          </div>
          <div>
            <div className="metric-label">Chains</div>
            <div className="metric-value">{detailQuery.data.unique_chains.toLocaleString()}</div>
          </div>
          <div>
            <div className="metric-label">Volume</div>
            <div className="metric-value">{formatUsd(detailQuery.data.total_volume_usd)}</div>
            <MetricCoverage count={detailQuery.data.paid_usd_take_count} total={detailQuery.data.total_takes} />
          </div>
          <div>
            <div className="metric-label">Last take</div>
            <div className="metric-value font-mono" title={formatDateTime(detailQuery.data.last_take)}>
              {formatCompactDateTime(detailQuery.data.last_take)}
            </div>
          </div>
        </StatGrid>

        <div className="flex flex-wrap gap-1">
          {detailQuery.data.active_chains.map((chainId) => (
            <ChainIcon key={chainId} chainId={chainId} size="md" />
          ))}
        </div>
      </Panel>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <Panel padded={false}>
          {takesQuery.data ? (
            <div className="flex items-center justify-between gap-3 px-3 pt-3 md:px-4">
              <div className="flex items-center gap-3">
                <div className="text-heading text-primary">Recent takes</div>
                {showPriceSourceSelector ? (
                  <PriceSourceSelect
                    value={selectedPriceSource}
                    options={sourceOptions}
                    onChange={setPriceSource}
                  />
                ) : null}
              </div>
              <div>
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
              </div>
            </div>
          ) : (
            <div className="px-3 pt-3">
              <div className="text-heading text-primary">Recent takes</div>
            </div>
          )}
          {takesQuery.isError && <RequestError message={takesQuery.data ? "Could not refresh takes. Showing previously loaded data." : "Unable to load takes."} onRetry={() => { void takesQuery.refetch(); }} />}
          {takesQuery.isLoading ? (
            <div className="space-y-2 p-3">
              {Array.from({ length: 8 }).map((_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
              ))}
            </div>
          ) : takesQuery.isError && !takesQuery.data ? null : takesQuery.data?.takes.length ? (
            <>
              <div className="md:hidden">
                {takesQuery.data.takes.map((take, index) => {
                  const pricing = getTakerTakePricingBySource(take, selectedPriceSource);
                  return (
                    <StackedListRow
                      key={`mobile-${take.tx_hash}-${index}`}
                      interactive
                      className="space-y-2"
                      onClick={(event) =>
                        handleRowNavigation(
                          event,
                          buildTakePath(take),
                          (to) => navigate(to, { state: withBackgroundLocation(location) }),
                        )
                      }
                      onAuxClick={(event) =>
                        handleRowNavigation(
                          event,
                          buildTakePath(take),
                          (to) => navigate(to, { state: withBackgroundLocation(location) }),
                        )
                      }
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex items-center gap-2">
                          <ChainIcon chainId={take.chain_id} />
                          <span className="font-mono text-primary">R{take.round_id}</span>
                        </div>
                        <div className="font-mono text-meta text-tertiary" title={formatDateTime(take.timestamp)}>
                          {formatCompactDateTime(take.timestamp)}
                        </div>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="metric-label">Price</span>
                        <span className="font-mono text-primary">{formatPrice(take.price)}</span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="metric-label">PnL</span>
                        <PnlValue percent={pricing.pnl_percent} usd={pricing.pnl_usd} compact align="right" />
                      </div>
                      <div className="min-w-0">
                        <AuctionAddressValue address={take.auction_address} chainId={take.chain_id} />
                      </div>
                    </StackedListRow>
                  );
                })}
              </div>
              <div className="hidden md:block table-wrap">
                <TableHoverScope>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>Chain</th>
                        <th>Round</th>
                        <th>Time</th>
                        <th className="text-right">Price</th>
                        <th>PnL</th>
                        <th>Auction</th>
                      </tr>
                    </thead>
                    <tbody>
                      {takesQuery.data.takes.map((take, index) => {
                        const pricing = getTakerTakePricingBySource(take, selectedPriceSource);
                        return (
                          <tr
                            key={`${take.tx_hash}-${index}`}
                            className="data-row"
                            onClick={(event) =>
                              handleRowNavigation(
                                event,
                                buildTakePath(take),
                                (to) => navigate(to, { state: withBackgroundLocation(location) }),
                              )
                            }
                            onAuxClick={(event) =>
                              handleRowNavigation(
                                event,
                                buildTakePath(take),
                                (to) => navigate(to, { state: withBackgroundLocation(location) }),
                              )
                            }
                          >
                            <td>
                              <ChainIcon chainId={take.chain_id} />
                            </td>
                            <td>
                              <Link
                                to={buildTakePath(take)}
                                state={withBackgroundLocation(location)}
                                className="font-mono text-primary underline-offset-4 hover:underline"
                              >
                                R{take.round_id}
                              </Link>
                            </td>
                            <td className="font-mono text-primary" title={formatDateTime(take.timestamp)}>
                              {formatCompactDateTime(take.timestamp)}
                            </td>
                            <td className="text-right font-mono text-primary">{formatPrice(take.price)}</td>
                            <td>
                              <PnlValue percent={pricing.pnl_percent} usd={pricing.pnl_usd} className="w-[4.8rem]" />
                            </td>
                            <td>
                              <AuctionAddressValue address={take.auction_address} chainId={take.chain_id} />
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </TableHoverScope>
              </div>
            </>
          ) : (
            <div className="p-3">
              <EmptyState title="No takes" description="This taker has no indexed takes yet." />
            </div>
          )}
        </Panel>

        <Panel className="space-y-3">
          <div className="text-heading text-primary">Auction breakdown</div>
          <div className="space-y-2">
            {detailQuery.data.auction_breakdown.map((auction) => (
              <div
                key={`${auction.chain_id}-${auction.auction_address}`}
                className="cursor-pointer rounded-md border border-divider-subtle px-3 py-3 hover:bg-background"
                onClick={() => navigate(`/auction/${auction.chain_id}/${auction.auction_address}`)}
              >
                <div className="flex items-center justify-between">
                  <ChainIcon chainId={auction.chain_id} />
                  <span className="font-mono text-data text-primary">{auction.takes_count} takes</span>
                </div>
                <div className="mt-2">
                  <AuctionAddressValue address={auction.auction_address} chainId={auction.chain_id} />
                </div>
                <div className="mt-2 font-mono text-meta text-tertiary" title={formatDateTime(auction.last_take)}>
                  {formatUsd(auction.volume_usd)} <MetricCoverage count={auction.paid_usd_take_count} total={auction.takes_count} /> · {formatCompactDateTime(auction.last_take)}
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}
