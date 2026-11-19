import { useSyncExternalStore } from "react";
import { notifyManager, useQueryClient, type Query } from "@tanstack/react-query";

import { ApiError } from "../api/client";

/**
 * A refresh has failed when a request that already has data on screen could
 * not be answered. An answer the server did give (not found, a snapshot that
 * moved on) is not a failure to refresh.
 */
function isShowingUnrefreshedData(query: Query): boolean {
  const { status, data, error } = query.state;
  if (status !== "error" || data === undefined || query.getObserversCount() === 0) return false;
  return !(error instanceof ApiError) || error.status >= 500;
}

/**
 * True while anything on screen is showing data whose last refresh failed.
 * The data-age control reports this once for the whole page, so sections keep
 * their previously loaded data without each announcing it.
 */
export function useRefreshFailing(): boolean {
  const cache = useQueryClient().getQueryCache();
  return useSyncExternalStore(
    (onChange) => cache.subscribe(notifyManager.batchCalls(onChange)),
    () => cache.getAll().some(isShowingUnrefreshedData),
    () => false,
  );
}
