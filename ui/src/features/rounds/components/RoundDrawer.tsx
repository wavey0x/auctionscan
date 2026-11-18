import { useEffect, useRef, useState, type ReactNode } from "react";

import { cn } from "../../../shared/lib/format";

const SHEET_QUERY = "(max-width: 700px)";

function useIsSheet(): boolean {
  const [matches, setMatches] = useState(() => typeof window !== "undefined" && window.matchMedia?.(SHEET_QUERY).matches === true);
  useEffect(() => {
    const query = window.matchMedia?.(SHEET_QUERY);
    if (!query) return undefined;
    const update = () => setMatches(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return matches;
}

/** Anything a pointer can act on keeps the drawer open: it either moves it or works inside it. */
const KEEP_OPEN_SELECTOR = [
  "a",
  "button",
  "input",
  "select",
  "textarea",
  "label",
  "[role='button']",
  "[role='listbox']",
  "[role='option']",
  "[data-row]",
  "[data-keep-drawer]",
  ".topbar",
].join(",");

/**
 * The round workspace floats over the right of the list without a scrim, so
 * the list never moves when it opens. Under 700px it becomes a bottom sheet
 * over a dimmed page.
 */
export default function RoundDrawer({
  ariaLabel,
  children,
  onClose,
  className,
}: {
  ariaLabel: string;
  children: ReactNode;
  onClose: () => void;
  className?: string;
}) {
  const drawerRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const isSheet = useIsSheet();

  useEffect(() => {
    const restore = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    drawerRef.current?.focus({ preventScroll: true });
    document.body.classList.add("has-drawer");
    return () => {
      document.body.classList.remove("has-drawer");
      if (restore && document.contains(restore)) restore.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    if (!isSheet) return undefined;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [isSheet]);

  useEffect(() => {
    if (isSheet) return undefined;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (drawerRef.current?.contains(target)) return;
      if (target.closest(KEEP_OPEN_SELECTOR)) return;
      onCloseRef.current();
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [isSheet]);

  return (
    <>
      {isSheet ? <div className="scrim" aria-hidden="true" onClick={onClose} /> : null}
      <aside
        ref={drawerRef}
        tabIndex={-1}
        role="dialog"
        aria-modal={isSheet}
        aria-label={ariaLabel}
        className={cn("drawer", className)}
      >
        {children}
      </aside>
    </>
  );
}
