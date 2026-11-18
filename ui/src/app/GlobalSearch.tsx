import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { api } from "../shared/api/client";
import { formatAddress, formatHash } from "../shared/lib/format";
import { normalizeTransactionHash, withBackgroundLocation } from "../shared/lib/routes";
import { searchResultOpensRound, searchResultRoute, searchTypeLabel } from "../shared/lib/search";
import type { SearchResult } from "../shared/types/api";
import ChainIcon from "../shared/ui/ChainIcon";

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

function hitName(result: SearchResult): string {
  if (result.type === "token") return String(result.metadata?.symbol || formatAddress(result.address_or_hash));
  if (result.type === "transaction" || result.type === "kick_transaction") return formatHash(result.address_or_hash, 10);
  return formatAddress(result.address_or_hash, 8);
}

function hitMeta(result: SearchResult): string | null {
  if (result.type === "token") return result.metadata?.name ? String(result.metadata.name) : null;
  if (result.metadata?.round_id !== undefined && result.metadata?.round_id !== null) return `R${String(result.metadata.round_id)}`;
  return null;
}

/** Search in the top bar: `/` focuses it, ↑/↓ pick a hit, Enter opens it or the full results. */
export default function GlobalSearch() {
  const navigate = useNavigate();
  const location = useLocation();
  const inputRef = useRef<HTMLInputElement>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState("");
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState(0);
  const query = useDebounced(draft.trim(), 180);

  const searchQuery = useQuery({
    queryKey: ["search", query, "bar"],
    queryFn: ({ signal }) => api.search(query, 8, signal),
    enabled: query.length >= 2,
    staleTime: 30_000,
  });
  const hits = useMemo(() => (query.length >= 2 ? searchQuery.data?.results ?? [] : []), [query, searchQuery.data]);

  useEffect(() => setCursor(0), [query]);

  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target;
      if (target instanceof HTMLElement && target.closest("input, textarea, select, [contenteditable='true']")) return;
      event.preventDefault();
      inputRef.current?.focus();
      inputRef.current?.select();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const finish = () => {
    setOpen(false);
    setDraft("");
    inputRef.current?.blur();
  };

  const go = (result: SearchResult) => {
    navigate(searchResultRoute(result), searchResultOpensRound(result) ? { state: withBackgroundLocation(location) } : undefined);
    finish();
  };

  const submit = () => {
    const text = draft.trim();
    if (!text) return;
    if (hits[cursor]) {
      go(hits[cursor]);
      return;
    }
    const txHash = normalizeTransactionHash(text);
    navigate(txHash ? `/tx/${txHash}` : `/search?q=${encodeURIComponent(text)}`);
    finish();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      finish();
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setCursor((current) => Math.min(current + 1, Math.max(hits.length - 1, 0)));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((current) => Math.max(current - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      submit();
    }
  };

  const showMenu = open && query.length >= 2;

  return (
    <div ref={rootRef} className="relative" data-keep-drawer>
      <label className="search-box">
        <Search className="h-3.5 w-3.5 shrink-0" strokeWidth={1.6} aria-hidden="true" />
        <span className="sr-only">Search auctions, takers, transactions and tokens</span>
        <input
          ref={inputRef}
          type="search"
          role="combobox"
          aria-expanded={showMenu}
          aria-controls="global-search-results"
          aria-autocomplete="list"
          placeholder="Auction, taker, tx or token"
          autoComplete="off"
          spellCheck={false}
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        <kbd className="kbd">/</kbd>
      </label>
      {showMenu ? (
        <div id="global-search-results" role="listbox" className="menu search-menu left-0 right-auto w-[min(380px,calc(100vw-24px))]">
          {searchQuery.isLoading ? (
            <div className="px-2 py-2.5 text-[12px] text-tertiary">Searching…</div>
          ) : searchQuery.isError ? (
            <div className="px-2 py-2.5 text-[12px] text-negative">Search is unavailable.</div>
          ) : hits.length ? (
            hits.map((result, index) => (
              <button
                key={`${result.type}:${result.chain_id}:${result.address_or_hash}:${index}`}
                type="button"
                role="option"
                aria-selected={index === cursor}
                className="hit"
                onMouseEnter={() => setCursor(index)}
                onClick={() => go(result)}
              >
                <ChainIcon chainId={result.chain_id} size="xs" />
                <span className="min-w-0 truncate font-mono text-primary">{hitName(result)}</span>
                {hitMeta(result) ? <span className="min-w-0 truncate text-tertiary">{hitMeta(result)}</span> : null}
                <span className="hit-kind">{searchTypeLabel(result.type, false)}</span>
              </button>
            ))
          ) : (
            <div className="px-2 py-2.5 text-[12px] text-tertiary">No matches</div>
          )}
          <button type="button" className="menu-row mt-1 w-full border-t border-divider-subtle pt-2" onClick={submit}>
            <span>All results for “{query}”</span>
            <span className="text-faint">↵</span>
          </button>
        </div>
      ) : null}
    </div>
  );
}
