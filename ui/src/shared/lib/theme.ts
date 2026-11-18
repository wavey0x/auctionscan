export type ColorMode = "light" | "dark";

const STORAGE_KEY = "ui_next_color_mode";

function stored(): ColorMode | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

/** Dark is the default; a choice made with the toggle is remembered per browser. */
export function initialColorMode(): ColorMode {
  return stored() ?? "dark";
}

export function applyColorMode(mode: ColorMode) {
  const root = document.documentElement;
  root.classList.toggle("dark", mode === "dark");
  const meta = document.querySelector('meta[name="theme-color"]');
  meta?.setAttribute("content", mode === "dark" ? "#0c0c0d" : "#f4f4f5");
}

export function currentColorMode(): ColorMode {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

export function setColorMode(mode: ColorMode) {
  applyColorMode(mode);
  try {
    window.localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // Private windows may refuse storage; the choice then lasts for this page.
  }
}
