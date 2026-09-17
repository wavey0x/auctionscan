import { cn } from "../lib/format";

interface SkeletonProps {
  className?: string;
}

export default function Skeleton({ className }: SkeletonProps) {
  return <div aria-hidden="true" className={cn("skeleton-block rounded", className)} />;
}
