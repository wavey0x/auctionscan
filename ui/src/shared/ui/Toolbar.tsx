import type { ReactNode } from "react";
import { Search, X } from "lucide-react";

import { cn, formatCount } from "../lib/format";

/** The number of rows a filter choice would give, set quietly beside its label. */
export function ChipCount({ value }: { value: number | null | undefined }) {
  return value === null || value === undefined ? null : <span className="chip-count">{formatCount(value)}</span>;
}

export interface ChipOption<T extends string | number> {
  value: T;
  label: ReactNode;
  title?: string;
  icon?: boolean;
  mono?: boolean;
}

/**
 * A filter group: one framed track of keys. What is chosen is a filled key,
 * and pressing it again lets it go; with nothing filled the group filters
 * nothing. Multi-select unless `single`. A group may open with a reset chip
 * named for it (`resetLabel`) where its keys alone would not say what they
 * choose between. Every filter on a list is one of these, whatever it filters
 * by.
 */
export function ChipGroup<T extends string | number>({
  label,
  resetLabel,
  options,
  selected,
  onChange,
  single = false,
}: {
  label: string;
  resetLabel?: ReactNode;
  options: ChipOption<T>[];
  selected: T[];
  onChange: (next: T[]) => void;
  single?: boolean;
}) {
  const chosen = new Set(selected);
  return (
    <div className="chips" role="group" aria-label={label}>
      {resetLabel === undefined ? null : (
        <button type="button" className="chip" aria-pressed={selected.length === 0} onClick={() => onChange([])}>
          {resetLabel}
        </button>
      )}
      {options.map((option) => {
        const isOn = chosen.has(option.value);
        return (
          <button
            key={String(option.value)}
            type="button"
            className={cn("chip", option.icon && "chip-icon", option.mono && "chip-mono")}
            aria-pressed={isOn}
            title={option.title}
            aria-label={option.title}
            onClick={() => {
              if (single) {
                onChange(isOn ? [] : [option.value]);
                return;
              }
              onChange(isOn ? selected.filter((item) => item !== option.value) : [...selected, option.value]);
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * A span of days, framed like a filter group: a first and a last day, either
 * of which may be left open. Days are UTC calendar dates (`YYYY-MM-DD`).
 */
export function DateRange({
  label,
  from,
  to,
  onChange,
}: {
  label: string;
  from: string;
  to: string;
  onChange: (next: { from: string; to: string }) => void;
}) {
  return (
    <div className="date-range" role="group" aria-label={label} title={`${label}, UTC days`}>
      <input
        type="date"
        aria-label={`${label} from`}
        value={from}
        max={to || undefined}
        className={cn(!from && "is-empty")}
        onChange={(event) => onChange({ from: event.target.value, to })}
      />
      <span aria-hidden="true">→</span>
      <input
        type="date"
        aria-label={`${label} to`}
        value={to}
        min={from || undefined}
        className={cn(!to && "is-empty")}
        onChange={(event) => onChange({ from, to: event.target.value })}
      />
      {/* The clear mark keeps its place while there is nothing to clear, so the frame never resizes. */}
      <button
        type="button"
        aria-label={`Clear ${label.toLowerCase()} dates`}
        title="Clear dates"
        disabled={!from && !to}
        style={from || to ? undefined : { visibility: "hidden" }}
        onClick={() => onChange({ from: "", to: "" })}
      >
        <X className="h-3 w-3" strokeWidth={1.8} />
      </button>
    </div>
  );
}

/** A quiet search field: an underline that takes the accent while focused. */
export function FilterField({
  value,
  onChange,
  placeholder,
  label,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  label: string;
  className?: string;
}) {
  return (
    <label className={cn("filter-field", className)}>
      <Search className="h-3.5 w-3.5 shrink-0" strokeWidth={1.6} aria-hidden="true" />
      <span className="sr-only">{label}</span>
      <input
        type="search"
        value={value}
        placeholder={placeholder}
        autoComplete="off"
        spellCheck={false}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
