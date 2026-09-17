import type { MouseEvent } from "react";

import { buildExplorerUrl, useChainInfo } from "../lib/chains";
import { cn, formatHash } from "../lib/format";
import CopyIconButton from "./CopyIconButton";

interface TxHashValueProps {
  txHash?: string | null;
  chainId?: number | null;
  className?: string;
  width?: number;
}

export default function TxHashValue({
  txHash,
  chainId,
  className,
  width = 8,
}: TxHashValueProps) {
  const { chain } = useChainInfo(chainId);
  const href = buildExplorerUrl(chain, "tx", txHash);
  const label = formatHash(txHash, width);

  const stopRowClick = (event: MouseEvent<HTMLAnchorElement>) => {
    event.stopPropagation();
  };

  return (
    <span className={cn("identity-inline", className)} title={txHash || undefined}>
      {href && txHash ? (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="identity-link font-mono"
          onClick={stopRowClick}
        >
          {label}
        </a>
      ) : (
        <span className="font-mono text-primary">{label}</span>
      )}
      {txHash ? (
        <CopyIconButton
          valueToCopy={txHash}
          title={`Copy transaction hash ${txHash}`}
          ariaLabel={`Copy transaction hash ${txHash}`}
        />
      ) : null}
    </span>
  );
}
