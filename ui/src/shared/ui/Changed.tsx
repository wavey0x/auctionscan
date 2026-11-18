import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

import { cn } from "../lib/format";

/**
 * Wraps a figure that refreshes in place. When its value changes after the
 * first paint, one band of light crosses it; at rest it is a plain span.
 */
export default function Changed({
  value,
  children,
  className,
}: {
  value: unknown;
  children: ReactNode;
  className?: string;
}) {
  const previous = useRef(value);
  const ref = useRef<HTMLSpanElement>(null);
  const [pass, setPass] = useState<{ tick: number; x: number }>({ tick: 0, x: 0 });

  useLayoutEffect(() => {
    if (Object.is(previous.current, value)) {
      return;
    }
    previous.current = value;
    const left = ref.current?.getBoundingClientRect().left ?? 0;
    setPass((current) => ({ tick: current.tick + 1, x: Math.round(left) }));
  }, [value]);

  return (
    <span
      key={pass.tick}
      ref={ref}
      className={cn(pass.tick > 0 && "changed", className)}
      style={pass.tick > 0 ? ({ "--x": `${pass.x}px` } as CSSProperties) : undefined}
    >
      {children}
    </span>
  );
}
