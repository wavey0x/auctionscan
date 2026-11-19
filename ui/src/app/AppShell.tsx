import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";

import { api } from "../shared/api/client";
import { cn } from "../shared/lib/format";
import { LIVE_REFETCH_INTERVAL_MS } from "../shared/lib/polling";
import { currentColorMode, setColorMode, type ColorMode } from "../shared/lib/theme";
import DataAge from "./DataAge";
import GlobalSearch from "./GlobalSearch";

const primaryLinks = [
  { to: "/", label: "Rounds", exact: true },
  { to: "/takers", label: "Takers" },
];

function resolveApiDocsHref(): string {
  const explicit = (import.meta.env.VITE_API_DOCS_URL || "").trim();
  if (explicit) {
    return explicit;
  }

  const proxyTarget = (import.meta.env.VITE_API_PROXY_TARGET || "").trim();
  if (proxyTarget) {
    try {
      return new URL("/docs", proxyTarget).toString();
    } catch {
      return "/docs";
    }
  }

  return "/docs";
}

function ThemeToggle() {
  const [mode, setMode] = useState<ColorMode>(() => (typeof document === "undefined" ? "dark" : currentColorMode()));
  const next = mode === "dark" ? "light" : "dark";
  return (
    <button
      type="button"
      className="icon-button"
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      onClick={() => {
        setColorMode(next);
        setMode(next);
      }}
    >
      {mode === "dark" ? (
        <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" aria-hidden="true">
          <circle cx="8" cy="8" r="2.8" />
          <path d="M8 1.5v1.6M8 12.9v1.6M1.5 8h1.6M12.9 8h1.6M3.4 3.4l1.1 1.1M11.5 11.5l1.1 1.1M3.4 12.6l1.1-1.1M11.5 4.5l1.1-1.1" />
        </svg>
      ) : (
        <svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" aria-hidden="true">
          <path d="M13.5 9.6A5.8 5.8 0 0 1 6.4 2.5a5.8 5.8 0 1 0 7.1 7.1Z" />
        </svg>
      )}
    </button>
  );
}

export default function AppShell() {
  const docsHref = resolveApiDocsHref();
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => api.getHealth(signal),
    refetchInterval: LIVE_REFETCH_INTERVAL_MS,
  });

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="topbar">
        <div className="shell flex h-full items-center gap-4 sm:gap-6">
          <NavLink to="/" className="wordmark" aria-label="Auctionscan home">
            AUCTION SCAN
          </NavLink>
          <nav className="flex items-center gap-4 self-end pb-3" aria-label="Primary">
            {primaryLinks.map((link) => (
              <NavLink
                key={link.label}
                to={link.to}
                end={link.exact}
                className={({ isActive }) => cn("nav-link", isActive && "nav-link-active")}
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <GlobalSearch />
            <DataAge chains={healthQuery.data?.chains} hasError={healthQuery.isError} docsHref={docsHref} />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="shell flex-1 pb-4 pt-4 md:pt-5">
        <Outlet />
      </main>

      <footer className="shell site-footer">
        <NavLink to="/status">Status</NavLink>
        <span aria-hidden="true">|</span>
        <NavLink to="/pricing">Docs</NavLink>
        <span aria-hidden="true">|</span>
        <a href={docsHref} target="_blank" rel="noreferrer">API Docs</a>
      </footer>
    </div>
  );
}
