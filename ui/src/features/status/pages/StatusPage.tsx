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
import Panel from "../../../shared/ui/Panel";
import Skeleton from "../../../shared/ui/Skeleton";
import StackedListRow from "../../../shared/ui/StackedListRow";
import StatGrid from "../../../shared/ui/StatGrid";

function toneClasses(tone: ChainHealthTone) {
  if (tone === "healthy") {
    return {
      dot: "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.24)]",
      chip: "border-emerald-500/25 text-emerald-700 dark:text-emerald-300",
      text: "text-emerald-700 dark:text-emerald-300",
    };
  }
  if (tone === "indexing" || tone === "degraded") {
    return {
      dot: "bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.2)]",
      chip: "border-amber-500/25 text-amber-700 dark:text-amber-300",
      text: "text-amber-700 dark:text-amber-300",
    };
  }
  if (tone === "error") {
    return {
      dot: "bg-rose-400 shadow-[0_0_8px_rgba(251,113,133,0.22)]",
      chip: "border-rose-500/25 text-rose-700 dark:text-rose-300",
      text: "text-rose-700 dark:text-rose-300",
    };
  }
  return {
    dot: "bg-slate-400 shadow-[0_0_8px_rgba(148,163,184,0.16)]",
    chip: "border-slate-400/25 text-slate-600 dark:text-slate-400",
    text: "text-slate-600 dark:text-slate-400",
  };
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

function SummaryMetric({
  label,
  value,
  className,
}: {
  label: string;
  value: string;
  className?: string;
}) {
  return (
    <div className="min-w-20">
      <div className="metric-label">{label}</div>
      <div className={cn("mt-0.5 font-mono text-data text-primary", className)}>{value}</div>
    </div>
  );
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

function StatusSkeleton() {
  return (
    <div className="space-y-3">
      <div className="flex items-end justify-between gap-3">
        <div className="space-y-1">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-5 w-24" />
        </div>
        <Skeleton className="h-3 w-24" />
      </div>

      <Panel className="flex flex-wrap gap-4 py-2">
        {Array.from({ length: 5 }).map((_, index) => (
          <div key={index} className="space-y-1">
            <Skeleton className="h-3 w-14" />
            <Skeleton className="h-4 w-12" />
          </div>
        ))}
      </Panel>

      <Panel padded={false}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px]">
            <thead>
              <tr className="border-b border-divider-subtle">
                {Array.from({ length: 7 }).map((_, index) => (
                  <th key={index} className="px-3 py-2 text-left">
                    <Skeleton className="h-3 w-16" />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Array.from({ length: 4 }).map((_, index) => (
                <tr key={index} className="border-b border-divider-subtle last:border-b-0">
                  {Array.from({ length: 7 }).map((__, inner) => (
                    <td key={inner} className="px-3 py-2">
                      <Skeleton className="h-4 w-full" />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

export default function StatusPage() {
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => api.getHealth(signal),
    refetchInterval: 3_000,
  });

  if (healthQuery.isLoading) {
    return <StatusSkeleton />;
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
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="space-y-1">
          <div className="metric-label">Indexer health</div>
          <h1 className="text-heading text-primary">Status</h1>
        </div>
        <div className="text-meta text-tertiary">Refreshes every 3s</div>
      </div>

      <Panel className="py-2">
        <StatGrid columns={2} className="gap-x-5 gap-y-2 md:grid-cols-5">
          <SummaryMetric label="Healthy" value={String(healthyCount)} className="text-emerald-700 dark:text-emerald-300" />
          <SummaryMetric label="Indexing" value={String(indexingCount)} className="text-amber-700 dark:text-amber-300" />
          <SummaryMetric label="Errors" value={String(errorCount)} className={errorCount > 0 ? "text-rose-700 dark:text-rose-300" : ""} />
          <SummaryMetric label="Delayed" value={String(delayedCount)} className="text-slate-600 dark:text-slate-400" />
          <SummaryMetric label="Max lag" value={`${formatAmount(maxLag, 0)} blk`} />
        </StatGrid>
      </Panel>

      <Panel padded={false}>
        <div className="md:hidden">
          {chains.map((chain) => {
            const tone = getChainHealthTone(chain);
            const classes = toneClasses(tone);

            return (
              <StackedListRow key={`mobile-${chain.chain_id}`} className="space-y-2">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <span
                      aria-hidden="true"
                      className={cn("mt-1 h-2 w-2 shrink-0 rounded-full ring-1 ring-white/10", classes.dot)}
                    />
                    <div className="min-w-0">
                      <ChainPill chainId={chain.chain_id} size="sm" className="min-w-0 truncate" />
                      <div className="mt-1 text-meta text-tertiary">
                        {chain.network_name} · chain {chain.chain_id}
                      </div>
                    </div>
                  </div>
                  <span className={cn("inline-flex rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.12em]", classes.chip)}>
                    {getChainHealthLabel(chain)}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-x-4 gap-y-2">
                  <div>
                    <div className="metric-label">Lag</div>
                    <div className="mt-1 font-mono text-data text-primary">
                      {chain.indexed && chain.block_lag != null ? `${formatAmount(chain.block_lag, 0)} blk` : "—"}
                    </div>
                  </div>
                  <div>
                    <div className="metric-label">Sync</div>
                    <div className="mt-1 font-mono text-data text-primary">{syncLabel(chain)}</div>
                  </div>
                </div>
                <div>
                  <div className="metric-label">Finality</div>
                  <div className="mt-1 font-mono text-data text-primary">
                    {chain.last_confirmed_processed != null ? formatAmount(chain.last_confirmed_processed, 0) : "—"} {chain.finality_mode === "finalized" ? "finalized" : "confirmed"}
                  </div>
                </div>
                <div>
                  <div className="metric-label mb-1">Discovery coverage</div>
                  <DiscoveryCoverage discovery={chain.discovery} />
                </div>
                {(chain.last_error || chain.health_detail) ? (
                  <div>
                    <div className="metric-label">Details</div>
                    <div className="mt-1 text-data text-negative">{(chain.last_error || chain.health_detail)}</div>
                  </div>
                ) : null}
              </StackedListRow>
            );
          })}
        </div>
        <div className="hidden md:block overflow-x-auto">
          <table className="w-full min-w-[860px] text-left">
            <thead>
              <tr className="border-b border-divider-subtle">
                <th className="table-header px-3 py-2">Network</th>
                <th className="table-header px-3 py-2">Status</th>
                <th className="table-header px-3 py-2">Lag</th>
                <th className="table-header px-3 py-2">Sync</th>
                <th className="table-header px-3 py-2">Finality</th>
                <th className="table-header px-3 py-2">Discovery coverage</th>
                <th className="table-header px-3 py-2">Details</th>
              </tr>
            </thead>
            <tbody>
              {chains.map((chain) => {
                const tone = getChainHealthTone(chain);
                const classes = toneClasses(tone);

                return (
                  <tr key={chain.chain_id} className="border-b border-divider-subtle last:border-b-0">
                    <td className="px-3 py-2">
                      <div className="flex min-w-0 items-center gap-2">
                        <span
                          aria-hidden="true"
                          className={cn("h-2 w-2 shrink-0 rounded-full ring-1 ring-white/10", classes.dot)}
                        />
                        <ChainPill chainId={chain.chain_id} size="sm" className="min-w-0 truncate" />
                      </div>
                      <div className="mt-1 text-meta text-tertiary">
                        {chain.network_name} · chain {chain.chain_id}
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <span className={cn("inline-flex rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-[0.12em]", classes.chip)}>
                        {getChainHealthLabel(chain)}
                      </span>
                    </td>
                    <td className="px-3 py-2 font-mono text-data text-primary">
                      {chain.indexed && chain.block_lag != null ? `${formatAmount(chain.block_lag, 0)} blk` : "—"}
                    </td>
                    <td className="px-3 py-2 font-mono text-data text-primary">
                      {syncLabel(chain)}
                    </td>
                    <td className="px-3 py-2 font-mono text-data text-primary">
                      {chain.last_confirmed_processed != null ? formatAmount(chain.last_confirmed_processed, 0) : "—"} {chain.finality_mode === "finalized" ? "finalized" : "confirmed"}
                    </td>
                    <td className="px-3 py-2"><DiscoveryCoverage discovery={chain.discovery} /></td>
                    <td
                      className={cn(
                        "px-3 py-2 text-data",
                        (chain.last_error || chain.health_detail) ? "text-rose-700 dark:text-rose-300" : "text-tertiary",
                      )}
                      title={(chain.last_error || chain.health_detail) || undefined}
                    >
                      <div className="max-w-[280px] truncate">
                        {(chain.last_error || chain.health_detail) || "—"}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
