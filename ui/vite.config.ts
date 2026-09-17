import { resolve } from "node:path";

import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

function escapeRegex(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function normalizeTargetPath(pathname: string): string {
  if (!pathname || pathname === "/") {
    return "";
  }
  return pathname.endsWith("/") ? pathname.slice(0, -1) : pathname;
}

export default defineConfig(({ mode }) => {
  const newRoot = resolve(__dirname, "..");
  const env = loadEnv(mode, newRoot, "");
  const apiBase = (env.VITE_API_BASE_URL || "/api").trim() || "/api";
  const proxyTarget = (env.VITE_API_PROXY_TARGET || "http://localhost:8000").trim();
  const isRelativeApiBase = apiBase.startsWith("/");
  const proxyUrl = new URL(proxyTarget);
  const targetOrigin = proxyUrl.origin;
  const targetPath = normalizeTargetPath(proxyUrl.pathname);
  const rewriteBase = targetPath || apiBase;

  return {
    plugins: [react()],
    envDir: newRoot,
    server: {
      port: 3001,
      proxy: isRelativeApiBase
        ? {
            [apiBase]: {
              target: targetOrigin,
              changeOrigin: true,
              secure: false,
              rewrite: (path) =>
                path.replace(
                  new RegExp(`^${escapeRegex(apiBase)}`),
                  rewriteBase,
                ),
            },
          }
        : undefined,
    },
    resolve: {
      alias: {
        "@": "/src",
      },
    },
  };
});
