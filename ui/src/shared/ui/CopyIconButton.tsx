import { useEffect, useRef, useState, type MouseEvent } from "react";

import { cn } from "../lib/format";

interface CopyIconButtonProps {
  valueToCopy?: string | null;
  title: string;
  ariaLabel: string;
  className?: string;
}

export default function CopyIconButton({
  valueToCopy,
  title,
  ariaLabel,
  className,
}: CopyIconButtonProps) {
  const [copied, setCopied] = useState(false);
  const resetTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (resetTimerRef.current) {
        window.clearTimeout(resetTimerRef.current);
      }
    };
  }, []);

  async function handleCopy(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation();

    if (!valueToCopy || !navigator.clipboard) {
      return;
    }

    try {
      await navigator.clipboard.writeText(valueToCopy);
      setCopied(true);

      if (resetTimerRef.current) {
        window.clearTimeout(resetTimerRef.current);
      }

      resetTimerRef.current = window.setTimeout(() => {
        setCopied(false);
      }, 1500);
    } catch {
      // Ignore clipboard failures in unsupported contexts.
    }
  }

  return (
    <button
      type="button"
      className={cn("copy-trigger", copied && "is-copied", className)}
      title={title}
      aria-label={ariaLabel}
      onClick={handleCopy}
    >
      <span className="copy-icon" aria-hidden="true">
        <svg className="copy-glyph" viewBox="0 0 16 16">
          <rect className="copy-back" x="3" y="5.5" width="7" height="9" rx="1.5" />
          <rect className="copy-front" x="6" y="2.5" width="7" height="9" rx="1.5" />
        </svg>
        <svg className="check-glyph" viewBox="0 0 16 16">
          <path d="M3 8.5L6.5 12L13 4.5" />
        </svg>
      </span>
    </button>
  );
}
