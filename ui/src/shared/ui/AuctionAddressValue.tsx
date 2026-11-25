import type { ReactNode } from "react";

import { cn } from "../lib/format";
import AddressValue from "./AddressValue";
import { useTableHover } from "./TableHoverContext";

interface AuctionAddressValueProps {
  address?: string | null;
  chainId?: number | null;
  className?: string;
  width?: number;
  showCowExplorerIcon?: boolean;
  /** A name shown before the short address, for an auction known by name. */
  label?: string | null;
  /** Show a named auction by its name alone. */
  bareLabel?: boolean;
  /** A quiet note after the address, such as the round a row is about. */
  tag?: ReactNode;
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
  label,
  bareLabel,
  tag,
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
      label={label}
      bareLabel={bareLabel}
      tag={tag}
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
