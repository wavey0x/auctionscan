import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../../../shared/api/client";
import { formatCompactDateTime, formatDateTime } from "../../../shared/lib/format";
import { buildRoundPathWithSource, roundModalSourceFromLocation, withBackgroundLocation } from "../../../shared/lib/routes";
import type { SearchResult } from "../../../shared/types/api";
import AddressValue from "../../../shared/ui/AddressValue";
import AuctionAddressValue from "../../../shared/ui/AuctionAddressValue";
import ChainIcon from "../../../shared/ui/ChainIcon";
import EmptyState from "../../../shared/ui/EmptyState";
import Panel from "../../../shared/ui/Panel";
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

function typeLabel(type: SearchResult["type"]) {
  switch (type) {
    case "auction":
      return "Auctions";
    case "taker":
      return "Takers";
    case "transaction":
      return "Take transactions";
    case "kick_transaction":
      return "Kick transactions";
    case "token":
      return "Tokens";
    default:
      return type;
  }
}

function buildRoute(result: SearchResult, roundModalSource: ReturnType<typeof roundModalSourceFromLocation>) {
  if (result.type === "auction") {
    return `/auction/${result.chain_id}/${result.address_or_hash}`;
  }

  if (result.type === "taker") {
    return `/taker/${result.address_or_hash}`;
  }

  if (result.type === "token") {
    return `/?chain=${result.chain_id}&filter=${encodeURIComponent(String(result.metadata?.symbol || result.address_or_hash))}`;
  }

  return `/tx/${result.address_or_hash}`;
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
      <Panel className="space-y-3">
        <div>
          <div className="text-title text-primary">Search</div>
          <div className="mt-1 text-data text-tertiary">
            Fast lookup for auctions, takers, transactions, token symbols, and direct round jumps.
          </div>
        </div>
        <form onSubmit={submit} className="flex flex-col gap-2 md:flex-row">
          <input
            className="filter-input"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Address, tx hash, token symbol, or 1:0xAuction:29"
          />
          <button className="plain-button" type="submit">
            Search
          </button>
        </form>
      </Panel>

      {directRoundMatch && directRound ? (
        <Panel className="space-y-2">
          <div className="metric-label">Direct round workspace</div>
          <Link
            to={buildRoundPathWithSource(directRoundMatch.chainId, directRoundMatch.auctionAddress, directRound.occurrence, roundModalSource)}
            state={withBackgroundLocation(location)}
            className="inline-flex items-center gap-3 text-data text-primary underline-offset-4 hover:underline"
          >
            <ChainIcon chainId={directRoundMatch.chainId} />
            <span className="font-mono">R{directRoundMatch.roundId}</span>
            <span className="font-mono text-tertiary">{directRoundMatch.auctionAddress.slice(0, 8)}…</span>
          </Link>
        </Panel>
      ) : null}

      {query.trim().length < 2 ? (
        <EmptyState title="Start with a query" description="Use at least two characters for indexed search, or a chain:auction:round pattern for a direct jump." />
      ) : searchQuery.data?.results.length ? (
        Object.entries(groupedResults).map(([type, results]) => (
          <Panel key={type} className="space-y-2">
            <div className="text-heading text-primary">{typeLabel(type as SearchResult["type"])}</div>
            <div className="space-y-1">
              {results.map((result, index) => {
                const timestamp = result.metadata?.timestamp ? String(result.metadata.timestamp) : null;
                const hasRoundDestination =
                  result.type !== "auction" &&
                  result.type !== "taker" &&
                  Boolean(result.metadata?.auction_address) &&
                  result.metadata?.round_id !== null &&
                  result.metadata?.round_id !== undefined;

                return (
                  <div
                    key={`${result.type}-${result.address_or_hash}-${index}`}
                    className="cursor-pointer rounded-md border border-divider-subtle px-3 py-2 text-data text-secondary hover:bg-background"
                    onClick={() =>
                      navigate(
                        buildRoute(result, roundModalSource),
                        hasRoundDestination ? { state: withBackgroundLocation(location) } : undefined,
                      )
                    }
                  >
                    <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                      <div className="flex min-w-0 items-center gap-3">
                        <ChainIcon chainId={result.chain_id} />
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
                      </div>
                      <div className="text-meta text-tertiary md:shrink-0">{type}</div>
                    </div>
                    <div className="mt-1 text-meta text-tertiary">
                      {timestamp
                        ? `${formatCompactDateTime(timestamp)} · ${formatDateTime(timestamp)}`
                        : result.metadata?.round_id
                          ? `Round ${String(result.metadata.round_id)}`
                          : result.type === "token"
                            ? String(result.metadata?.name || "Indexed token")
                            : "Indexed match"}
                    </div>
                  </div>
                );
              })}
            </div>
          </Panel>
        ))
      ) : searchQuery.isFetching ? (
        <Panel className="text-data text-tertiary">Searching…</Panel>
      ) : (
        <EmptyState title="No matches" description="No indexed auctions, takers, transactions, or token symbols matched this query." />
      )}
    </div>
  );
}
