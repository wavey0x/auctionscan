import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../../shared/api/client";
import { buildAuctionPath, buildRoundPathWithSource, occurrenceKey } from "../../../shared/lib/routes";
import type { AuctionDetails, RoundListItem, TakeDetail } from "../../../shared/types/api";
import AuctionPage from "./AuctionPage";

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
  vi.spyOn(api, "getRounds").mockResolvedValue({ as_of: {}, rounds: [round], total: 21, page: 1, per_page: 10, has_next: true });
  vi.spyOn(api, "getAuctionTakes").mockResolvedValue({ as_of: {}, takes: [take], available_price_sources: [] });
  vi.spyOn(api, "getTake").mockResolvedValue(take);
  vi.spyOn(api, "getChains").mockResolvedValue({ chains: {}, count: 0 });
});
afterEach(() => { cleanup(); router?.dispose(); client.clear(); vi.restoreAllMocks(); });

async function mount(search = "?priceSource=canonical&keep=yes") {
  router = createMemoryRouter([
    { path: "/auction/:chainId/:address", element: <AuctionPage /> },
    { path: "/round/:chainId/:auctionAddress/:occurrence", element: <div>Round destination</div> },
  ], { initialEntries: [buildAuctionPath(1, auction) + search] });
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
  await screen.findByRole("cell", { name: "T1" });
}

function roundRow() {
  return screen.getByRole("cell", { name: "R7 Settled" }).closest("tr")!;
}

it("changes pages while preserving selection and unrelated query parameters", async () => {
  const key = occurrenceKey(take.occurrence);
  await mount(`?take=${key}&priceSource=canonical&keep=yes`);
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await waitFor(() => expect(api.getRounds).toHaveBeenCalledWith(
    { chain_id: 1, auction_address: auction, page: 2, limit: 10 }, expect.any(AbortSignal),
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
  expect(router.state.location.pathname + router.state.location.search).toBe(buildRoundPathWithSource(1, auction, occurrence, "auction"));
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
  expect(open).toHaveBeenCalledWith(buildRoundPathWithSource(1, auction, occurrence, "auction"), "_blank", "noopener,noreferrer");
  expect(router.state.location).toEqual(initialLocation);
});

it("keeps display toggles within rows from opening the round", async () => {
  await mount();
  const initialLocation = router.state.location;
  const kickedToggle = within(roundRow()).getByRole("button", { name: /ago/ });
  const previousLabel = kickedToggle.textContent;
  fireEvent.click(kickedToggle);
  expect(kickedToggle.textContent).not.toBe(previousLabel);
  expect(router.state.location).toEqual(initialLocation);
});
