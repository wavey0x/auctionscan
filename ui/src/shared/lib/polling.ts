/**
 * Only views that track in-flight auctions poll. Reference data (chains,
 * versions), search results and taker rollups refresh on navigation instead,
 * so a user sitting on a leaderboard does not re-query every few seconds.
 */
export const LIVE_REFETCH_INTERVAL_MS = 3_000;
