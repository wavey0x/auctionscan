
import { act, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import App from "./App";
import { api } from "../shared/api/client";
import type { RoundListItem } from "../shared/types/api";

vi.mock("../shared/api/client", () => ({
  api: {
    getRounds: vi.fn(),
    getChains: vi.fn().mockResolvedValue({ chains: {} }),
    getAuctionVersions: vi.fn().mockResolvedValue({ versions: [] }),
    getHealth: vi.fn().mockResolvedValue({ chains: [] }),
  },
}));

const round: RoundListItem = {
  occurrence: { chain_id: 1, block_hash: `0x${"01".repeat(32)}`, tx_hash: `0x${"02".repeat(32)}`, log_index: 0 },
  chain_id: 1, auction_address: `0x${"aa".repeat(20)}`, round_id: 1,
  status: "live", is_active: true,
  from_token: `0x${"bb".repeat(20)}`, from_token_symbol: "BEFORE", from_token_name: "From token",
  from_token_decimals: 18, from_token_logo_url: null,
  want_token: `0x${"cc".repeat(20)}`, want_token_symbol: "WANT", want_token_name: "Want token",
  want_token_decimals: 6, want_token_logo_url: null,
  kicked_at: "2026-09-17T12:00:00Z", scheduled_end_at: "2026-09-18T12:00:00Z",
  end_at: "2026-09-18T12:00:00Z", last_take_at: null, activity_at: "2026-09-17T12:00:00Z",
  take_count: 0, sold_amount: "0", paid_amount: null, paid_take_count: 0,
  avg_execution_price: null, last_take_price: null, available_amount: "500", initial_available: "500",
  receiver: null, receiver_name: null, version: "1.0.4", update_interval: 60,
  decay_percent: "0.25%", auction_length: 86400,
  starting_price: "100", starting_price_per_unit: "0.2", minimum_price: null,
  expected_price_per_unit: null, kick_market_quote: null, kick_market_quote_usd: null,
  paid_usd_take_count: 0, total_actual_paid_usd: null, total_market_quote_usd: null,
  total_auction_profit_usd: null, total_auction_profit_bps: null,
  usd_priced_take_count: 0, priced_take_count: null, total_take_count: null,
  priced_volume_share: null, pricing_by_source: null,
};

afterEach(() => vi.useRealTimers());

it("refreshes visible rounds without navigation or a window-focus event", async () => {
  vi.useFakeTimers();
  const response = { as_of: {}, rounds: [round], total: 1, page: 1, per_page: 15, has_next: false };
  vi.mocked(api.getRounds).mockResolvedValue(response);
  const view = render(<App />);
  try {
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(screen.getAllByText("500 BEFORE").length).toBeGreaterThan(0);
    vi.mocked(api.getRounds).mockResolvedValue({
      ...response, rounds: [{ ...round, from_token_symbol: "AFTER" }],
    });
    await act(async () => { await vi.advanceTimersByTimeAsync(3_100); });
    expect(screen.getAllByText("500 AFTER").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("500 BEFORE")).toHaveLength(0);
    expect(api.getRounds).toHaveBeenCalledTimes(2);
  } finally {
    view.unmount();
  }
});
