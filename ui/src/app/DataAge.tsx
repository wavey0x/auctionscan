import { useEffect, useRef, useState, type CSSProperties } from "react";
import { ArrowUpRight } from "lucide-react";
import { Link } from "react-router-dom";

import { cn, formatCount } from "../shared/lib/format";
import { getChainHealthLabel, getChainHealthTone, summarizeNetworkHealth, type ChainHealthTone } from "../shared/lib/health";
import type { HealthChain } from "../shared/types/api";
import ChainIcon from "../shared/ui/ChainIcon";

const TONE: Record<ChainHealthTone, string> = {
  healthy: "var(--color-active-mark)",
  indexing: "var(--color-warning-mark)",
  degraded: "var(--color-warning-mark)",
  error: "var(--color-negative)",
  disabled: "var(--color-faint)",
};

function ago(seconds: number | null): string {
  if (seconds === null) return "never";
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86_400)}d ago`;
}

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Math.floor(Date.now() / 1000)), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);
  return now;
}

/**
 * The data-age control: how fresh the index is, in the bar's own words. The
 * dot pulses once when a newer block lands; the menu lists each network.
 */
export default function DataAge({
  chains,
  hasError,
  docsHref,
}: {
  chains: HealthChain[] | undefined;
  hasError: boolean;
  docsHref: string;
}) {
  const now = useNow(1000);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const tone = summarizeNetworkHealth(chains, hasError);
  const indexed = (chains ?? []).filter((chain) => chain.indexed);
  const lastSuccess = indexed.reduce<number | null>((latest, chain) => {
    const value = chain.last_success_at ?? null;
    return value !== null && (latest === null || value > latest) ? value : latest;
  }, null);
  const head = indexed.reduce((max, chain) => Math.max(max, chain.last_live_processed ?? 0), 0);
  const previousHead = useRef(head);
  const [pulse, setPulse] = useState(0);

  useEffect(() => {
    if (head > previousHead.current && previousHead.current > 0) setPulse((value) => value + 1);
    previousHead.current = head;
  }, [head]);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const age = lastSuccess === null ? null : Math.max(0, now - lastSuccess);
  const label = hasError ? "Status unavailable" : age === null ? "Waiting for index" : `Updated ${ago(age)}`;

  return (
    <div ref={rootRef} className="relative" data-keep-drawer>
      <button
        type="button"
        className={cn("data-age", (tone === "degraded" || tone === "error") && "text-warning")}
        aria-expanded={open}
        aria-haspopup="true"
        aria-label={`${label}. Show indexing status`}
        title={label}
        onClick={() => setOpen((value) => !value)}
      >
        <span
          key={pulse}
          aria-hidden="true"
          className={cn("status-dot", pulse > 0 && "pulse-once")}
          style={{ "--tone": TONE[tone] } as CSSProperties}
        />
        <span className="data-age-label">{label}</span>
      </button>
      {open ? (
        <div className="menu" role="dialog" aria-label="Indexing status">
          {indexed.length ? indexed.map((chain) => {
            const chainTone = getChainHealthTone(chain);
            const chainAge = chain.last_success_at != null ? Math.max(0, now - chain.last_success_at) : null;
            return (
              <div key={chain.chain_id} className="menu-row" title={chain.health_detail ?? undefined}>
                <span className="inline-flex items-center gap-2 text-primary">
                  <span className="status-dot" style={{ "--tone": TONE[chainTone] } as CSSProperties} aria-hidden="true" />
                  <ChainIcon chainId={chain.chain_id} size="xs" />
                  {chain.name}
                  {chainTone !== "healthy" ? <em className="not-italic text-warning">{getChainHealthLabel(chain)}</em> : null}
                </span>
                <span className="inline-flex items-center gap-3">
                  <strong title="Last indexed block">{chain.last_live_processed != null ? formatCount(chain.last_live_processed) : "—"}</strong>
                  <span className="w-16 text-right text-tertiary">{ago(chainAge)}</span>
                </span>
              </div>
            );
          }) : (
            <div className="menu-row text-tertiary">{hasError ? "The status endpoint did not answer." : "No indexed networks yet."}</div>
          )}
          <div className="menu-group">
            <Link to="/status" className="menu-row" onClick={() => setOpen(false)}>
              <span>Indexer status</span>
              <span className="text-faint">→</span>
            </Link>
            <Link to="/pricing" className="menu-row" onClick={() => setOpen(false)}>
              <span>Pricing method</span>
              <span className="text-faint">→</span>
            </Link>
            <a href={docsHref} target="_blank" rel="noreferrer" className="menu-row" onClick={() => setOpen(false)}>
              <span>API docs</span>
              <ArrowUpRight className="h-3.5 w-3.5 text-faint" strokeWidth={1.6} />
            </a>
          </div>
        </div>
      ) : null}
    </div>
  );
}
