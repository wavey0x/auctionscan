/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        background: "var(--color-background)",
        surface: "var(--color-surface)",
        primary: "var(--color-primary)",
        secondary: "var(--color-secondary)",
        tertiary: "var(--color-tertiary)",
        divider: {
          strong: "var(--color-divider-strong)",
          subtle: "var(--color-divider-subtle)",
        },
        active: "var(--color-active)",
        complete: "var(--color-complete)",
        settled: "var(--color-settled)",
        kickable: "var(--color-kickable)",
        positive: "var(--color-positive)",
        negative: "var(--color-negative)",
        warning: "var(--color-warning)",
      },
      fontFamily: {
        sans: [
          "IBM Plex Mono",
          "Azeret Mono",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
        mono: [
          "IBM Plex Mono",
          "Azeret Mono",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      fontSize: {
        title: ["18px", { lineHeight: "24px" }],
        heading: ["16px", { lineHeight: "22px" }],
        body: ["13px", { lineHeight: "18px" }],
        meta: ["12px", { lineHeight: "16px" }],
        data: ["12px", { lineHeight: "16px" }],
        "table-header": ["11px", { lineHeight: "16px", letterSpacing: "0.08em" }],
      },
      maxWidth: {
        shell: "1600px",
      },
      minWidth: {
        status: "7.5rem",
      },
    },
  },
  plugins: [],
}
