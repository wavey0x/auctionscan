import { expect, it } from "vitest";
import { getTakePricingBySource, roundMarketValue } from "./pricingSource";

it("does not substitute the default benchmark for an absent selected provider", () => {
  const take = { pricing_by_source: { canonical: { pnl_usd: "10" }, odos: { pnl_usd: "20" } } };
  expect(getTakePricingBySource(take, "odos").pnl_usd).toBe("20");
  expect(getTakePricingBySource(take, "canonical").pnl_usd).toBe("10");
  expect(getTakePricingBySource(take, "curve").pnl_usd).toBeUndefined();
});

it("values a round by what sold once anything has, and by the lot until then", () => {
  // Sold: the figure PnL is measured against, not what the lot was worth when it opened.
  expect(roundMarketValue({ take_count: 8, kick_market_quote_usd: "326.24" }, "399.04")).toEqual({ usd: "399.04", at: "take" });
  // A sale no source quoted has no value, as it has no PnL.
  expect(roundMarketValue({ take_count: 2, kick_market_quote_usd: "326.24" }, null)).toEqual({ usd: null, at: "take" });
  expect(roundMarketValue({ take_count: 0, kick_market_quote_usd: "326.24" }, undefined)).toEqual({ usd: "326.24", at: "kick" });
});
