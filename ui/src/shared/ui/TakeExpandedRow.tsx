import type { TakeDetail } from "../types/api";
import EmptyState from "./EmptyState";
import Skeleton from "./Skeleton";
import TakeExpandedContent from "./TakeExpandedContent";

interface TakeExpandedRowProps {
  colSpan: number;
  take?: TakeDetail | null;
  isLoading?: boolean;
  priceSource?: string;
}

export default function TakeExpandedRow({
  colSpan,
  take,
  isLoading,
  priceSource,
}: TakeExpandedRowProps) {
  return (
    <tr className="bg-background">
      <td colSpan={colSpan} className="border-b border-divider-subtle px-3 py-3 md:px-4">
        <div className="rounded-md border border-divider-subtle bg-surface px-3 py-3">
          {isLoading ? (
            <Skeleton className="h-32 w-full" />
          ) : take ? (
            <TakeExpandedContent take={take} priceSource={priceSource} />
          ) : (
            <EmptyState title="Take not found" description="The selected take detail could not be loaded." />
          )}
        </div>
      </td>
    </tr>
  );
}
