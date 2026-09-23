import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, api } from "../shared/api/client";
import { buildRoundPath, occurrenceKey } from "../shared/lib/routes";
import type { AuctionDetails, RoundDetailResponse, TakeDetail, TakerDetail, TakerSummary } from "../shared/types/api";
import AuctionPage from "../features/auctions/pages/AuctionPage";
import RoundModalContent from "../features/rounds/components/RoundModalContent";
import RoundsPage from "../features/rounds/pages/RoundsPage";
import SearchPage from "../features/search/pages/SearchPage";
import TakerProfilePage from "../features/takers/pages/TakerProfilePage";
import TakersPage from "../features/takers/pages/TakersPage";

const address = `0x${"a".repeat(40)}`;
const occurrence = { chain_id: 1, block_hash: `0x${"b".repeat(64)}`, tx_hash: `0x${"c".repeat(64)}`, log_index: 4 };
const token = { address, symbol: "SELL", name: "Sell token", decimals: 18, chain_id: 1 };
const roundDetails: RoundDetailResponse = {
  as_of: {},
  round: { occurrence, chain_id: 1, auction_address: address, round_id: 7, status: "settled", is_active: false,
    from_token: address, want_token: address, kicked_at: "2026-09-17T12:00:00Z", activity_at: "2026-09-17T12:00:00Z",
    take_count: 1, paid_take_count: 1, paid_usd_take_count: 0, usd_priced_take_count: 0, sold_amount: "1", paid_amount: "2" },
};
const auction: AuctionDetails = { as_of: {}, address, chain_id: 1, from_tokens: [token], want_token: token, parameters: {},
  activity: { total_participants: 1, total_volume: "2", paid_take_count: 1, total_rounds: 1, total_takes: 1 } };
const take: TakeDetail = { occurrence: { ...occurrence, log_index: 8 }, round_occurrence: occurrence, auction: address,
  chain_id: 1, round_id: 7, take_seq: 1, taker: address, amount_taken: "1", amount_paid: "2", price: "2",
  timestamp: "2026-09-17T12:00:00Z", tx_hash: occurrence.tx_hash, block_number: 100, confirmed: true };
const taker: TakerSummary = { taker: address, active_chains: [1], total_takes: 1, unique_auctions: 1, unique_chains: 1, rank_by_takes: 1,
  total_volume_usd: 25, paid_usd_take_count: 1, last_take: "2026-09-17T12:00:00Z" };
const profile: TakerDetail = { as_of: {}, taker: address, active_chains: [1], auction_breakdown: [], rank_by_takes: 1,
  total_takes: 1, unique_auctions: 1, unique_chains: 1, total_volume_usd: 25, paid_usd_take_count: 1 };
const roundList = { as_of: {}, rounds: [roundDetails.round], total: 1, page: 1, per_page: 10, has_next: false };
const takeList = { as_of: {}, takes: [take], available_price_sources: [] };
const searchResults = { query: "SELL", results: [{ type: "token" as const, chain_id: 1, address_or_hash: address, metadata: { symbol: "SELL", name: "Search match" } }], total: 1 };
const roundPath = buildRoundPath(1, address, 7);
const cases = [
  { name: "rounds", path: "/", method: "getRounds", key: "rounds", loaded: "1 matching rounds", missing: "No rounds found", data: roundList, empty: { ...roundList, rounds: [], total: 0 } },
  { name: "takers", path: "/takers", method: "getTakers", key: "takers", loaded: "1 results found", missing: "No takers found", data: { takers: [taker], total: 1, page: 1, per_page: 15, has_next: false, as_of: {} }, empty: { takers: [], total: 0, page: 1, per_page: 15, has_next: false, as_of: {} } },
  { name: "auction", path: `/auction/1/${address}`, method: "getAuction", key: "auction", loaded: "Auction:", missing: "Auction not found", data: auction, empty: null },
  { name: "taker profile", path: `/taker/${address}`, method: "getTaker", key: "taker", loaded: "Taker profile", missing: "Taker not found", data: profile, empty: null },
  { name: "round", path: roundPath, method: "getRoundDetail", key: "round-detail", loaded: "R7", missing: "Round not found", data: roundDetails, empty: undefined },
  { name: "search", path: "/search?q=SELL", method: "search", key: "search", loaded: "Search match", missing: "No matches", data: searchResults, empty: { query: "SELL", results: [], total: 0 } },
] satisfies Array<{ name: string; path: string; method: keyof typeof api; key: string; loaded: string; missing: string; data: unknown; empty: unknown }>;

let client: QueryClient;
let router: ReturnType<typeof createMemoryRouter>;
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  vi.spyOn(api, "getChains").mockResolvedValue({ chains: {}, count: 0 });
  vi.spyOn(api, "getAuctionVersions").mockResolvedValue({ as_of: {}, versions: [], count: 0 });
  vi.spyOn(api, "getAuction").mockResolvedValue(auction);
  vi.spyOn(api, "getRounds").mockResolvedValue(roundList);
  vi.spyOn(api, "getRoundDetail").mockResolvedValue(roundDetails);
  vi.spyOn(api, "getAuctionTakes").mockResolvedValue(takeList);
  vi.spyOn(api, "getTake").mockResolvedValue(take);
  vi.spyOn(api, "getTaker").mockResolvedValue(profile);
  vi.spyOn(api, "getTakerTakes").mockResolvedValue({ as_of: {}, takes: [], available_price_sources: [], total_count: 0, total_pages: 0, page: 1, limit: 20 });
  vi.spyOn(api, "getTakers").mockResolvedValue({ takers: [taker], total: 1, page: 1, per_page: 15, has_next: false, as_of: {} });
  vi.spyOn(api, "search").mockResolvedValue(searchResults);
});
afterEach(() => { cleanup(); router?.dispose(); client.clear(); vi.restoreAllMocks(); });

function mount(path: string) {
  router = createMemoryRouter([
    { path: "/", element: <RoundsPage /> },
    { path: "/auction/:chainId/:address", element: <AuctionPage /> },
    { path: "/round/:chainId/:auctionAddress/:roundId", element: <RoundModalContent onClose={() => {}} /> },
    { path: "/taker/:address", element: <TakerProfilePage /> },
    { path: "/takers", element: <TakersPage /> },
    { path: "/search", element: <SearchPage /> },
  ], { initialEntries: [path] });
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
}
async function refresh(key: string) {
  await act(async () => { await client.refetchQueries({ queryKey: [key] }); });
}
function retry(message: string) {
  const notice = screen.getByText(message).closest('[role="alert"]')! as HTMLElement;
  fireEvent.click(within(notice).getByRole("button", { name: "Retry" }));
}

it.each(cases)("$name distinguishes initial failure, retry, and confirmed emptiness", async (item) => {
  const request = vi.spyOn(api, item.method);
  request.mockRejectedValue(new TypeError("Failed to fetch"));
  mount(item.path);
  const error = item.method === "search" ? "Unable to search." : `Unable to load ${item.name}.`;
  await screen.findByText(error);
  expect(screen.queryByText(item.missing)).toBeNull();
  if (item.empty === undefined) request.mockRejectedValue(new ApiError(404, "Not found"));
  else request.mockResolvedValue(item.empty);
  retry(error);
  await screen.findByText(item.missing);
  expect(screen.queryByRole("alert")).toBeNull();
});

it.each(cases)("$name retains loaded data during a failed refresh and recovers on retry", async (item) => {
  mount(item.path);
  await screen.findByText(item.loaded);
  const request = vi.spyOn(api, item.method);
  request.mockRejectedValue(new ApiError(503, "Unavailable"));
  await refresh(item.key);
  const warning = `Could not refresh ${item.name}. Showing previously loaded data.`;
  await screen.findByText(warning);
  expect(screen.getByText(item.loaded)).toBeTruthy();
  expect(screen.queryByText(item.missing)).toBeNull();
  request.mockResolvedValue(item.data);
  retry(warning);
  await waitFor(() => expect(screen.queryByText(warning)).toBeNull());
});

it.each(cases.filter((item) => ["auction", "taker", "round-detail"].includes(item.key)))("$name stops showing a cached record once absence is confirmed", async (item) => {
  mount(item.path);
  await screen.findByText(item.loaded);
  const request = vi.spyOn(api, item.method);
  if (item.key === "round-detail") request.mockRejectedValue(new ApiError(404, "Not found"));
  else request.mockResolvedValue(null);
  await refresh(item.key);
  await screen.findByText(item.missing);
  expect(screen.queryByText(item.loaded)).toBeNull();
});

it.each([roundPath, `/auction/1/${address}`])("keeps %s visible while takes load or fail", async (path) => {
  let reject!: (error: Error) => void;
  vi.mocked(api.getAuctionTakes).mockImplementation(() => new Promise((_resolve, fail) => { reject = fail; }));
  mount(path);
  await screen.findByText(path === roundPath ? "R7" : "Auction:");
  expect(screen.queryByText(/No (recent takes|takes in this round)/)).toBeNull();
  await act(async () => reject(new Error("offline")));
  await screen.findByText("Unable to load takes.");
  expect(screen.queryByText(/No (recent takes|takes in this round)/)).toBeNull();
  vi.mocked(api.getAuctionTakes).mockResolvedValue({ ...takeList, takes: [] });
  retry("Unable to load takes.");
  await screen.findByText(path === roundPath ? "No takes in this round" : "No recent takes");
});

it.each([roundPath, `/auction/1/${address}`])("retains takes in %s after their refresh fails", async (path) => {
  mount(path);
  await screen.findByRole("cell", { name: "T1" });
  vi.mocked(api.getAuctionTakes).mockRejectedValue(new Error("offline"));
  await refresh(path === roundPath ? "round-takes" : "auction-recent-takes");
  await screen.findByText("Could not refresh takes. Showing previously loaded data.");
  expect(screen.getByRole("cell", { name: "T1" })).toBeTruthy();
});

it.each([roundPath, `/auction/1/${address}`])("distinguishes failed and missing selected takes in %s", async (path) => {
  vi.mocked(api.getTake).mockRejectedValue(new Error("offline"));
  mount(`${path}?take=${occurrenceKey(take.occurrence)}`);
  await screen.findByText("Unable to load take.");
  expect(screen.queryByText("Take not found")).toBeNull();
  vi.mocked(api.getTake).mockResolvedValue(take);
  retry("Unable to load take.");
  await screen.findAllByText("Execution price");
  vi.mocked(api.getTake).mockRejectedValue(new ApiError(503, "Unavailable"));
  await refresh("take-detail");
  await screen.findByText("Could not refresh take. Showing previously loaded data.");
  expect(screen.getAllByText("Execution price").length).toBeGreaterThan(0);
  vi.mocked(api.getTake).mockRejectedValue(new ApiError(404, "Not found"));
  await refresh("take-detail");
  await screen.findByText("Take not found");
  expect(screen.queryByText("Execution price")).toBeNull();
});

it("keeps direct round lookup failures separate from normal search", async () => {
  vi.mocked(api.getRounds).mockRejectedValue(new Error("offline"));
  mount(`/search?q=1:${address}:7`);
  await screen.findByText("Unable to look up this round.");
  expect(screen.getByText("Search match")).toBeTruthy();
  vi.mocked(api.getRounds).mockResolvedValue(roundList);
  retry("Unable to look up this round.");
  await screen.findByText("Direct round workspace");
});

it("keeps a loaded round visible when its supporting auction request fails", async () => {
  vi.mocked(api.getAuction).mockRejectedValue(new Error("offline"));
  mount(roundPath);
  await screen.findByText("R7");
  await screen.findByText("Unable to load auction details.");
  expect(screen.queryByText("Round not found")).toBeNull();
});

it("keeps taker totals visible through takes failures and retries", async () => {
  vi.mocked(api.getTakerTakes).mockRejectedValue(new Error("offline"));
  mount(`/taker/${address}`);
  await screen.findByText("Unable to load takes.");
  expect(screen.getByText("Taker profile")).toBeTruthy();
  expect(screen.queryByText("No takes")).toBeNull();
  vi.mocked(api.getTakerTakes).mockResolvedValue({ as_of: {}, takes: [{ ...take, auction_address: address }],
    available_price_sources: [], total_count: 1, total_pages: 1, page: 1, limit: 20 });
  retry("Unable to load takes.");
  await screen.findByRole("cell", { name: "R7" });
  vi.mocked(api.getTakerTakes).mockRejectedValue(new Error("offline"));
  await refresh("taker-takes");
  await screen.findByText("Could not refresh takes. Showing previously loaded data.");
  expect(screen.getByRole("cell", { name: "R7" })).toBeTruthy();
});
