import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";

import type { PriceSourceOption } from "../types/api";
import { cn } from "../lib/format";

const MENU_MIN_WIDTH = 136;
const MENU_MAX_HEIGHT = 220;
const VIEWPORT_MARGIN = 8;

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export default function PriceSourceSelect({
  value,
  options,
  className,
  quiet = false,
  onChange,
}: {
  value: string;
  options: PriceSourceOption[];
  className?: string;
  /** A flat, labelled trigger for places where the control should recede, such as the round drawer. */
  quiet?: boolean;
  onChange: (nextValue: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const buttonRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [menuPosition, setMenuPosition] = useState<{ left: number; top: number; width: number } | null>(null);
  const selected = useMemo(
    () => options.find((option) => option.id === value) ?? options[0],
    [options, value],
  );

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
      const estimatedMenuHeight = Math.min(options.length * 33 + 2, MENU_MAX_HEIGHT);
      const width = Math.max(MENU_MIN_WIDTH, Math.ceil(rect.width));
      const left = clamp(quiet ? rect.right - width : rect.left, VIEWPORT_MARGIN, window.innerWidth - width - VIEWPORT_MARGIN);
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
  }, [open, options.length, quiet]);

  return (
    <div ref={rootRef} className={cn("relative inline-flex items-center", className)}>
      <button
        ref={buttonRef}
        type="button"
        className={cn(
          "inline-flex h-6 items-center font-mono text-[11px] font-normal leading-none transition-colors",
          quiet
            ? "-mr-1.5 gap-1.5 rounded-[4px] px-1.5 text-secondary hover:bg-hover hover:text-primary"
            : "min-w-[6.25rem] justify-between gap-2 rounded-[6px] bg-hover px-2 text-primary hover:bg-selected",
          open && (quiet ? "bg-hover text-primary" : "bg-selected"),
        )}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Price source"
        onClick={() => setOpen((current) => !current)}
      >
        {quiet ? <span className="text-faint">Source</span> : null}
        <span>{selected?.label ?? value}</span>
        <ChevronDown className={cn("text-tertiary transition-transform", quiet ? "h-3 w-3" : "h-3.5 w-3.5", open && "rotate-180")} strokeWidth={1.8} />
      </button>
      {open && menuPosition ? createPortal(
        <div
          ref={menuRef}
          className="fixed z-[95] overflow-hidden rounded-[8px] border border-divider bg-surface p-1 shadow-[var(--overlay-shadow)]"
          style={{
            left: menuPosition.left,
            top: menuPosition.top,
            width: menuPosition.width,
            maxHeight: MENU_MAX_HEIGHT,
          }}
        >
          <div role="listbox" aria-label="Price source" className="overflow-y-auto overscroll-contain" style={{ maxHeight: MENU_MAX_HEIGHT }}>
            {options.map((option) => {
              const active = option.id === value;
              return (
                <button
                  key={option.id}
                  type="button"
                  role="option"
                  aria-selected={active}
                  title={`${option.priced_take_count}/${option.total_take_count} takes with observed payment and quote; ${option.usd_priced_take_count}/${option.total_take_count} with USD comparison`}
                  className={cn(
                    "flex w-full items-center justify-between gap-3 rounded-[5px] px-2 py-1.5 text-left font-mono text-[12px] leading-none text-secondary transition-colors hover:bg-hover hover:text-primary",
                    active && "text-primary",
                  )}
                  onClick={() => {
                    onChange(option.id);
                    setOpen(false);
                  }}
                >
                  <span>{option.label} <span className="text-tertiary">{option.priced_take_count}/{option.total_take_count}</span></span>
                  <Check className={cn("h-3 w-3", active ? "text-primary" : "opacity-0")} strokeWidth={2.2} />
                </button>
              );
            })}
          </div>
        </div>,
        document.body,
      ) : null}
    </div>
  );
}
