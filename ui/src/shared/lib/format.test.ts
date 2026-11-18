import { expect, it } from "vitest";

import { formatFullAmount, formatUsd } from "./format";

it("keeps every digit of an exact 18-decimal amount", () => {
  // Number() would round this to 1.2345678901234568.
  expect(formatFullAmount("1.234567890123456789")).toBe("1.234567890123456789");
  expect(formatFullAmount("123456789.123456789012345678")).toBe(
    "123,456,789.123456789012345678",
  );
});

it("groups and trims exact amounts without inventing precision", () => {
  expect(formatFullAmount("1000")).toBe("1,000");
  expect(formatFullAmount("0.100000000000000000")).toBe("0.1");
  expect(formatFullAmount("0")).toBe("0");
  expect(formatFullAmount("-0.0")).toBe("0");
  expect(formatFullAmount("-1234.5")).toBe("-1,234.5");
  expect(formatFullAmount(null)).toBe("—");
  expect(formatFullAmount("")).toBe("—");
  expect(formatFullAmount("not-a-number")).toBe("not-a-number");
});

it("chooses USD precision by magnitude, not by sign", () => {
  expect(formatUsd(500)).toBe(formatUsd(-500).replace("-", ""));
  expect(formatUsd(-500)).toBe("-$500");
  expect(formatUsd(-5)).toBe("-$5.00");
});
