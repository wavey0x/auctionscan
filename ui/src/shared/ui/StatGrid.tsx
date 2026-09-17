import type { PropsWithChildren } from "react";

import { cn } from "../lib/format";

interface StatGridProps extends PropsWithChildren {
  className?: string;
  columns?: 1 | 2 | 3 | 4;
}

const columnClassNames: Record<NonNullable<StatGridProps["columns"]>, string> = {
  1: "grid-cols-1",
  2: "grid-cols-2",
  3: "grid-cols-2 md:grid-cols-3",
  4: "grid-cols-2 xl:grid-cols-4",
};

export default function StatGrid({
  children,
  className,
  columns = 2,
}: StatGridProps) {
  return (
    <div className={cn("grid gap-3", columnClassNames[columns], className)}>
      {children}
    </div>
  );
}
