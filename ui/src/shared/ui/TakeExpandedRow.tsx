import type { TakeDetail } from "../types/api";
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
    <tr className="bg-inset">
      <td colSpan={colSpan} className="!h-auto border-b border-divider-subtle !py-3.5">
        {isLoading ? (
          <div className="grid grid-cols-2 gap-3">
            {Array.from({ length: 6 }).map((_, index) => <span key={index} className="skeleton-bar w-32" />)}
          </div>
        ) : take ? (
          <TakeExpandedContent take={take} priceSource={priceSource} />
        ) : null}
      </td>
    </tr>
  );
}
