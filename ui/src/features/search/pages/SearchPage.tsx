import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../../../shared/api/client";
import { formatCompactDateTime, formatDateTime } from "../../../shared/lib/format";
import { linkRowKeyDown } from "../../../shared/lib/openRound";
import { handleRowNavigation } from "../../../shared/lib/rowNavigation";
import { buildRoundPathWithSource, roundModalSourceFromLocation, withBackgroundLocation } from "../../../shared/lib/routes";
import { searchResultOpensRound, searchResultRoute, searchTypeLabel } from "../../../shared/lib/search";
import type { SearchResult } from "../../../shared/types/api";
import AddressValue from "../../../shared/ui/AddressValue";
import AuctionAddressValue from "../../../shared/ui/AuctionAddressValue";
import ChainIcon from "../../../shared/ui/ChainIcon";
import EmptyState from "../../../shared/ui/EmptyState";
import RequestError from "../../../shared/ui/RequestError";
import TokenValue from "../../../shared/ui/TokenValue";
import TxHashValue from "../../../shared/ui/TxHashValue";

function groupResults(results: SearchResult[]) {
  return results.reduce<Record<string, SearchResult[]>>((groups, result) => {
    if (!groups[result.type]) {
      groups[result.type] = [];
    }
    groups[result.type].push(result);
    return groups;
  }, {});
}

export default function SearchPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const roundModalSource = roundModalSourceFromLocation(location);
  const [searchParams, setSearchParams] = useSearchParams();
  const query = searchParams.get("q") || "";
  const [draft, setDraft] = useState(query);

  useEffect(() => {
    setDraft(query);
  }, [query]);

  const directRoundMatch = useMemo(() => {
    const match = query.match(/^(\d+)[/:](0x[a-fA-F0-9]{40})[/:](\d+)$/);
    if (!match) return null;
    return {
      chainId: Number(match[1]),
      auctionAddress: match[2],
      roundId: Number(match[3]),
    };
  }, [query]);

  const directRoundQuery = useQuery({
    queryKey: ["round-position-lookup", directRoundMatch],
    queryFn: ({ signal }) => api.getRounds({ chain_id: directRoundMatch!.chainId, auction_address: directRoundMatch!.auctionAddress, round_id: directRoundMatch!.roundId, limit: 1 }, signal),
    enabled: Boolean(directRoundMatch),
  });
  const directRound = directRoundQuery.data?.rounds[0];

  const searchQuery = useQuery({
    queryKey: ["search", query],
    queryFn: ({ signal }) => api.search(query, 30, signal),
    enabled: query.trim().length >= 2,
  });

  const groupedResults = groupResults(searchQuery.data?.results || []);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const next = new URLSearchParams(searchParams);
    if (draft.trim()) next.set("q", draft.trim());
    else next.delete("q");
    setSearchParams(next);
  };

  return (
    <div className="space-y-4">
      <div className="page-head">
        <div>
          <h1 className="page-title m-0">Search</h1>
          <p className="prose-text m-0 mt-1 text-data text-tertiary">Auctions, takers, transactions, token symbols, or a chain:auction:round jump.</p>
        </div>
      </div>
      <form onSubmit={submit} className="flex items-center gap-2">
        <input
          className="filter-input h-9 max-w-xl font-mono"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Address, tx hash, token symbol, or 1:0xAuction:29"
          aria-label="Search query"
        />
        <button className="plain-button h-9" type="submit">
          Search
        </button>
      </form>

      {directRoundMatch && directRoundQuery.isError && !directRoundQuery.data && <RequestError message="Unable to look up this round." onRetry={() => { void directRoundQuery.refetch(); }} />}
      {directRoundMatch && directRoundQuery.isLoading && <div className="text-data text-tertiary">Looking up round…</div>}
      {directRoundMatch && directRoundQuery.data && !directRound && <EmptyState title="Round not found" />}
      {directRoundMatch && directRound ? (
        <section className="card card-clip">
          <div className="card-title"><span>Direct round workspace</span></div>
          <Link
            to={buildRoundPathWithSource(directRoundMatch.chainId, directRoundMatch.auctionAddress, directRound.round_id, roundModalSource)}
            state={withBackgroundLocation(location)}
            className="data-row flex items-center gap-3 px-4 py-2.5 text-data text-primary"
          >
            <ChainIcon chainId={directRoundMatch.chainId} />
            <span className="font-mono">R{directRoundMatch.roundId}</span>
            <span className="font-mono text-tertiary">{directRoundMatch.auctionAddress.slice(0, 8)}…</span>
            <ChevronRight className="ml-auto h-3.5 w-3.5 text-faint" strokeWidth={1.6} />
          </Link>
        </section>
      ) : null}

      {query.trim().length >= 2 && searchQuery.isError && !searchQuery.data && <RequestError message="Unable to search." onRetry={() => { void searchQuery.refetch(); }} />}
      {query.trim().length < 2 ? (
        <EmptyState title="Start with a query" description="Use at least two characters for indexed search, or a chain:auction:round pattern for a direct jump." />
      ) : searchQuery.data?.results.length ? (
        Object.entries(groupedResults).map(([type, results]) => (
          <section key={type} className="card card-clip" aria-label={searchTypeLabel(type as SearchResult["type"])}>
            <div className="card-title">
              <span>{searchTypeLabel(type as SearchResult["type"])}</span>
              <strong>{results.length}</strong>
            </div>
            <ul className="m-0 list-none p-0">
              {results.map((result, index) => {
                const timestamp = result.metadata?.timestamp ? String(result.metadata.timestamp) : null;
                const route = searchResultRoute(result);
                const open = () => navigate(route, searchResultOpensRound(result) ? { state: withBackgroundLocation(location) } : undefined);
                return (
                  <li
                    key={`${result.type}-${result.address_or_hash}-${index}`}
                    className="data-row reveal-row flex items-center gap-3 border-b border-divider-subtle px-4 py-2.5 text-data last:border-b-0"
                    tabIndex={0}
                    data-row=""
                    onClick={(event) => handleRowNavigation(event, route, open)}
                    onKeyDown={linkRowKeyDown(open)}
                  >
                    <ChainIcon chainId={result.chain_id} />
                    <span className="min-w-0">
                      {result.type === "transaction" || result.type === "kick_transaction" ? (
                        <TxHashValue txHash={result.address_or_hash} chainId={result.chain_id} />
                      ) : result.type === "auction" ? (
                        <AuctionAddressValue address={result.address_or_hash} chainId={result.chain_id} width={8} />
                      ) : result.type === "token" ? (
                        <TokenValue
                          address={result.address_or_hash}
                          symbol={String(result.metadata?.symbol || result.address_or_hash)}
                          logoUrl={String(result.metadata?.logo_url || "")}
                          chainId={result.chain_id}
                          showCopy={false}
                        />
                      ) : (
                        <AddressValue address={result.address_or_hash} chainId={result.chain_id} width={8} />
                      )}
                    </span>
                    <span className="min-w-0 truncate text-tertiary" title={timestamp ? formatDateTime(timestamp) : undefined}>
                      {timestamp
                        ? formatCompactDateTime(timestamp)
                        : result.metadata?.round_id
                          ? `Round ${String(result.metadata.round_id)}`
                          : result.type === "token"
                            ? String(result.metadata?.name || "Indexed token")
                            : "Indexed match"}
                    </span>
                    <ChevronRight className="ml-auto h-3.5 w-3.5 shrink-0 text-faint" strokeWidth={1.6} aria-hidden="true" />
                  </li>
                );
              })}
            </ul>
          </section>
        ))
      ) : searchQuery.isLoading ? (
        <div className="text-data text-tertiary">Searching…</div>
      ) : searchQuery.isError && !searchQuery.data ? null : (
        <EmptyState title="No matches" description="No indexed auctions, takers, transactions, or token symbols matched this query." />
      )}
    </div>
  );
}
