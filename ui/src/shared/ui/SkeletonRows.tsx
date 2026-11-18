import { cn } from "../lib/format";

/** Placeholder rows in the shape of the table they stand in for. */
export default function SkeletonRows({
  widths,
  rows = 8,
  classNames,
}: {
  widths: Array<number | null>;
  rows?: number;
  classNames?: Array<string | undefined>;
}) {
  return (
    <>
      {Array.from({ length: rows }).map((_, row) => (
        <tr key={row} aria-hidden="true">
          {widths.map((width, column) => (
            <td key={column} className={classNames?.[column]}>
              {width ? (
                <span
                  className={cn("skeleton-bar", classNames?.[column]?.includes("num") && "ml-auto")}
                  style={{ width: `${Math.max(12, width - ((row * 7 + column * 13) % 24))}px` }}
                />
              ) : null}
            </td>
          ))}
        </tr>
      ))}
    </>
  );
}
