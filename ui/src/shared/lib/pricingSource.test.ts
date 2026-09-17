import { expect, it } from "vitest";
import { getTakePricingBySource } from "./pricingSource";

it("does not substitute the default benchmark for an absent selected provider", () => {
  const take = { pricing_by_source: { canonical: { pnl_usd: "10" }, odos: { pnl_usd: "20" } } };
  expect(getTakePricingBySource(take, "odos").pnl_usd).toBe("20");
  expect(getTakePricingBySource(take, "canonical").pnl_usd).toBe("10");
  expect(getTakePricingBySource(take, "curve").pnl_usd).toBeUndefined();
});
