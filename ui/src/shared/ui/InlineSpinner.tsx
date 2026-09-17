import { cn } from "../lib/format";

interface InlineSpinnerProps {
  className?: string;
}

export default function InlineSpinner({ className }: InlineSpinnerProps) {
  return (
    <span
      className={cn(
        "inline-flex h-3.5 w-3.5 shrink-0 animate-spin rounded-full border border-divider-strong border-t-primary/70",
        className,
      )}
      aria-hidden="true"
    />
  );
}
