import type { FocusEventHandler, MouseEvent, MouseEventHandler, ReactNode } from "react";
import { ArrowUpRight } from "lucide-react";
import { Link } from "react-router-dom";

import { buildExplorerUrl, useChainInfo } from "../lib/chains";
import { cn, formatAddress, formatMiddleEllipsis } from "../lib/format";
import CopyIconButton from "./CopyIconButton";

interface AddressValueProps {
  address?: string | null;
  chainId?: number | null;
  className?: string;
  width?: number;
  label?: string | null;
  labelWidth?: number;
  internalTo?: string | null;
  showExplorerIcon?: boolean;
  showTitle?: boolean;
  leadingVisual?: ReactNode;
  trailingActions?: ReactNode;
  onMouseEnter?: MouseEventHandler<HTMLSpanElement>;
  onMouseLeave?: MouseEventHandler<HTMLSpanElement>;
  onFocusCapture?: FocusEventHandler<HTMLSpanElement>;
  onBlurCapture?: FocusEventHandler<HTMLSpanElement>;
}

export default function AddressValue({
  address,
  chainId,
  className,
  width = 6,
  label,
  labelWidth = 14,
  internalTo,
  showExplorerIcon,
  showTitle = true,
  leadingVisual,
  trailingActions,
  onMouseEnter,
  onMouseLeave,
  onFocusCapture,
  onBlurCapture,
}: AddressValueProps) {
  const { chain } = useChainInfo(chainId);
  const href = buildExplorerUrl(chain, "address", address);
  const displayLabel = label ? formatMiddleEllipsis(label, labelWidth, 6) : formatAddress(address, width);
  const displayAddressSuffix = label && address ? `(${formatAddress(address, 6, 0)})` : null;
  const shouldShowExplorerIcon = showExplorerIcon ?? Boolean(internalTo);
  const title = showTitle ? (label?.trim() || address || undefined) : undefined;
  const textClassName = label
    ? "identity-link min-w-0 max-w-full shrink overflow-hidden text-[12px] leading-none"
    : "identity-link font-mono";
  const staticClassName = label
    ? "min-w-0 max-w-full overflow-hidden text-primary text-[12px] leading-none"
    : "font-mono text-primary";

  const stopRowClick = (event: MouseEvent<HTMLElement>) => {
    event.stopPropagation();
  };

  const content = label ? (
    <span className="inline-flex min-w-0 max-w-full items-baseline gap-1 overflow-hidden whitespace-nowrap">
      <span className="min-w-0 truncate text-primary">{displayLabel}</span>
      {displayAddressSuffix ? (
        <span className="shrink-0 font-mono text-[10px] text-tertiary">
          {displayAddressSuffix}
        </span>
      ) : null}
    </span>
  ) : (
    displayLabel
  );

  return (
    <span
      className={cn("identity-inline max-w-full", className)}
      title={title}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onFocusCapture={onFocusCapture}
      onBlurCapture={onBlurCapture}
    >
      {leadingVisual ? <span className="shrink-0">{leadingVisual}</span> : null}
      {internalTo && address ? (
        <Link
          to={internalTo}
          className={textClassName}
          onClick={stopRowClick}
        >
          {content}
        </Link>
      ) : href && address ? (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className={textClassName}
          onClick={stopRowClick}
        >
          {content}
        </a>
      ) : (
        <span className={staticClassName}>{content}</span>
      )}
      {shouldShowExplorerIcon && href && address ? (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="icon-link-trigger"
          title={`Open address ${address} in explorer`}
          aria-label={`Open address ${address} in explorer`}
          onClick={stopRowClick}
        >
          <ArrowUpRight className="h-3 w-3" strokeWidth={1.8} />
        </a>
      ) : null}
      {address ? (
        <CopyIconButton
          valueToCopy={address}
          title={`Copy address ${address}`}
          ariaLabel={`Copy address ${address}`}
        />
      ) : null}
      {trailingActions}
    </span>
  );
}
