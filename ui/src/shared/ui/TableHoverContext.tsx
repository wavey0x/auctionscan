import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

type HoverKind = "auction" | "token" | "taker";

interface TableHoverContextValue {
  hovered: Partial<Record<HoverKind, string | null>>;
  setHovered: (kind: HoverKind, value: string | null) => void;
}

const TableHoverContext = createContext<TableHoverContextValue | null>(null);

function normalizeHoverIdentity(value?: string | null): string | null {
  return value ? value.toLowerCase() : null;
}

export function TableHoverScope({ children }: { children: ReactNode }) {
  const [hovered, setHoveredState] = useState<Partial<Record<HoverKind, string | null>>>({});
  const value = useMemo<TableHoverContextValue>(
    () => ({
      hovered,
      setHovered: (kind, nextValue) => {
        setHoveredState((current) => {
          if ((current[kind] ?? null) === nextValue) {
            return current;
          }
          return { ...current, [kind]: nextValue };
        });
      },
    }),
    [hovered],
  );

  return <TableHoverContext.Provider value={value}>{children}</TableHoverContext.Provider>;
}

export function useTableHover(kind: HoverKind, identity?: string | null) {
  const context = useContext(TableHoverContext);
  const normalizedIdentity = normalizeHoverIdentity(identity);
  const isHovered = Boolean(
    context && normalizedIdentity && context.hovered[kind] === normalizedIdentity,
  );

  const bind = context && normalizedIdentity
    ? {
        onMouseEnter: () => context.setHovered(kind, normalizedIdentity),
        onMouseLeave: () => {
          if (context.hovered[kind] === normalizedIdentity) {
            context.setHovered(kind, null);
          }
        },
        onFocusCapture: () => context.setHovered(kind, normalizedIdentity),
        onBlurCapture: () => {
          if (context.hovered[kind] === normalizedIdentity) {
            context.setHovered(kind, null);
          }
        },
      }
    : undefined;

  return {
    inScope: Boolean(context),
    isHovered,
    bind,
  };
}
