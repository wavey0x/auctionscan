import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from "react";
import { useEffect, useRef } from "react";

import { cn } from "../../../shared/lib/format";

interface RoundModalProps {
  ariaLabel: string;
  children: ReactNode;
  onClose: () => void;
  className?: string;
}

function getFocusableElements(root: HTMLElement | null): HTMLElement[] {
  if (!root) {
    return [];
  }

  const selectors = [
    "a[href]",
    "button:not([disabled])",
    "input:not([disabled])",
    "select:not([disabled])",
    "textarea:not([disabled])",
    "[tabindex]:not([tabindex='-1'])",
  ];

  return Array.from(root.querySelectorAll<HTMLElement>(selectors.join(","))).filter(
    (element) => !element.hasAttribute("disabled") && !element.getAttribute("aria-hidden"),
  );
}

export default function RoundModal({
  ariaLabel,
  children,
  onClose,
  className,
}: RoundModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    restoreFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const scrollY = window.scrollY;
    const bodyStyle = document.body.style;
    const previous = {
      position: bodyStyle.position,
      top: bodyStyle.top,
      left: bodyStyle.left,
      right: bodyStyle.right,
      width: bodyStyle.width,
      overflow: bodyStyle.overflow,
    };

    bodyStyle.position = "fixed";
    bodyStyle.top = `-${scrollY}px`;
    bodyStyle.left = "0";
    bodyStyle.right = "0";
    bodyStyle.width = "100%";
    bodyStyle.overflow = "hidden";

    const focusTarget =
      dialogRef.current?.querySelector<HTMLElement>("[data-autofocus]") ?? dialogRef.current;
    focusTarget?.focus();

    return () => {
      bodyStyle.position = previous.position;
      bodyStyle.top = previous.top;
      bodyStyle.left = previous.left;
      bodyStyle.right = previous.right;
      bodyStyle.width = previous.width;
      bodyStyle.overflow = previous.overflow;
      window.scrollTo(0, scrollY);
      restoreFocusRef.current?.focus?.();
    };
  }, []);

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab") {
      return;
    }

    const focusables = getFocusableElements(dialogRef.current);
    if (!focusables.length) {
      event.preventDefault();
      dialogRef.current?.focus();
      return;
    }

    const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const currentIndex = activeElement ? focusables.indexOf(activeElement) : -1;

    if (event.shiftKey) {
      if (currentIndex <= 0) {
        event.preventDefault();
        focusables[focusables.length - 1]?.focus();
      }
      return;
    }

    if (currentIndex === -1 || currentIndex === focusables.length - 1) {
      event.preventDefault();
      focusables[0]?.focus();
    }
  };

  return (
    <div className="fixed inset-0 z-[70]">
      <div
        className="absolute inset-0 bg-black/45 md:bg-black/40 xl:bg-black/50"
        onClick={onClose}
      />
      <div className="pointer-events-none absolute inset-0 flex items-end justify-center px-2 pb-0 pt-[max(env(safe-area-inset-top),0.5rem)] md:items-center md:p-4 xl:p-6">
        <div
          ref={dialogRef}
          tabIndex={-1}
          role="dialog"
          aria-modal="true"
          aria-label={ariaLabel}
          onKeyDown={handleKeyDown}
          className={cn(
            "pointer-events-auto flex h-full w-full flex-col overflow-hidden overscroll-y-contain border border-divider-strong bg-surface shadow-2xl",
            "rounded-t-[20px] border-b-0 md:h-auto md:max-h-[86vh] md:max-w-[calc(100vw-2rem)] md:rounded-lg md:border-b xl:max-h-[84vh] xl:max-w-6xl",
            className,
          )}
        >
          {children}
        </div>
      </div>
    </div>
  );
}
