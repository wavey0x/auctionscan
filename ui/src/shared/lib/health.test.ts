import { describe, expect, it } from "vitest";

import type { HealthChain } from "../types/api";
import { getChainHealthLabel, getChainHealthTone, summarizeNetworkHealth } from "./health";

const chain: HealthChain = {
  chain_id: 1,
  short_name: "ETH",
  reorg_count: 0, network_name: "ethereum", name: "Ethereum", indexed: true,
  health: "ok", block_lag: 0, last_success_at: 100, latest_rpc_head_timestamp: 100,
  finality_mode: "finalized", confirmed_head_hash: "0xaa", confirmed_head_timestamp: 90,
  last_confirmed_hash: "0xaa", last_finality_advance_at: 100, finality_warning: null,
  health_detail: null,
  discovery: { status: "ok", known_factory_count: 1, last_attempt_at: 100, last_success_at: 100, last_error: null, problems: [] },
};

describe("indexer health", () => {
  it("does not show healthy when a stopped writer has zero stored lag", () => {
    expect(getChainHealthLabel({ ...chain, health: "stale" })).toBe("Stale");
    expect(getChainHealthTone({ ...chain, health: "stale" })).toBe("degraded");
  });
  it("keeps a known error ahead of stale or finality warnings", () => {
    expect(getChainHealthLabel({ ...chain, health: "stale", last_error: "Reorg failed" })).toBe("Error");
  });
  it("uses live lag and propagates delayed finality to the footer", () => {
    expect(getChainHealthLabel({ ...chain, block_lag: 2 })).toBe("Indexing");
    expect(summarizeNetworkHealth([{ ...chain, health: "degraded" }, chain], false)).toBe("degraded");
  });
});
