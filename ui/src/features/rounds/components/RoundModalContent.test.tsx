import { act, cleanup, render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, MemoryRouter, Route, RouterProvider, Routes } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../../../shared/api/client";
import { buildRoundPath, occurrenceKey } from "../../../shared/lib/routes";
import type { RoundDetailResponse, RoundLivePrice } from "../../../shared/types/api";
import RoundModalContent from "./RoundModalContent";

const auction = `0x${"a".repeat(40)}`;
const occurrence = { chain_id: 1, block_hash: `0x${"b".repeat(64)}`, tx_hash: `0x${"c".repeat(64)}`, log_index: 4 };
function details(block: number): RoundDetailResponse {
  return {
    round: { occurrence, chain_id: 1, auction_address: auction, round_id: 1, status: "live", is_active: true,
      from_token: `0x${"d".repeat(40)}`, want_token: `0x${"e".repeat(40)}`, want_token_decimals: 6,
      kicked_at: "2026-09-17T12:00:00Z", activity_at: "2026-09-17T12:00:00Z", take_count: 0, paid_take_count: 0, paid_usd_take_count: 0,
      usd_priced_take_count: 0, sold_amount: "0", paid_amount: null },
    as_of: { 1: { indexed_block: block, indexed_block_hash: `0x${block.toString(16).padStart(64, "0")}`, indexed_timestamp: 1789646400 + block,
      confirmed_block: block, confirmed_block_hash: null, finality_mode: "finalized" } },
  };
}
function price(block: number, value: string): RoundLivePrice {
  const checkpoint = details(block).as_of[1];
  return { occurrence, chain_id: 1, auction_address: auction, round_id: 1, is_active: true,
    indexed_block: block, indexed_block_hash: checkpoint.indexed_block_hash!, indexed_timestamp: checkpoint.indexed_timestamp!, current_price: value };
}
let client: QueryClient;
beforeEach(() => {
  vi.useFakeTimers();
  client = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchInterval: 3000, staleTime: 2000, refetchOnWindowFocus: false } } });
  vi.spyOn(api, "getAuction").mockResolvedValue({ address: auction, version: "1.0.4" } as Awaited<ReturnType<typeof api.getAuction>>);
  vi.spyOn(api, "getAuctionTakes").mockResolvedValue({ as_of: {}, takes: [], available_price_sources: [] });
  vi.spyOn(api, "getChains").mockResolvedValue({ chains: {}, count: 0 });
});
afterEach(() => { cleanup(); client.clear(); vi.restoreAllMocks(); vi.useRealTimers(); });
function mount() {
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[buildRoundPath(1, auction, occurrence)]}><Routes><Route path="/round/:chainId/:auctionAddress/:occurrence" element={<RoundModalContent onClose={() => {}} />} /></Routes></MemoryRouter></QueryClientProvider>);
}
async function settle(ms = 100) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
  await act(async () => { await vi.advanceTimersByTimeAsync(0); });
}

it("refreshes once on snapshot mismatch, then waits for normal polling", async () => {
  let block = 100;
  const detailCalls = vi.spyOn(api, "getRoundDetail").mockImplementation(async () => details(block++));
  const prices = vi.spyOn(api, "getRoundLivePrice").mockRejectedValue(new ApiError(409, "snapshot mismatch"));
  mount();
  await settle();
  await settle();
  expect(prices).toHaveBeenCalledTimes(2);
  expect(detailCalls).toHaveBeenCalledTimes(2);
  await settle(2000);
  expect(prices).toHaveBeenCalledTimes(2);
  expect(detailCalls).toHaveBeenCalledTimes(2);
});

it("cannot display a late price from a different indexed snapshot", async () => {
  vi.spyOn(api, "getRoundDetail").mockResolvedValue(details(100));
  let resolveOld!: (value: RoundLivePrice) => void;
  vi.spyOn(api, "getRoundLivePrice")
    .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
    .mockResolvedValue(price(101, "222"));
  const { container } = mount();
  await settle();
  await act(async () => { client.setQueryData(["round-detail", occurrence], details(101)); });
  await settle();
  expect(container.textContent).toContain("222");
  await act(async () => { resolveOld(price(100, "111")); });
  await settle();
  expect(container.textContent).toContain("222");
  expect(container.textContent).not.toContain("111");
});

it.each(["round-detail", "round-live-price"])("withholds a cached live price when %s refresh fails", async (key) => {
  const roundRequest = vi.spyOn(api, "getRoundDetail").mockResolvedValue(details(100));
  const priceRequest = vi.spyOn(api, "getRoundLivePrice").mockResolvedValue(price(100, "123.456"));
  const { container } = mount();
  await settle();
  expect(container.textContent).toContain("123.456");
  const request = key === "round-detail" ? roundRequest : priceRequest;
  request.mockRejectedValue(new ApiError(503, "Unavailable"));
  act(() => { void client.refetchQueries({ queryKey: [key] }); });
  await settle(1200);
  expect(container.textContent).not.toContain("123.456");
  expect(container.textContent).toContain("R1");
});

it("replaces the route when a selected take moves rounds, preserving search and background state", async () => {
  const correctedOccurrence = { ...occurrence, log_index: 8 };
  const takeOccurrence = { ...occurrence, log_index: 12 };
  const backgroundLocation = { pathname: `/auction/1/${auction}`, search: "?page=3", hash: "", state: null, key: "auction" };
  const state = { backgroundLocation };
  const search = `?take=${occurrenceKey(takeOccurrence)}&priceSource=canonical&from=auction`;
  vi.spyOn(api, "getRoundDetail").mockImplementation(async (requested) => ({
    ...details(100), round: { ...details(100).round, occurrence: requested, is_active: false },
  }));
  vi.spyOn(api, "getTake").mockResolvedValue({
    occurrence: takeOccurrence, round_occurrence: correctedOccurrence,
    auction, chain_id: 1, round_id: 2, take_seq: 1, taker: auction,
    amount_taken: "1", amount_paid: "2", timestamp: "2026-09-17T12:00:00Z",
    tx_hash: takeOccurrence.tx_hash, block_number: 100, confirmed: true,
  });
  const router = createMemoryRouter([
    { path: "/round/:chainId/:auctionAddress/:occurrence", element: <RoundModalContent onClose={() => {}} /> },
  ], { initialEntries: [{ pathname: buildRoundPath(1, auction, occurrence), search, state }] });
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
  await settle();
  await settle();

  expect(router.state.location.pathname).toBe(buildRoundPath(1, auction, correctedOccurrence));
  expect(router.state.historyAction).toBe("REPLACE");
  expect(router.state.location.search).toBe(search);
  expect(router.state.location.state).toEqual(state);
  router.dispose();
});
