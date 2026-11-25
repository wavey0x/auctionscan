import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../../shared/api/client";
import type { RoundListItem, RoundsResponse } from "../../../shared/types/api";
import RoundsPage from "./RoundsPage";

// The list's filters: status chips for the states worth isolating, and the protocol.

const burner = "0xc014A92C76709D6c7f7c7841823b7164D6D2AbD4";
const upcoming: RoundListItem = {
  occurrence: { chain_id: 1, block_hash: `0x${"b".repeat(64)}`, tx_hash: `0x${"c".repeat(64)}`, log_index: 4 },
  chain_id: 1, auction_address: burner, round_id: 12, status: "scheduled", is_active: false, protocol: "curve", version: "curve-1",
  from_token: `0x${"d".repeat(40)}`, from_token_symbol: "USDC", want_token: `0x${"e".repeat(40)}`, want_token_symbol: "crvUSD",
  kicked_at: "2099-01-06T00:00:00Z", scheduled_end_at: "2099-01-07T00:00:00Z", activity_at: "2099-01-06T00:00:00Z",
  take_count: 0, paid_take_count: 0, paid_usd_take_count: 0, usd_priced_take_count: 0,
  sold_amount: "0", paid_amount: null, initial_available: "1500", available_amount: "1500",
};
const counts = { all: 40, scheduled: 3, live: 5, sold_out: 20, expired: 7, settled: 5 };
let client: QueryClient;
let router: ReturnType<typeof createMemoryRouter>;
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.spyOn(api, "getChains").mockResolvedValue({ chains: {}, count: 0 });
  vi.spyOn(api, "getRounds").mockImplementation(async (params) => ({
    as_of: {}, rounds: [upcoming], total: 1, status_counts: counts, page: params.page ?? 1, per_page: 20, has_next: false,
  }) satisfies RoundsResponse);
});
afterEach(() => { cleanup(); router?.dispose(); client.clear(); vi.restoreAllMocks(); });

async function mount(search = "") {
  router = createMemoryRouter([{ path: "/", element: <RoundsPage /> }], { initialEntries: [`/${search}`] });
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
  await screen.findByText("1 matching rounds");
}

function lastRequest() {
  return vi.mocked(api.getRounds).mock.calls.at(-1)![0];
}

it("offers Upcoming, Live, Sold and Expired with their counts, and Upcoming asks for scheduled rounds", async () => {
  await mount();
  const chips = within(screen.getByRole("group", { name: "Round status" })).getAllByRole("button");
  expect(chips.map((chip) => chip.textContent)).toEqual(["Upcoming3", "Live5", "Sold20", "Expired7"]);
  expect(lastRequest().status).toBe("all");

  fireEvent.click(chips[0]);
  await waitFor(() => expect(lastRequest().status).toBe("scheduled"));
  expect(router.state.location.search).toBe("?status=scheduled");

  fireEvent.click(chips[2]);
  await waitFor(() => expect(lastRequest().status).toBe("sold_out"));
  expect(router.state.location.search).toBe("?status=sold_out");
});

it("falls back to all rounds for a status the list does not offer", async () => {
  await mount("?status=settled");
  expect(lastRequest().status).toBe("all");
  const chips = within(screen.getByRole("group", { name: "Round status" })).getAllByRole("button");
  expect(chips.every((chip) => chip.getAttribute("aria-pressed") === "false")).toBe(true);
});

it("narrows by protocol and names Curve's burner in its rows", async () => {
  await mount();
  expect(lastRequest().protocol).toBe("all");
  fireEvent.click(within(screen.getByRole("group", { name: "Protocol" })).getByRole("button", { name: "Curve" }));
  await waitFor(() => expect(lastRequest().protocol).toBe("curve"));
  expect(router.state.location.search).toBe("?protocol=curve");
  const rows = within(screen.getByRole("region", { name: "Rounds" }));
  expect(rows.getByText("Curve burner")).toBeTruthy();
  // An upcoming round's window opens later.
  expect(rows.getAllByText(/^in \d+/).length).toBeGreaterThan(0);
});

it("has no round column: a Yearn row carries its round on its auction, a burner's lot its token", async () => {
  const yearn: RoundListItem = { ...upcoming, auction_address: `0x${"a".repeat(40)}`, round_id: 66, protocol: "yearn", version: "1.0.4",
    occurrence: { ...upcoming.occurrence, log_index: 5 } };
  vi.mocked(api.getRounds).mockResolvedValue({
    as_of: {}, rounds: [upcoming, yearn], total: 1, status_counts: counts, page: 1, per_page: 20, has_next: false,
  });
  await mount();
  const table = screen.getByRole("region", { name: "Rounds" });
  expect(within(table).getAllByRole("columnheader").map((header) => header.textContent))
    .toEqual(["Auction", "Status", "Progress time", "Lot", "Received", "PnL", "Kicked", "Open"]);

  const [burnerRow, yearnRow] = within(table).getAllByRole("row").slice(1);
  // The burner counts every lot it ever staged in one run, so its number places nothing.
  expect(within(burnerRow).queryByText("R12")).toBeNull();
  expect(within(burnerRow).getByText("Curve burner")).toBeTruthy();
  expect(within(burnerRow).queryByText(/\(0xc014/i)).toBeNull();
  // Many burner tokens share a symbol, so the lot says which token it is.
  expect(within(burnerRow).getByText(/^\(0xdddd…\)$/i)).toBeTruthy();

  expect(within(yearnRow).getByText("R66")).toBeTruthy();
  expect(within(yearnRow).queryByText(/^\(0xdddd…\)$/i)).toBeNull();
});
