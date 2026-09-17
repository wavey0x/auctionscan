import type { PropsWithChildren } from "react";

import { cn } from "../lib/format";

interface PanelProps extends PropsWithChildren {
  className?: string;
  padded?: boolean;
}

export default function Panel({ children, className, padded = true }: PanelProps) {
  return (
    <section className={cn("panel", padded && "p-3 md:p-4", className)}>
      {children}
    </section>
  );
}
