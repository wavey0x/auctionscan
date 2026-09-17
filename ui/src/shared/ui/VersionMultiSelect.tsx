import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";

import { cn } from "../lib/format";
import type { AuctionVersionOption } from "../types/api";

const MENU_MIN_WIDTH = 168;
const MENU_MAX_HEIGHT = 248;
const VIEWPORT_MARGIN = 8;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function displayVersion(version: string): string {
  return version.startsWith("v") ? version : `v${version}`;
}

function countLabel(option: AuctionVersionOption): string {
  if (option.auction_count === 1) {
    return "1 auction";
  }
  return `${option.auction_count.toLocaleString()} auctions`;
}

export default function VersionMultiSelect({
  value,
  options,
  className,
  onChange,
}: {
  value: string[];
  options: AuctionVersionOption[];
  className?: string;
  onChange: (nextValue: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [menuPosition, setMenuPosition] = useState<{ left: number; top: number; width: number } | null>(null);

  const selectedSet = useMemo(() => new Set(value), [value]);
  const summary = useMemo(() => {
    if (value.length === 0) {
      return "All versions";
    }
    if (value.length === 1) {
      return displayVersion(value[0]);
    }
    return `${displayVersion(value[0])} +${value.length - 1}`;
  }, [value]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const updatePosition = () => {
      const trigger = buttonRef.current;
      if (!trigger) {
        return;
      }
      const rect = trigger.getBoundingClientRect();
      const estimatedMenuHeight = Math.min(Math.max(options.length, 1) * 34 + 2, MENU_MAX_HEIGHT);
      const width = Math.max(MENU_MIN_WIDTH, Math.ceil(rect.width));
      const left = clamp(rect.left, VIEWPORT_MARGIN, window.innerWidth - width - VIEWPORT_MARGIN);
      const spaceBelow = window.innerHeight - rect.bottom - VIEWPORT_MARGIN;
      const spaceAbove = rect.top - VIEWPORT_MARGIN;
      const openUpwards = spaceBelow < estimatedMenuHeight && spaceAbove > spaceBelow;
      const top = openUpwards
        ? Math.max(VIEWPORT_MARGIN, rect.top - estimatedMenuHeight - 4)
        : Math.min(window.innerHeight - estimatedMenuHeight - VIEWPORT_MARGIN, rect.bottom + 4);
      setMenuPosition({ left, top, width });
    };

    updatePosition();

    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) {
        setOpen(false);
      }
    };

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    window.addEventListener("pointerdown", handlePointerDown);
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("resize", updatePosition);
    window.addEventListener("scroll", updatePosition, true);
    return () => {
      window.removeEventListener("pointerdown", handlePointerDown);
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("resize", updatePosition);
      window.removeEventListener("scroll", updatePosition, true);
    };
  }, [open, options.length]);

  const toggleVersion = (version: string) => {
    const nextSet = new Set(value);
    if (nextSet.has(version)) {
      nextSet.delete(version);
    } else {
      nextSet.add(version);
    }
    const ordered = options.map((option) => option.version).filter((optionVersion) => nextSet.has(optionVersion));
    const unavailableSelected = value.filter(
      (selectedVersion) => !options.some((option) => option.version === selectedVersion) && nextSet.has(selectedVersion),
    );
    onChange([...ordered, ...unavailableSelected]);
  };

  return (
    <div ref={rootRef} className={cn("relative", className)}>
      <button
        ref={buttonRef}
        type="button"
        className={cn("filter-select flex w-full items-center justify-between gap-2 text-left", open && "border-primary")}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Version filter"
        onClick={() => setOpen((current) => !current)}
      >
        <span className="min-w-0 truncate">{summary}</span>
        <ChevronDown className={cn("h-4 w-4 shrink-0 text-tertiary transition-transform", open && "rotate-180")} strokeWidth={1.8} />
      </button>
      {open && menuPosition ? createPortal(
        <div
          ref={menuRef}
          className="fixed z-[95] overflow-hidden rounded-md border border-divider-strong bg-surface"
          style={{
            left: menuPosition.left,
            top: menuPosition.top,
            width: menuPosition.width,
            maxHeight: MENU_MAX_HEIGHT,
          }}
        >
          <div
            role="listbox"
            aria-label="Version filter"
            aria-multiselectable="true"
            className="overflow-y-auto overscroll-contain"
            style={{ maxHeight: MENU_MAX_HEIGHT }}
          >
            {options.length ? options.map((option) => {
              const active = selectedSet.has(option.version);
              return (
                <button
                  key={option.version}
                  type="button"
                  role="option"
                  aria-selected={active}
                  className={cn(
                    "flex w-full items-center justify-between gap-3 border-b border-divider-subtle px-2.5 py-2 text-left font-mono text-[12px] leading-none text-secondary transition-colors last:border-b-0 hover:bg-background hover:text-primary",
                    active && "bg-background text-primary",
                  )}
                  onClick={() => toggleVersion(option.version)}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <Check className={cn("h-3 w-3 shrink-0", active ? "text-primary" : "opacity-0")} strokeWidth={2.2} />
                    <span className="truncate">{displayVersion(option.version)}</span>
                  </span>
                  <span className="shrink-0 text-[10px] text-tertiary">{countLabel(option)}</span>
                </button>
              );
            }) : (
              <div className="px-2.5 py-2 font-mono text-[12px] leading-none text-tertiary">No versions</div>
            )}
          </div>
        </div>,
        document.body,
      ) : null}
    </div>
  );
}
