
import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import TokenLogo, { TOKEN_LOGO_FALLBACK_URL } from "./TokenLogo";

function image(container: HTMLElement): HTMLImageElement {
  const element = container.querySelector("img");
  if (!(element instanceof HTMLImageElement)) {
    throw new Error("token logo image was not rendered");
  }
  return element;
}

describe("TokenLogo", () => {
  it("uses the bundled fallback immediately when the logo URL is missing", () => {
    const { container } = render(<TokenLogo logoUrl={null} symbol="TKN" />);
    const element = image(container);

    expect(element.getAttribute("src")).toBe(TOKEN_LOGO_FALLBACK_URL);
    fireEvent.error(element);
    expect(image(container).getAttribute("src")).toBe(TOKEN_LOGO_FALLBACK_URL);
  });

  it("switches a corrupt logo to the fallback once without an error loop", () => {
    const corruptUrl = "https://prices.wavey.info/token-logos/1/0x0000000000000000000000000000000000000001";
    const { container } = render(<TokenLogo logoUrl={corruptUrl} symbol="TKN" />);
    const primary = image(container);

    expect(primary.getAttribute("src")).toBe(corruptUrl);
    fireEvent.error(primary);

    const fallback = image(container);
    expect(fallback.getAttribute("src")).toBe(TOKEN_LOGO_FALLBACK_URL);
    fireEvent.error(fallback);
    expect(image(container).getAttribute("src")).toBe(TOKEN_LOGO_FALLBACK_URL);
  });
});
