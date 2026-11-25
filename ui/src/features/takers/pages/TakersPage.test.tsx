import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../../shared/api/client";
import type { TakerListResponse, TakerSummary } from "../../../shared/types/api";
import TakersPage from "./TakersPage";

// The ranking narrowed to one protocol: the figures are that protocol's, so the request carries it.

const address = `0x${"a".repeat(40)}`;
// Across both protocols this taker has one take without a USD value; within Curve, every take has one.
const everywhere: TakerSummary = { taker: address, active_chains: [1], total_takes: 9, unique_auctions: 3, unique_chains: 1, rank_by_takes: 1,
  total_volume_usd: 5000, paid_usd_take_count: 8, last_take: "2026-09-17T12:00:00Z" };
const onCurve: TakerSummary = { ...everywhere, total_takes: 2, unique_auctions: 1, total_volume_usd: 1500, paid_usd_take_count: 2 };
let client: QueryClient;
let router: ReturnType<typeof createMemoryRouter>;
beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.spyOn(api, "getChains").mockResolvedValue({ chains: {}, count: 0 });
  vi.spyOn(api, "getTakers").mockImplementation(async (params) => ({
    as_of: {}, takers: [params.protocol === "curve" ? onCurve : everywhere], total: 1, page: 1, per_page: 20, has_next: false,
  }) satisfies TakerListResponse);
});
afterEach(() => { cleanup(); router?.dispose(); client.clear(); vi.restoreAllMocks(); });

async function mount(search = "") {
  router = createMemoryRouter([{ path: "/takers", element: <TakersPage /> }], { initialEntries: [`/takers${search}`] });
  render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>);
  await screen.findByText("1 results found");
}

function lastRequest() {
  return vi.mocked(api.getTakers).mock.calls.at(-1)![0];
}

it("narrows the ranking and its figures to one protocol", async () => {
  await mount("?page=3");
  const table = within(screen.getByRole("region", { name: "Takers" }));
  expect(lastRequest().protocol).toBe("all");
  expect(table.getByText("$5.00K")).toBeTruthy();

  fireEvent.click(within(screen.getByRole("group", { name: "Protocol" })).getByRole("button", { name: "Curve" }));
  await waitFor(() => expect(lastRequest().protocol).toBe("curve"));
  // A narrower ranking starts from its first page.
  expect(router.state.location.search).toBe("?protocol=curve");
  await table.findByText("$1.50K");
  expect(table.getByText("2")).toBeTruthy();

  fireEvent.click(within(screen.getByRole("group", { name: "Protocol" })).getByRole("button", { name: "Curve" }));
  await waitFor(() => expect(lastRequest().protocol).toBe("all"));
  expect(router.state.location.search).toBe("");
});

it("states volume as a bare figure, with its coverage on hover", async () => {
  await mount();
  const figure = within(screen.getByRole("region", { name: "Takers" })).getByText("$5.00K");
  expect(screen.queryByText("partial")).toBeNull();
  expect(figure.closest("td")?.getAttribute("title")).toContain("USD value known for 8 of 9 takes");
});
