import type { CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "../../../shared/api/client";
import { cn, formatAmount, formatCompactDateTime } from "../../../shared/lib/format";
import {
  getChainHealthLabel,
  getChainHealthTone,
  type ChainHealthTone,
} from "../../../shared/lib/health";
import type { HealthChain } from "../../../shared/types/api";
import ChainPill from "../../../shared/ui/ChainPill";
import EmptyState from "../../../shared/ui/EmptyState";
import SkeletonRows from "../../../shared/ui/SkeletonRows";
import StatStrip, { Stat } from "../../../shared/ui/StatStrip";
import { LIVE_REFETCH_INTERVAL_MS } from "../../../shared/lib/polling";

const TONE: Record<ChainHealthTone, string> = {
  healthy: "var(--color-active-mark)",
  indexing: "var(--color-warning-mark)",
  degraded: "var(--color-warning-mark)",
  error: "var(--color-negative)",
  disabled: "var(--color-faint)",
};

function HealthStatus({ chain }: { chain: HealthChain }) {
  const tone = getChainHealthTone(chain);
  return (
    <span className="status">
      <span className={cn("status-dot", tone === "disabled" && "is-ring")} style={{ "--tone": TONE[tone] } as CSSProperties} aria-hidden="true" />
      <span>{getChainHealthLabel(chain)}</span>
    </span>
  );
}

function syncProgress(chain: HealthChain): number | null {
  const startBlock = chain.start_block;
  const confirmed = chain.latest_rpc_head;
  const processed = chain.last_live_processed;
  if (
    startBlock === null
    || startBlock === undefined
    || confirmed === null
    || confirmed === undefined
    || processed === null
    || processed === undefined
    || confirmed < startBlock
  ) {
    return null;
  }
  const baseline = startBlock - 1;
  const total = confirmed - baseline;
  if (total <= 0) {
    return null;
  }
  const completed = Math.max(0, processed - baseline);
  return Math.max(0, Math.min(100, (completed / total) * 100));
}

function syncLabel(chain: HealthChain): string {
  if (!chain.indexed) {
    return "—";
  }
  const processed = chain.last_live_processed != null ? formatAmount(chain.last_live_processed, 0) : "—";
  const confirmed = chain.latest_rpc_head != null ? formatAmount(chain.latest_rpc_head, 0) : "—";
  const progress = syncProgress(chain);

  if (progress == null) {
    return `${processed} / ${confirmed}`;
  }
  return `${processed} / ${confirmed} · ${progress.toFixed(1)}%`;
}

function sortChains(chains: HealthChain[]): HealthChain[] {
  const priority: Record<ChainHealthTone, number> = {
    error: 0,
    degraded: 1,
    indexing: 2,
    healthy: 3,
    disabled: 4,
  };
  return [...chains].sort((left, right) => {
    const leftTone = getChainHealthTone(left);
    const rightTone = getChainHealthTone(right);
    const byTone = priority[leftTone] - priority[rightTone];
    if (byTone !== 0) {
      return byTone;
    }
    return left.chain_id - right.chain_id;
  });
}

function DiscoveryCoverage({ discovery }: { discovery: HealthChain["discovery"] }) {
  const labels = { ok: "No known gaps", partial: "Partial", stale: "Stale", unavailable: "Unavailable" };
  const reasons = { unsupported_version: "Unsupported version", lookup_failed: "Lookup failed", deployment_unresolved: "Deployment block unresolved" };
  return (
    <div className="space-y-1 text-data">
      <div className={discovery.status === "ok" ? "text-secondary" : "text-warning"}>{labels[discovery.status]} · {discovery.known_factory_count} factories</div>
      <div className="text-meta text-tertiary">{discovery.last_success_at != null
        ? `Checked ${formatCompactDateTime(new Date(discovery.last_success_at * 1000).toISOString())}`
        : "No successful evaluation"}</div>
      {discovery.last_error && <div className="text-warning">{discovery.last_error}</div>}
      {discovery.problems.length > 0 && <details>
        <summary className="cursor-pointer text-warning">{discovery.problems.length} known gaps</summary>
        {discovery.problems.map((problem) => <div key={`${problem.factory_address}:${problem.code}`} className="mt-1 break-all text-meta text-secondary">
          {reasons[problem.code]}{problem.version ? ` (${problem.version})` : ""} · {problem.factory_address}
        </div>)}
      </details>}
    </div>
  );
}

export default function StatusPage() {
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => api.getHealth(signal),
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
  });

  const header = (
    <div className="page-head">
      <div>
        <div className="text-[11px] text-tertiary">Indexer health</div>
        <h1 className="page-title m-0">Status</h1>
      </div>
      <div className="text-meta text-tertiary">Refreshes every 3s</div>
    </div>
  );

  if (healthQuery.isLoading) {
    return (
      <div className="space-y-4" aria-busy="true">
        {header}
        <StatStrip label="Network totals" count={5}>
          {["Healthy", "Indexing", "Errors", "Delayed", "Max lag"].map((label) => <Stat key={label} label={label} value="" loading />)}
        </StatStrip>
        <section className="card card-clip">
          <div className="table-wrap">
            <table className="data-table"><tbody><SkeletonRows rows={3} widths={[120, 60, 40, 160, 100, 140, 120]} /></tbody></table>
          </div>
        </section>
      </div>
    );
  }

  if (healthQuery.isError) {
    return (
      <EmptyState
        title="Status unavailable"
        description="The API health view could not be loaded right now."
      />
    );
  }

  const chains = sortChains(healthQuery.data?.chains ?? []);

  if (chains.length === 0) {
    return (
      <EmptyState
        title="No networks available"
        description="No active networks are currently configured for the status view."
      />
    );
  }

  const healthyCount = chains.filter((chain) => getChainHealthTone(chain) === "healthy").length;
  const indexingCount = chains.filter((chain) => getChainHealthTone(chain) === "indexing").length;
  const errorCount = chains.filter((chain) => getChainHealthTone(chain) === "error").length;
  const delayedCount = chains.filter((chain) => getChainHealthTone(chain) === "degraded").length;
  const maxLag = chains
    .filter((chain) => chain.indexed)
    .reduce((max, chain) => Math.max(max, chain.block_lag ?? 0), 0);

  return (
    <div className="space-y-4">
      {header}

      <StatStrip label="Network totals" count={5}>
        <Stat label="Healthy" value={String(healthyCount)} />
        <Stat label="Indexing" value={String(indexingCount)} />
        <Stat label="Errors" value={String(errorCount)} />
        <Stat label="Delayed" value={String(delayedCount)} />
        <Stat label="Max lag" value={formatAmount(maxLag, 0)} suffix="blocks" />
      </StatStrip>

      <section className="card card-clip" aria-label="Networks">
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Network</th>
                <th>Status</th>
                <th className="col-lo num">Lag</th>
                <th className="col-md">Sync</th>
                <th className="col-md">Finality</th>
                <th className="col-lo">Discovery coverage</th>
                <th className="col-xl">Details</th>
              </tr>
            </thead>
            <tbody>
              {chains.map((chain) => {
                const progress = syncProgress(chain);
                const detail = chain.last_error || chain.health_detail;
                return (
                  <tr key={chain.chain_id} className="align-top">
                    <td className="!h-auto !py-2.5">
                      <ChainPill chainId={chain.chain_id} size="sm" className="min-w-0 truncate" />
                      <div className="mt-1 text-[11px] text-tertiary">{chain.network_name} · chain {chain.chain_id}</div>
                    </td>
                    <td className="!h-auto !py-2.5"><HealthStatus chain={chain} /></td>
                    <td className="col-lo num !h-auto !py-2.5">
                      {chain.indexed && chain.block_lag != null ? formatAmount(chain.block_lag, 0) : <span className="text-faint">—</span>}
                    </td>
                    <td className="col-md mono !h-auto !py-2.5">
                      <div>{syncLabel(chain)}</div>
                      {progress != null ? (
                        <span className="bar mt-1.5 w-[140px]" aria-hidden="true"><i style={{ width: `${progress}%` }} /></span>
                      ) : null}
                    </td>
                    <td className="col-md mono !h-auto !py-2.5">
                      {chain.last_confirmed_processed != null ? formatAmount(chain.last_confirmed_processed, 0) : "—"} <span className="text-tertiary">{chain.finality_mode === "finalized" ? "finalized" : "confirmed"}</span>
                    </td>
                    <td className="col-lo !h-auto !py-2.5 whitespace-normal"><DiscoveryCoverage discovery={chain.discovery} /></td>
                    <td className={cn("col-xl !h-auto !py-2.5 text-data", detail ? "text-negative" : "text-faint")} title={detail || undefined}>
                      <div className="max-w-[260px] truncate">{detail || "—"}</div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
