import { ChevronRight } from "lucide-react";

/** The trailing mark of a row whose click opens its subject in place. */
export default function OpenMark() {
  return (
    <td className="open-cell" aria-hidden="true">
      <ChevronRight className="h-3.5 w-3.5" strokeWidth={1.6} />
    </td>
  );
}
