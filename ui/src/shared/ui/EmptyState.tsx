import { cn } from "../lib/format";

interface EmptyStateProps {
  title: string;
  description?: string;
  titleClassName?: string;
  className?: string;
}

/** One quiet line where the list would be: what would be here, and why it is not. */
export default function EmptyState({ title, description, titleClassName, className }: EmptyStateProps) {
  return (
    <div className={cn("px-4 py-9 text-center", className)}>
      <div className={cn("text-body text-secondary", titleClassName)}>{title}</div>
      {description ? <p className="mx-auto mt-1 max-w-md text-data text-tertiary">{description}</p> : null}
    </div>
  );
}
