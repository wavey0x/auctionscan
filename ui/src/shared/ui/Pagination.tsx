import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationProps {
  page: number;
  hasNext: boolean;
  onPageChange: (page: number) => void;
  summary?: string;
}

export default function Pagination({ page, hasNext, onPageChange, summary }: PaginationProps) {
  if (page <= 1 && !hasNext && !summary) {
    return null;
  }
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-caption text-tertiary">
      <span className="whitespace-nowrap font-mono">{summary ?? ""}</span>
      <div className="segmented" role="group" aria-label="Pages">
        <button
          type="button"
          className="inline-flex items-center disabled:cursor-not-allowed disabled:opacity-40"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          aria-label="Previous page"
          title="Previous page"
        >
          <ChevronLeft className="h-3 w-3" strokeWidth={1.8} />
        </button>
        <span className="px-2 py-[5px] font-mono text-[11px] leading-none text-primary">Page {page}</span>
        <button
          type="button"
          className="inline-flex items-center disabled:cursor-not-allowed disabled:opacity-40"
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
