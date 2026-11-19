import type { ReactNode } from "react";
import { Search } from "lucide-react";

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
 * A filter group: one framed track that opens with a reset chip named for the
 * group. What is chosen is a filled key. Multi-select unless `single`. Every
 * filter on a list is one of these, whatever it filters by.
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
  resetLabel: ReactNode;
  options: ChipOption<T>[];
  selected: T[];
  onChange: (next: T[]) => void;
  single?: boolean;
}) {
  const chosen = new Set(selected);
  return (
    <div className="chips" role="group" aria-label={label}>
      <button type="button" className="chip" aria-pressed={selected.length === 0} onClick={() => onChange([])}>
        {resetLabel}
      </button>
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
