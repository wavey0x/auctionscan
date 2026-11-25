import { act, cleanup, fireEvent, render } from "@testing-library/react";
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
    round: { occurrence, chain_id: 1, auction_address: auction, round_id: 1, status: "live", is_active: true, protocol: "yearn",
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
afterEach(() => { cleanup(); client.clear(); vi.restoreAllMocks(); vi.useRealTimers(); window.localStorage.clear(); });
function mount() {
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[buildRoundPath(1, auction, 1)]}><Routes><Route path="/round/:chainId/:auctionAddress/:roundId" element={<RoundModalContent onClose={() => {}} />} /></Routes></MemoryRouter></QueryClientProvider>);
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
  await act(async () => { client.setQueryData(["round-detail", 1, auction, 1], details(101)); });
  await settle();
  expect(container.textContent).toContain("222");
  await act(async () => { resolveOld(price(100, "111")); });
  await settle();
  expect(container.textContent).toContain("222");
  expect(container.textContent).not.toContain("111");
});

it("resolves a numbered URL before loading takes and prices for the exact event", async () => {
  let resolveRound!: (value: RoundDetailResponse) => void;
  const roundRequest = vi.spyOn(api, "getRoundDetail").mockImplementation(() => new Promise((resolve) => { resolveRound = resolve; }));
  const priceRequest = vi.spyOn(api, "getRoundLivePrice").mockResolvedValue(price(100, "123.456"));
  mount();
  await settle();
  expect(roundRequest).toHaveBeenCalledWith(1, auction, 1, expect.any(AbortSignal));
  expect(api.getAuctionTakes).not.toHaveBeenCalled();
  expect(priceRequest).not.toHaveBeenCalled();
  await act(async () => { resolveRound(details(100)); });
  await settle();
  expect(api.getAuctionTakes).toHaveBeenCalledWith(1, auction, occurrence, 200, expect.any(AbortSignal));
  expect(priceRequest).toHaveBeenCalledWith(occurrence, expect.objectContaining({ indexed_block: 100 }), expect.any(AbortSignal));
});

it("discards a pending price when the same round number resolves to a replacement event", async () => {
  vi.spyOn(api, "getRoundDetail").mockResolvedValue(details(100));
  let resolveOld!: (value: RoundLivePrice) => void;
  const replacement = { ...occurrence, block_hash: `0x${"f".repeat(64)}` };
  vi.spyOn(api, "getRoundLivePrice")
    .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
    .mockResolvedValue({ ...price(100, "222"), occurrence: replacement });
  const { container } = mount();
  await settle();
  await act(async () => { client.setQueryData(["round-detail", 1, auction, 1], {
    ...details(100), round: { ...details(100).round, occurrence: replacement },
  }); });
  await settle();
  expect(api.getAuctionTakes).toHaveBeenLastCalledWith(1, auction, replacement, 200, expect.any(AbortSignal));
  expect(container.textContent).toContain("222");
  await act(async () => { resolveOld(price(100, "111")); });
  await settle();
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
  vi.spyOn(api, "getRoundDetail").mockImplementation(async (_chain, _auction, requestedRoundId) => ({
    ...details(100), round: { ...details(100).round, round_id: requestedRoundId, occurrence: requestedRoundId === 2 ? correctedOccurrence : occurrence, is_active: false },
  }));
  vi.spyOn(api, "getTake").mockResolvedValue({
    occurrence: takeOccurrence, round_occurrence: correctedOccurrence,
    auction, chain_id: 1, round_id: 2, take_seq: 1, taker: auction,
    amount_taken: "1", amount_paid: "2", timestamp: "2026-09-17T12:00:00Z",
    tx_hash: takeOccurrence.tx_hash, block_number: 100, confirmed: true,
  });
  const router = createMemoryRouter([
    { path: "/round/:chainId/:auctionAddress/:roundId", element: <RoundModalContent onClose={() => {}} /> },
  ], { initialEntries: [{ pathname: buildRoundPath(1, auction, 1), search, state }] });
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
  await settle();
  await settle();

  expect(router.state.location.pathname).toBe(buildRoundPath(1, auction, 2));
  expect(router.state.historyAction).toBe("REPLACE");
  expect(router.state.location.search).toBe(search);
  expect(router.state.location.state).toEqual(state);
  router.dispose();
});

function mountRound(overrides: Partial<RoundDetailResponse["round"]>) {
  vi.spyOn(api, "getRoundDetail").mockResolvedValue({ ...details(100), round: { ...details(100).round, ...overrides } });
  vi.spyOn(api, "getRoundLivePrice").mockResolvedValue(price(100, "9"));
  return mount();
}

it("leads a live round with what is still open and holds the result until a take lands", async () => {
  const { container } = mountRound({ initial_available: "100", available_amount: "100", expected_price_per_unit: "2" });
  await settle();
  const text = container.textContent ?? "";
  for (const label of ["Remaining", "Price now", "Time left", "4.5× quote", "none yet"]) expect(text).toContain(label);
  for (const label of ["Received", "PnL", "Kicked"]) expect(text).not.toContain(label);
});

it("adds the result to a live round once it has a take", async () => {
  const { container } = mountRound({
    take_count: 1, paid_take_count: 1, initial_available: "100", available_amount: "60", sold_amount: "40", paid_amount: "80",
  });
  await settle();
  const text = container.textContent ?? "";
  for (const label of ["Remaining", "40% of 100 sold", "Sold", "Received", "PnL"]) expect(text).toContain(label);
});

const ended = { status: "expired", is_active: false, initial_available: "100", scheduled_end_at: "2026-09-18T12:00:00Z", end_at: "2026-09-18T12:00:00Z" } as const;

it.each([
  ["all but dust sold", { take_count: 2, paid_take_count: 2, available_amount: "0.000000000000000001", sold_amount: "100", paid_amount: "50" }],
  ["40% sold", { take_count: 1, paid_take_count: 1, available_amount: "60", sold_amount: "40", paid_amount: "20" }],
  ["nothing sold", { take_count: 0, available_amount: "100", sold_amount: "0" }],
])("says an expired round left %s", async (statement, sales) => {
  const { container } = mountRound({ ...ended, ...sales });
  await settle();
  const text = container.textContent ?? "";
  // The head says it expired; the facts line gives the figures without naming them.
  expect(text).toContain("1d 0h");
  expect(text).not.toContain("expired after");
  expect(text).not.toContain("Kicked");
  expect(text).toContain(statement);
  expect(text).not.toContain("Time left");
  // A round that ended without a take has no result to report beyond its lot.
  expect(text.includes("Received")).toBe(sales.take_count > 0);
});


it("leads an upcoming Curve lot with its window and names the burner", async () => {
  vi.setSystemTime(new Date("2026-09-17T06:00:00Z"));
  const { container } = mountRound({
    status: "scheduled", is_active: false, protocol: "curve", version: "curve-1",
    kicked_at: "2026-09-17T12:00:00Z", scheduled_end_at: "2026-09-18T12:00:00Z", end_at: "2026-09-18T12:00:00Z",
    initial_available: "1500", available_amount: "1500", auction_length: 86400, update_interval: 36,
    decay_percent: "0.33%", starting_price_per_unit: "166.666", floor_price_per_unit: "0.0666",
  });
  await settle();
  const text = container.textContent ?? "";
  for (const label of ["Upcoming", "Curve burner", "Lot", "1.50K", "Starts at", "floor 0.0666", "Opens in", "5h 59m", "for 1d 0h", "none yet"]) {
    expect(text).toContain(label);
  }
  // Nothing is open to price or report yet: one row of figures, not a second Lot under the chart.
  for (const absent of ["Remaining", "Price now", "Received", "Kicked"]) expect(text).not.toContain(absent);
  expect(container.querySelectorAll("dl.outcome")).toHaveLength(1);
  expect(container.querySelectorAll("dl.outcome dt")).toHaveLength(3);
});

const finished = {
  status: "sold_out", is_active: false, protocol: "curve", version: "curve-1",
  scheduled_end_at: "2026-09-18T12:00:00Z", end_at: "2026-09-17T18:00:00Z",
  initial_available: "1500", available_amount: "0", sold_amount: "1500", paid_amount: "1499",
  take_count: 1, paid_take_count: 1, paid_usd_take_count: 1, usd_priced_take_count: 1, priced_take_count: 1,
  total_actual_paid_usd: "1499.5", total_market_quote_usd: "1510", total_auction_profit_usd: "-10.5", total_auction_profit_bps: -0.7,
} as const;
const takeTx = `0x${"f".repeat(64)}`;
const curveTake = {
  occurrence: { ...occurrence, tx_hash: takeTx, log_index: 9 }, round_occurrence: occurrence, auction, chain_id: 1, round_id: 1,
  take_seq: 1, taker: `0x${"9".repeat(40)}`, amount_taken: "1500", amount_paid: "1499", amount_paid_usd: "1499.5",
  price: "0.9993", timestamp: "2026-09-17T18:00:00Z", tx_hash: takeTx, block_number: 101, confirmed: true,
  market_quote_out_usd: "1510", price_differential_usd: "-10.5", price_differential_percent: -0.7,
};

it("gives a figure with no dollar value a dash in dollars", async () => {
  window.localStorage.setItem("round_figures_denomination", "usd");
  vi.spyOn(api, "getAuctionTakes").mockResolvedValue({ as_of: {}, takes: [{ ...curveTake, amount_paid_usd: null }], available_price_sources: [] } as unknown as Awaited<ReturnType<typeof api.getAuctionTakes>>);
  const { container } = mountRound({ ...finished, total_actual_paid_usd: null });
  await settle();
  const received = [...container.querySelectorAll("dl.outcome .outcome-cell")].find((cell) => cell.querySelector("dt")?.textContent === "Received");
  expect(received?.querySelector(".outcome-figure")?.textContent).toBe("—");
  window.localStorage.clear();
});

const sold = {
  status: "sold_out", is_active: false, initial_available: "100", available_amount: "0", sold_amount: "100", paid_amount: "50",
  end_at: "2026-09-17T13:00:00Z", take_count: 1, paid_take_count: 1, paid_usd_take_count: 1, usd_priced_take_count: 1, priced_take_count: 1,
  total_market_quote_usd: "200", total_actual_paid_usd: "190", total_auction_profit_usd: "-10", total_auction_profit_bps: -5,
} as const;
const soldTake = {
  occurrence: { ...occurrence, log_index: 9 }, round_occurrence: occurrence, auction, chain_id: 1, round_id: 1, take_seq: 1, taker: auction,
  amount_taken: "100", amount_paid: "50", amount_paid_usd: "190", market_quote_out_usd: "200",
  price_differential_usd: "-10", price_differential_percent: -5, price: "0.5",
  timestamp: "2026-09-17T13:00:00Z", tx_hash: occurrence.tx_hash, block_number: 100, confirmed: true,
} as Awaited<ReturnType<typeof api.getAuctionTakes>>["takes"][number];

it("gives each figure once and switches the whole round between tokens and dollars", async () => {
  vi.mocked(api.getAuctionTakes).mockResolvedValue({ as_of: {}, takes: [soldTake], available_price_sources: [] });
  const { container } = mountRound(sold);
  await settle();
  const figures = () => [...container.querySelectorAll(".outcome-figure, .takes-table tbody td.num")].map((node) => node.textContent ?? "");
  // Sold, Received and PnL, then the take's own sold, received, price and PnL.
  expect(figures()).toHaveLength(7);
  expect(figures().some((figure) => figure.includes("$"))).toBe(false);
  expect(container.querySelectorAll(".outcome-sub")).toHaveLength(0);

  fireEvent.click(container.querySelector(".figure-toggle")!);
  const inDollars = figures();
  // Every figure but the execution price, which is a rate between the two tokens.
  expect(inDollars.filter((figure) => figure.includes("$"))).toHaveLength(6);
  expect(window.localStorage.getItem("round_figures_denomination")).toBe("usd");

  fireEvent.click(container.querySelector(".figure-toggle")!);
  expect(figures().some((figure) => figure.includes("$"))).toBe(false);
});

it("makes a take's label the link to its transaction, without opening the take", async () => {
  vi.mocked(api.getChains).mockResolvedValue({ chains: { 1: { chain_id: 1, name: "Ethereum", short_name: "Ethereum", explorer: "https://etherscan.io" } }, count: 1 });
  vi.mocked(api.getAuctionTakes).mockResolvedValue({ as_of: {}, takes: [soldTake], available_price_sources: [] });
  const { container } = mountRound(sold);
  await settle();
  const link = container.querySelector<HTMLAnchorElement>(".takes-table a.tx-link")!;
  expect(link.textContent).toBe("T1");
  expect(link.getAttribute("href")).toBe(`https://etherscan.io/tx/${occurrence.tx_hash}`);
  expect(link.target).toBe("_blank");
  fireEvent.click(link);
  expect(link.closest("tr")!.getAttribute("aria-expanded")).toBe("false");
});
