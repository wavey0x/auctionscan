import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationProps {
  page: number;
  hasNext: boolean;
  onPageChange: (page: number) => void;
  summary?: string;
}

export default function Pagination({ page, hasNext, onPageChange, summary }: PaginationProps) {
  return (
    <div className="flex flex-wrap items-center justify-end gap-2 text-meta text-tertiary">
      {summary ? <span className="whitespace-nowrap">{summary}</span> : null}
      <div className="inline-flex items-center gap-0.5 rounded-md border border-divider-subtle bg-background px-1 py-0.5">
        <button
          className="inline-flex h-6 w-6 items-center justify-center rounded-sm text-tertiary transition-colors hover:bg-surface hover:text-primary disabled:cursor-not-allowed disabled:text-tertiary disabled:hover:bg-background"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          aria-label="Previous page"
          title="Previous page"
        >
          <ChevronLeft className="h-3 w-3" strokeWidth={1.8} />
        </button>
        <span className="min-w-[3.75rem] px-1 text-center font-mono text-[11px] text-primary">Page {page}</span>
        <button
          className="inline-flex h-6 w-6 items-center justify-center rounded-sm text-tertiary transition-colors hover:bg-surface hover:text-primary disabled:cursor-not-allowed disabled:text-tertiary disabled:hover:bg-background"
          onClick={() => onPageChange(page + 1)}
          disabled={!hasNext}
          aria-label="Next page"
          title="Next page"
        >
          <ChevronRight className="h-3 w-3" strokeWidth={1.8} />
        </button>
      </div>
    </div>
  );
}
