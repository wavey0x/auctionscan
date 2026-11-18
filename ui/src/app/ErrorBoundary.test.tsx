import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import ErrorBoundary from "./ErrorBoundary";

function Boom(): JSX.Element {
  throw new Error("render exploded");
}

afterEach(() => vi.restoreAllMocks());

it("shows a recoverable message instead of a blank page", () => {
  vi.spyOn(console, "error").mockImplementation(() => {});

  render(
    <ErrorBoundary>
      <Boom />
    </ErrorBoundary>,
  );

  expect(screen.getByRole("alert")).toBeTruthy();
  expect(screen.getByText("render exploded")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
});

it("renders children when nothing throws", () => {
  render(
    <ErrorBoundary>
      <span>all good</span>
    </ErrorBoundary>,
  );

  expect(screen.getByText("all good")).toBeTruthy();
});
