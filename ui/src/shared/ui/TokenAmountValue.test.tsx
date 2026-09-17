// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it } from "vitest";
import TokenAmountValue from "./TokenAmountValue";

it("labels an estimate and preserves an observed zero", () => {
  const { container, rerender } = render(<MemoryRouter><TokenAmountValue amount={null} estimatedAmount="150" symbol="USDC" /></MemoryRouter>);
  expect(container.textContent).toContain("Est. 150 USDC");
  rerender(<MemoryRouter><TokenAmountValue amount="0" estimatedAmount="150" symbol="USDC" /></MemoryRouter>);
  expect(container.textContent).toContain("0 USDC");
  expect(container.textContent).not.toContain("Est.");
  rerender(<MemoryRouter><TokenAmountValue amount={null} estimatedAmount={null} symbol="USDC" /></MemoryRouter>);
  expect(container.textContent).toContain("—");
  expect(container.textContent).not.toContain("0 USDC");
});
