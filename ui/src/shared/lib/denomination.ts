import { useState } from "react";

/** What a round's figures are counted in: its own tokens, or dollars. */
export type Denomination = "token" | "usd";

const DENOMINATION_KEY = "round_figures_denomination";

function readDenomination(): Denomination {
  try {
    return window.localStorage.getItem(DENOMINATION_KEY) === "usd" ? "usd" : "token";
  } catch {
    return "token";
  }
}

/**
 * A round shows each figure once, in tokens or in dollars. Clicking a figure
 * switches every figure in the round; the choice is remembered per browser.
 */
export function useDenomination(): [Denomination, () => void] {
  const [denomination, setDenomination] = useState<Denomination>(readDenomination);
  const toggle = () => {
    setDenomination((current) => {
      const next = current === "usd" ? "token" : "usd";
      try {
        window.localStorage.setItem(DENOMINATION_KEY, next);
      } catch {
        // Storage may be unavailable; the choice then lasts for this page.
      }
      return next;
    });
  };
  return [denomination, toggle];
}
