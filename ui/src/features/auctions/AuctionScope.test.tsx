import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../shared/api/client";
import { buildAuctionPath, buildRoundPathWithSource, occurrenceKey } from "../../shared/lib/routes";
import type { AuctionDetails, RoundListItem, TakeDetail } from "../../shared/types/api";
import RoundsPage from "../rounds/pages/RoundsPage";

// An auction is the rounds list narrowed to it: the same page at /auction/:chainId/:address.

const auction = `0x${"a".repeat(40)}`;
const occurrence = { chain_id: 1, block_hash: `0x${"b".repeat(64)}`, tx_hash: `0x${"c".repeat(64)}`, log_index: 4 };
const sellToken = { address: `0x${"d".repeat(40)}`, symbol: "SELL", name: "Sell token", decimals: 18, chain_id: 1 };
const wantToken = { ...sellToken, address: `0x${"e".repeat(40)}`, symbol: "WANT", name: "Want token" };
const round: RoundListItem = {
  occurrence, chain_id: 1, auction_address: auction, round_id: 7, status: "settled", is_active: false,
  from_token: sellToken.address, from_token_symbol: sellToken.symbol,
  want_token: wantToken.address, want_token_symbol: wantToken.symbol,
  kicked_at: "2026-09-17T12:00:00Z", activity_at: "2026-09-17T13:00:00Z", end_at: "2026-09-17T13:00:00Z",
  take_count: 1, paid_take_count: 1, paid_usd_take_count: 0, usd_priced_take_count: 0,
  sold_amount: "1", paid_amount: "2",
};
const take: TakeDetail = {
  occurrence: { ...occurrence, log_index: 8 }, round_occurrence: occurrence,
  auction, chain_id: 1, round_id: 7, take_seq: 1, taker: auction,
  amount_taken: "1", amount_paid: "2", price: "2", timestamp: "2026-09-17T13:00:00Z",
  tx_hash: occurrence.tx_hash, block_number: 100, confirmed: true,
  from_token: sellToken.address, from_token_symbol: sellToken.symbol,
  to_token: wantToken.address, to_token_symbol: wantToken.symbol,
};
const details: AuctionDetails = {
  as_of: {}, address: auction, chain_id: 1, from_tokens: [sellToken], want_token: wantToken,
  parameters: {}, activity: { total_participants: 1, total_volume: "2", paid_take_count: 1, total_rounds: 21, total_takes: 1 },
};
let client: QueryClient;
let router: ReturnType<typeof createMemoryRouter>;
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.spyOn(api, "getAuction").mockResolvedValue(details);
  // The pager follows the page the response says it holds, so the stub answers with the page asked for.
  vi.spyOn(api, "getRounds").mockImplementation(async (params) => ({ as_of: {}, rounds: [round], total: 21, status_counts: { all: 21, live: 0, sold_out: 0, expired: 0, settled: 21 }, page: params.page ?? 1, per_page: 20, has_next: true }));
  vi.spyOn(api, "getAuctionTakes").mockResolvedValue({ as_of: {}, takes: [take], available_price_sources: [] });
  vi.spyOn(api, "getTake").mockResolvedValue(take);
  vi.spyOn(api, "getChains").mockResolvedValue({ chains: {}, count: 0 });
});
afterEach(() => { cleanup(); router?.dispose(); client.clear(); vi.restoreAllMocks(); });

async function mount(search = "?priceSource=canonical&keep=yes") {
  router = createMemoryRouter([
    { path: "/", element: <RoundsPage /> },
    { path: "/auction/:chainId/:address", element: <RoundsPage /> },
    { path: "/round/:chainId/:auctionAddress/:roundId", element: <div>Round destination</div> },
  ], { initialEntries: [buildAuctionPath(1, auction) + search] });
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
  await screen.findByRole("cell", { name: "T1" });
}

function roundRow() {
  // The recent takes beneath name their round too; the row meant is the one in the rounds table.
  return within(screen.getByRole("region", { name: "Rounds" })).getByRole("cell", { name: /^R7\b/ }).closest("tr")!;
}

it("lists the auction's rounds under its own head, without an auction column", async () => {
  await mount("");
  expect(api.getRounds).toHaveBeenCalledWith(
    expect.objectContaining({ status: "all", chain_id: 1, auction_address: auction, page: 1, limit: 20 }), expect.any(AbortSignal),
  );
  expect(screen.getByRole("heading", { level: 1 }).textContent?.toLowerCase()).toContain("0xaaaa");
  expect(screen.getAllByRole("columnheader").map((header) => header.textContent)[0]).toBe("Round");
  expect(screen.queryByRole("columnheader", { name: "Auction" })).toBeNull();
  // The auction fixes the chain, so it is not offered as a filter.
  expect(screen.queryByRole("group", { name: "Chain" })).toBeNull();
  expect(screen.getByRole("group", { name: "Round status" })).toBeTruthy();
});

it("narrows an auction's rounds by status without leaving it", async () => {
  await mount("?keep=yes");
  fireEvent.click(within(screen.getByRole("group", { name: "Round status" })).getByRole("button", { name: /^Expired/ }));
  await waitFor(() => expect(api.getRounds).toHaveBeenCalledWith(
    expect.objectContaining({ status: "expired", chain_id: 1, auction_address: auction }), expect.any(AbortSignal),
  ));
  expect(router.state.location.pathname).toBe(buildAuctionPath(1, auction));
  expect(new URLSearchParams(router.state.location.search)).toEqual(new URLSearchParams("keep=yes&status=expired"));
});

it("closes the auction back to the whole list", async () => {
  await mount("");
  fireEvent.click(screen.getByRole("button", { name: "Show all rounds" }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  await waitFor(() => expect(screen.getAllByRole("columnheader").map((header) => header.textContent)[0]).toBe("Auction"));
  expect(screen.queryByRole("region", { name: "Recent takes" })).toBeNull();
});

it("changes pages while preserving selection and unrelated query parameters", async () => {
  const key = occurrenceKey(take.occurrence);
  await mount(`?take=${key}&priceSource=canonical&keep=yes`);
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await waitFor(() => expect(api.getRounds).toHaveBeenCalledWith(
    expect.objectContaining({ chain_id: 1, auction_address: auction, page: 2, limit: 20 }), expect.any(AbortSignal),
  ));
  expect(new URLSearchParams(router.state.location.search)).toEqual(new URLSearchParams(`take=${key}&priceSource=canonical&keep=yes&page=2`));
  fireEvent.click(await screen.findByRole("button", { name: "Previous page" }));
  expect(new URLSearchParams(router.state.location.search).has("page")).toBe(false);
  expect(new URLSearchParams(router.state.location.search).get("take")).toBe(key);
});

it("toggles take expansion and clears it with Escape without losing other parameters", async () => {
  await mount();
  const row = screen.getByRole("cell", { name: "T1" }).closest("tr")!;
  fireEvent.click(row);
  await waitFor(() => expect(screen.getAllByText("Execution price").length).toBeGreaterThan(0));
  expect(new URLSearchParams(router.state.location.search).get("take")).toBe(occurrenceKey(take.occurrence));
  expect(router.state.historyAction).toBe("REPLACE");
  fireEvent.click(row);
  expect(new URLSearchParams(router.state.location.search).has("take")).toBe(false);
  expect(screen.queryByText("Execution price")).toBeNull();
  fireEvent.click(row);
  fireEvent.keyDown(window, { key: "Escape" });
  expect(router.state.location.search).toBe("?priceSource=canonical&keep=yes");
});

it("opens a desktop round with the auction location as its modal background", async () => {
  await mount("?page=2&keep=yes");
  const background = router.state.location;
  fireEvent.click(roundRow());
  expect(router.state.location.pathname + router.state.location.search).toBe(buildRoundPathWithSource(1, auction, 7, "auction"));
  expect(router.state.location.state).toEqual({ backgroundLocation: background });
});

it("opens modified and middle row clicks in a new tab without navigating the page", async () => {
  const open = vi.spyOn(window, "open").mockReturnValue(null);
  await mount();
  const initialLocation = router.state.location;
  const row = roundRow();
  fireEvent.click(row, { ctrlKey: true });
  fireEvent.click(row, { metaKey: true });
  fireEvent(row, new MouseEvent("auxclick", { button: 1, bubbles: true }));
  expect(open).toHaveBeenCalledTimes(3);
  expect(open).toHaveBeenCalledWith(buildRoundPathWithSource(1, auction, 7, "auction"), "_blank", "noopener,noreferrer");
  expect(router.state.location).toEqual(initialLocation);
});

it("toggles the kicked column from its header without opening a round", async () => {
  await mount();
  const initialLocation = router.state.location;
  // The narrow-layout sub-line always reads relative time; the column follows the header toggle.
  expect(within(roundRow()).getAllByText(/ago$/)).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: "Kicked" }));
  expect(within(roundRow()).getAllByText(/ago$/)).toHaveLength(1);
  expect(router.state.location).toEqual(initialLocation);
});

it("opens the round from the keyboard", async () => {
  await mount();
  const row = roundRow();
  fireEvent.keyDown(row, { key: "Enter" });
  expect(router.state.location.pathname + router.state.location.search).toBe(buildRoundPathWithSource(1, auction, 7, "auction"));
});
