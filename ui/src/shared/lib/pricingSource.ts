import type { PriceSourceOption, RoundListItem, RoundPricingBySource, TakeListItem, TakePricingBySource, TakerTake } from "../types/api";

export const DEFAULT_PRICE_SOURCE = "canonical";

export function roundPnlCoverageTitle(round: Pick<RoundListItem, "priced_take_count" | "usd_priced_take_count" | "take_count">): string | undefined {
  const quoted = round.priced_take_count ?? 0;
  if (quoted >= round.take_count && round.usd_priced_take_count >= round.take_count) return undefined;
  const details = [`Market quotes available for ${quoted} of ${round.take_count} takes.`];
  if (round.usd_priced_take_count !== quoted) details.push(`USD PnL available for ${round.usd_priced_take_count} of ${round.take_count} takes.`);
  details.push("PnL includes only takes with the required pricing data.");
  return details.join(" ");
}

export function resolvePriceSource(
  requestedSource: string | null | undefined,
  options: PriceSourceOption[] | null | undefined,
): string {
  const normalized = (requestedSource || "").trim().toLowerCase();
  if (!options?.length) {
    return DEFAULT_PRICE_SOURCE;
  }
  if (normalized && options.some((option) => option.id === normalized)) {
    return normalized;
  }
  return DEFAULT_PRICE_SOURCE;
}

export function shouldShowPriceSourceSelector(options: PriceSourceOption[] | null | undefined): boolean {
  return (options?.length ?? 0) > 1;
}

export function getTakePricingBySource(
  take: Pick<TakeListItem, "pricing_by_source" | "market_quote_out" | "market_quote_out_usd" | "price_differential_usd" | "price_differential_percent" | "pricing_status">,
  sourceId: string,
): TakePricingBySource {
  if (sourceId !== DEFAULT_PRICE_SOURCE) return take.pricing_by_source?.[sourceId] ?? {};
  return (
    take.pricing_by_source?.[sourceId]
    ?? take.pricing_by_source?.[DEFAULT_PRICE_SOURCE]
    ?? {
      market_quote_out: take.market_quote_out,
      market_quote_out_usd: take.market_quote_out_usd,
      pnl_usd: take.price_differential_usd,
      pnl_percent: take.price_differential_percent,
      pricing_status: take.pricing_status,
    }
  );
}

export function getTakerTakePricingBySource(
  take: Pick<TakerTake, "pricing_by_source" | "pricing_status">,
  sourceId: string,
): TakePricingBySource {
  if (sourceId !== DEFAULT_PRICE_SOURCE) return take.pricing_by_source?.[sourceId] ?? {};
  return (
    take.pricing_by_source?.[sourceId]
    ?? take.pricing_by_source?.[DEFAULT_PRICE_SOURCE]
    ?? { pricing_status: take.pricing_status }
  );
}

export function getRoundPricingBySource(
  round: Pick<RoundListItem, "pricing_by_source" | "total_market_quote_usd" | "total_auction_profit_usd" | "total_auction_profit_bps" | "priced_take_count" | "usd_priced_take_count" | "total_take_count" | "priced_volume_share" | "take_count">,
  sourceId: string,
): RoundPricingBySource {
  if (sourceId !== DEFAULT_PRICE_SOURCE) return round.pricing_by_source?.[sourceId] ?? { priced_take_count: 0, usd_priced_take_count: 0, total_take_count: round.take_count };
  return (
    round.pricing_by_source?.[sourceId]
    ?? round.pricing_by_source?.[DEFAULT_PRICE_SOURCE]
    ?? {
      total_market_quote_usd: round.total_market_quote_usd,
      total_auction_profit_usd: round.total_auction_profit_usd,
      total_auction_profit_bps: round.total_auction_profit_bps,
      priced_take_count: round.priced_take_count ?? 0,
      usd_priced_take_count: round.usd_priced_take_count,
      total_take_count: round.total_take_count ?? round.take_count,
      priced_volume_share: round.priced_volume_share,
    }
  );
}
