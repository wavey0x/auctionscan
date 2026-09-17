import { cn } from "../lib/format";
import AddressValue from "./AddressValue";
import { useTableHover } from "./TableHoverContext";
import TakerBlockie from "./TakerBlockie";

interface TakerAddressValueProps {
  address?: string | null;
  chainId?: number | null;
  className?: string;
  width?: number;
  showBlockie?: boolean;
  blockieSize?: number;
}

export default function TakerAddressValue({
  address,
  chainId,
  className,
  width = 6,
  showBlockie = false,
  blockieSize = 18,
}: TakerAddressValueProps) {
  const hover = useTableHover("taker", address);

  return (
    <AddressValue
      address={address}
      chainId={chainId}
      className={cn(
        className,
        hover.inScope ? "hover-match-target" : null,
        hover.isHovered ? "hover-match-active" : null,
      )}
      width={width}
      leadingVisual={showBlockie ? <TakerBlockie address={address} size={blockieSize} /> : null}
      onMouseEnter={hover.bind?.onMouseEnter}
      onMouseLeave={hover.bind?.onMouseLeave}
      onFocusCapture={hover.bind?.onFocusCapture}
      onBlurCapture={hover.bind?.onBlurCapture}
    />
  );
}
