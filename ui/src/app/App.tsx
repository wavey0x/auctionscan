import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes, matchPath, useLocation } from "react-router-dom";
import type { Location } from "react-router-dom";

import AppShell from "./AppShell";
import AuctionPage from "../features/auctions/pages/AuctionPage";
import DocsPage from "../features/docs/pages/DocsPage";
import RoundModalRoute from "../features/rounds/pages/RoundModalRoute";
import RoundsPage from "../features/rounds/pages/RoundsPage";
import SearchPage from "../features/search/pages/SearchPage";
import StatusPage from "../features/status/pages/StatusPage";
import TakerProfilePage from "../features/takers/pages/TakerProfilePage";
import TakersPage from "../features/takers/pages/TakersPage";
import TxResolveRoute from "../features/tx/pages/TxResolveRoute";
import { parseRoundModalSource, resolveRoundModalBackgroundLocation } from "../shared/lib/routes";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 2_000,
      refetchInterval: 3_000,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  );
}

function AppRoutes() {
  const location = useLocation();
  const roundMatch = matchPath("/round/:chainId/:auctionAddress/:occurrence", location.pathname);
  const routeState = (location.state as { backgroundLocation?: Location } | null) ?? null;
  const routeSearchParams = new URLSearchParams(location.search);
  const roundModalSource = parseRoundModalSource(routeSearchParams.get("from"));
  const roundModalTxHash = routeSearchParams.get("tx");
  const synthesizedBackgroundLocation =
    roundMatch && !routeState?.backgroundLocation
      ? (() => {
          const background = resolveRoundModalBackgroundLocation(
            roundModalSource,
            roundMatch.params.chainId ?? "",
            roundMatch.params.auctionAddress ?? "",
            roundModalTxHash,
          );
          return {
            pathname: background.pathname,
            search: background.search,
            hash: "",
            state: null,
            key: `round-background-${roundModalSource ?? "fallback"}-${roundMatch.params.chainId}-${roundMatch.params.auctionAddress}-${roundModalTxHash ?? "none"}`,
          };
        })()
      : null;
  const backgroundLocation = routeState?.backgroundLocation ?? synthesizedBackgroundLocation ?? undefined;

  return (
    <>
      <Routes location={backgroundLocation || location}>
        <Route element={<AppShell />}>
          <Route path="/" element={<RoundsPage />} />
          <Route path="/pricing" element={<DocsPage />} />
          <Route path="/status" element={<StatusPage />} />
          <Route path="/auction/:chainId/:address" element={<AuctionPage />} />
          <Route path="/takers" element={<TakersPage />} />
          <Route path="/taker/:address" element={<TakerProfilePage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/tx/:txHash" element={<TxResolveRoute />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>

      {roundMatch ? (
        <Routes>
          <Route path="/round/:chainId/:auctionAddress/:occurrence" element={<RoundModalRoute />} />
        </Routes>
      ) : null}
    </>
  );
}
