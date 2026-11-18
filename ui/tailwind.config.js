/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        background: "var(--color-background)",
        surface: "var(--color-surface)",
        inset: "var(--color-inset)",
        hover: "var(--color-hover)",
        selected: "var(--color-selected)",
        track: "var(--color-track)",
        key: "var(--color-key)",
        primary: "var(--color-primary)",
        secondary: "var(--color-secondary)",
        tertiary: "var(--color-tertiary)",
        faint: "var(--color-faint)",
        accent: "var(--color-accent)",
        divider: {
          DEFAULT: "var(--color-divider)",
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
        sans: ["var(--font-sans)"],
        mono: ["var(--font-mono)"],
      },
      fontSize: {
        title: ["18px", { lineHeight: "24px" }],
        heading: ["15px", { lineHeight: "21px" }],
        body: ["13px", { lineHeight: "18px" }],
        meta: ["12px", { lineHeight: "16px" }],
        data: ["12px", { lineHeight: "16px" }],
        caption: ["11px", { lineHeight: "15px" }],
        "table-header": ["11px", { lineHeight: "16px" }],
      },
      maxWidth: {
        shell: "1296px",
      },
      minWidth: {
        status: "7.5rem",
      },
    },
  },
  plugins: [],
}
