import type { HTMLAttributes, PropsWithChildren } from "react";

import { cn } from "../lib/format";

interface StackedListRowProps extends PropsWithChildren, HTMLAttributes<HTMLDivElement> {
  interactive?: boolean;
}

export default function StackedListRow({
  children,
  className,
  interactive = false,
  ...props
}: StackedListRowProps) {
  return (
    <div
      className={cn(
        "border-b border-divider-subtle px-3 py-3 last:border-b-0",
        interactive && "cursor-pointer transition-colors hover:bg-background",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}
