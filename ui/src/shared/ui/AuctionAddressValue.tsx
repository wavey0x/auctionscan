import { cn } from "../lib/format";
import AddressValue from "./AddressValue";
import { useTableHover } from "./TableHoverContext";

interface AuctionAddressValueProps {
  address?: string | null;
  chainId?: number | null;
  className?: string;
  width?: number;
  showCowExplorerIcon?: boolean;
}

function buildCowExplorerUrl(address?: string | null) {
  if (!address) {
    return null;
  }
  return `https://explorer.cow.fi/address/${address}`;
}

export default function AuctionAddressValue({
  address,
  chainId,
  className,
  width = 6,
  showCowExplorerIcon = false,
}: AuctionAddressValueProps) {
  const hover = useTableHover("auction", address);
  const internalTo =
    address && chainId
      ? `/auction/${chainId}/${address}`
      : null;
  const cowExplorerUrl = buildCowExplorerUrl(address);

  return (
    <AddressValue
      address={address}
      chainId={chainId}
      className={cn(
        className,
        "auction-address-value",
        hover.inScope ? "hover-match-target" : null,
        hover.isHovered ? "hover-match-active" : null,
      )}
      width={width}
      internalTo={internalTo}
      showExplorerIcon
      trailingActions={
        showCowExplorerIcon && cowExplorerUrl ? (
          <a
            href={cowExplorerUrl}
            target="_blank"
            rel="noreferrer"
            className="icon-link-trigger text-[12px] leading-none"
            title={`Open auction ${address} in Cow Explorer`}
            aria-label={`Open auction ${address} in Cow Explorer`}
            onClick={(event) => event.stopPropagation()}
          >
            <span aria-hidden="true">🐄</span>
          </a>
        ) : null
      }
      showTitle={false}
      onMouseEnter={hover.bind?.onMouseEnter}
      onMouseLeave={hover.bind?.onMouseLeave}
      onFocusCapture={hover.bind?.onFocusCapture}
      onBlurCapture={hover.bind?.onBlurCapture}
    />
  );
}
