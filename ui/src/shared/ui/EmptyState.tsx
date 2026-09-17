import { cn } from "../lib/format";

interface EmptyStateProps {
  title: string;
  description?: string;
  titleClassName?: string;
}

export default function EmptyState({ title, description, titleClassName }: EmptyStateProps) {
  return (
    <div className="panel p-6 text-center">
      <div className={cn("text-heading text-primary", titleClassName)}>{title}</div>
      {description ? <p className="mt-2 text-data text-tertiary">{description}</p> : null}
    </div>
  );
}
