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

it("offers Live, Sold and Expired, each with its mark and count, and no key for upcoming rounds", async () => {
  await mount();
  const chips = within(screen.getByRole("group", { name: "Round status" })).getAllByRole("button");
  expect(chips.map((chip) => chip.textContent)).toEqual(["Live5", "Sold20", "Expired7"]);
  expect(chips.every((chip) => chip.querySelector(".status-mark"))).toBe(true);
  expect(lastRequest().status).toBe("all");

  fireEvent.click(chips[0]);
  await waitFor(() => expect(lastRequest().status).toBe("live"));
  expect(router.state.location.search).toBe("?status=live");

  fireEvent.click(chips[1]);
  await waitFor(() => expect(lastRequest().status).toBe("sold_out"));
  // The address bar spells the status as its key does; the API keeps its stored name.
  expect(router.state.location.search).toBe("?status=sold");
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

it("narrows to the days rounds were kicked on, and lets either end go", async () => {
  await mount("?from=2026-11-01&to=not-a-day");
  const range = within(screen.getByRole("group", { name: "Kicked" }));
  expect(lastRequest()).toMatchObject({ kicked_from: "2026-11-01", kicked_to: undefined });

  fireEvent.change(range.getByLabelText("Kicked to"), { target: { value: "2026-11-24" } });
  await waitFor(() => expect(lastRequest().kicked_to).toBe("2026-11-24"));
  expect(router.state.location.search).toBe("?from=2026-11-01&to=2026-11-24");

  fireEvent.click(range.getByRole("button", { name: "Clear kicked dates" }));
  await waitFor(() => expect(lastRequest().kicked_from).toBeUndefined());
  expect(router.state.location.search).toBe("");
  expect(range.queryByRole("button")).toBeNull();
});

it("orders by PnL from the worst and by lot value from the largest, and a second click returns to newest first", async () => {
  await mount("?status=sold&page=3");
  expect(lastRequest()).toMatchObject({ sort_by: "kicked", page: 3 });
  const head = within(screen.getByRole("region", { name: "Rounds" }));
  const pnl = head.getByRole("columnheader", { name: /PnL/ });
  const lot = head.getByRole("columnheader", { name: /Lot/ });
  expect(document.querySelectorAll("thead .sort-arrow")).toHaveLength(0);

  fireEvent.click(within(pnl).getByRole("button", { name: "PnL" }));
  await waitFor(() => expect(lastRequest()).toMatchObject({ sort_by: "pnl_percent", status: "sold_out", page: 1 }));
  expect(router.state.location.search).toBe("?status=sold&sort=pnl");
  expect(pnl.getAttribute("aria-sort")).toBe("ascending");
  expect(pnl.querySelectorAll(".sort-arrow")).toHaveLength(1);

  fireEvent.click(within(lot).getByRole("button"));
  await waitFor(() => expect(lastRequest().sort_by).toBe("value"));
  expect(router.state.location.search).toBe("?status=sold&sort=value");
  expect(lot.getAttribute("aria-sort")).toBe("descending");
  expect(pnl.getAttribute("aria-sort")).toBeNull();
  expect(document.querySelectorAll("thead .sort-arrow")).toHaveLength(1);

  fireEvent.click(within(lot).getByRole("button"));
  await waitFor(() => expect(lastRequest().sort_by).toBe("kicked"));
  expect(router.state.location.search).toBe("?status=sold");
  expect(document.querySelectorAll("thead .sort-arrow")).toHaveLength(0);
});

it("orders PnL by the unit its column shows, and the unit still switches on its own", async () => {
  await mount("?sort=pnl&page=2");
  expect(lastRequest()).toMatchObject({ sort_by: "pnl_percent", page: 2 });
  const pnl = within(screen.getByRole("region", { name: "Rounds" })).getByRole("columnheader", { name: /PnL/ });

  // Another unit is another order, so it is read from its first page.
  fireEvent.click(within(pnl).getByRole("button", { name: "%" }));
  await waitFor(() => expect(lastRequest()).toMatchObject({ sort_by: "pnl_usd", page: 1 }));
  expect(router.state.location.search).toBe("?sort=pnl");
  expect(pnl.textContent).toBe("PnL $");
});

it("leaves the order and the page alone when the PnL unit changes under another order", async () => {
  await mount("?page=2");
  const pnl = within(screen.getByRole("region", { name: "Rounds" })).getByRole("columnheader", { name: /PnL/ });
  const requests = vi.mocked(api.getRounds).mock.calls.length;
  fireEvent.click(within(pnl).getByRole("button", { name: "%" }));
  expect(pnl.textContent).toBe("PnL $");
  expect(router.state.location.search).toBe("?page=2");
  expect(vi.mocked(api.getRounds).mock.calls).toHaveLength(requests);
});

it("ignores an order the list does not offer", async () => {
  await mount("?sort=received");
  expect(lastRequest().sort_by).toBe("kicked");
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
    .toEqual(["Auction", "Status", "Progress time", "Lot value", "Received", "PnL %", "Kicked", "Open"]);

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

it("values a sold lot by what the market quoted when it sold, the figure its PnL is measured against", async () => {
  const sold: RoundListItem = {
    ...upcoming, round_id: 380, status: "sold_out", take_count: 8, paid_take_count: 8, paid_usd_take_count: 8, usd_priced_take_count: 8,
    sold_amount: "190", initial_available: "190", available_amount: "0", paid_amount: "407",
    kick_market_quote_usd: "326.24", total_market_quote_usd: "399.04", total_auction_profit_usd: "7.17",
  };
  const unsold: RoundListItem = { ...upcoming, round_id: 381, kick_market_quote_usd: "1500" };
  vi.mocked(api.getRounds).mockResolvedValue({
    as_of: {}, rounds: [sold, unsold], total: 2, status_counts: counts, page: 1, per_page: 20, has_next: false,
  });
  router = createMemoryRouter([{ path: "/", element: <RoundsPage /> }], { initialEntries: ["/"] });
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
  await screen.findByText("2 matching rounds");

  const values = Array.from(document.querySelectorAll("tbody .lot-usd")).map((cell) => cell.textContent);
  expect(values).toEqual(["$399", "$1.50K"]);
});
