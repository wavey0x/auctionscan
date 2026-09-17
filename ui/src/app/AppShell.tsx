import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";

import { api } from "../shared/api/client";
import { cn } from "../shared/lib/format";
import { summarizeNetworkHealth, type ChainHealthTone } from "../shared/lib/health";

const primaryLinks = [
  { to: "/", label: "Rounds", exact: true },
  { to: "/takers", label: "Takers" },
];

function footerStatusDotClass(tone: ChainHealthTone): string {
  if (tone === "healthy") {
    return "bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.28)]";
  }
  if (tone === "indexing" || tone === "degraded") {
    return "bg-amber-400 shadow-[0_0_10px_rgba(251,191,36,0.24)]";
  }
  if (tone === "error") {
    return "bg-rose-400 shadow-[0_0_10px_rgba(251,113,133,0.24)]";
  }
  return "bg-slate-500 shadow-[0_0_8px_rgba(148,163,184,0.18)]";
}

function footerStatusLabel(tone: ChainHealthTone): string {
  if (tone === "degraded") return "Updates delayed";
  if (tone === "healthy") {
    return "System healthy";
  }
  if (tone === "indexing") {
    return "Indexing in progress";
  }
  if (tone === "error") {
    return "Status issues detected";
  }
  return "No active indexed networks";
}

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

export default function AppShell() {
  const docsHref = resolveApiDocsHref();
  const healthQuery = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => api.getHealth(signal),
    refetchInterval: 3_000,
  });
  const statusTone = summarizeNetworkHealth(healthQuery.data?.chains, healthQuery.isError);
  const statusLabel = footerStatusLabel(statusTone);

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-40 border-b border-divider-strong bg-background backdrop-blur-sm">
        <div className="mx-auto flex max-w-shell items-center px-4 py-3 md:px-6">
          <div className="flex items-center gap-6">
            <NavLink to="/" className="text-heading text-primary">
              AUCTION SCAN
            </NavLink>
            <nav className="flex items-center gap-4">
              {primaryLinks.map((link) => (
                <NavLink
                  key={link.label}
                  to={link.to}
                  end={link.exact}
                  className={({ isActive }) =>
                    `nav-link ${isActive ? "nav-link-active" : ""}`
                  }
                >
                  {link.label}
                </NavLink>
              ))}
            </nav>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-shell px-4 py-4 pb-14 md:px-6 md:py-5 md:pb-14">
        <Outlet />
      </main>

      <footer className="fixed inset-x-0 bottom-0 z-30 border-t border-divider-subtle bg-surface/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-shell items-center justify-center px-4 py-1 text-meta text-tertiary md:px-6">
          <div className="flex items-center gap-2">
            <NavLink
              to="/status"
              className="inline-flex items-center gap-2 transition-colors hover:text-primary"
              title={statusLabel}
            >
              <span
                aria-hidden="true"
                className={cn(
                  "h-2 w-2 rounded-full ring-1 ring-white/10 transition-colors",
                  footerStatusDotClass(statusTone),
                )}
              />
              Status
            </NavLink>
            <span aria-hidden="true">|</span>
            <NavLink to="/pricing" className="transition-colors hover:text-primary">
              Docs
            </NavLink>
            <span aria-hidden="true">|</span>
            <a href={docsHref} target="_blank" rel="noreferrer" className="transition-colors hover:text-primary">
              API Docs
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
