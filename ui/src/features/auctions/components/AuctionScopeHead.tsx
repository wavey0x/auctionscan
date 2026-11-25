import type { ReactNode } from "react";
import { useState } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { Link, type To } from "react-router-dom";

import { formatAmount, formatCount, formatDuration, formatPrice } from "../../../shared/lib/format";
import { auctionLabel } from "../../../shared/lib/protocol";
import type { AuctionDetails } from "../../../shared/types/api";
import AddressValue from "../../../shared/ui/AddressValue";
import AuctionAddressValue from "../../../shared/ui/AuctionAddressValue";
import AuctionVersionBadge from "../../../shared/ui/AuctionVersionBadge";
import ChainIcon from "../../../shared/ui/ChainIcon";
import RequestError from "../../../shared/ui/RequestError";
import TokenPairValue from "../../../shared/ui/TokenPairValue";
import TokenValue from "../../../shared/ui/TokenValue";

const SELL_TOKEN_PREVIEW_LIMIT = 8;

function Fact({ label, children, title }: { label: string; children: ReactNode; title?: string }) {
  return (
    <div className="min-w-0" title={title}>
      <dt className="label">{label}</dt>
      <dd className="m-0 mt-1 text-data text-primary">{children}</dd>
    </div>
  );
}

function SellTokens({ chainId, tokens }: { chainId: number; tokens: AuctionDetails["from_tokens"] }) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? tokens : tokens.slice(0, SELL_TOKEN_PREVIEW_LIMIT);
  const overflow = Math.max(tokens.length - SELL_TOKEN_PREVIEW_LIMIT, 0);
  return (
    <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {visible.map((token) => <TokenValue key={token.address} token={token} chainId={chainId} showCopy />)}
      {overflow ? (
        <button type="button" className="text-tertiary transition-colors hover:text-primary" onClick={() => setExpanded((value) => !value)}>
          {expanded ? "Show less" : `+${overflow} more`}
        </button>
      ) : null}
    </span>
  );
}

function Facts({ auction }: { auction: AuctionDetails }) {
  const { activity, parameters } = auction;
  const partialVolume = activity.paid_take_count < activity.total_takes;
  return (
    <dl className="scope-facts reveal-row">
      {auction.from_tokens.length === 1 ? (
        <Fact label="Pair">
          <TokenPairValue fromToken={auction.from_tokens[0]} toToken={auction.want_token} chainId={auction.chain_id} showCopy />
        </Fact>
      ) : (
        <>
          <Fact label={`Sells · ${auction.from_tokens.length}`}>
            <SellTokens chainId={auction.chain_id} tokens={auction.from_tokens} />
          </Fact>
          <Fact label="For"><TokenValue token={auction.want_token} chainId={auction.chain_id} /></Fact>
        </>
      )}
      <Fact label="Receiver">
        <AddressValue address={auction.receiver} chainId={auction.chain_id} label={auction.receiver_name} />
      </Fact>
      <Fact label="Rounds"><span className="font-mono">{formatCount(activity.total_rounds)}</span></Fact>
      <Fact label="Takes"><span className="font-mono">{formatCount(activity.total_takes)}</span></Fact>
      <Fact
        label="Volume"
        title={partialVolume ? `Payment observed for ${activity.paid_take_count} of ${activity.total_takes} takes` : undefined}
      >
        <span className="font-mono">{activity.total_volume ? formatAmount(activity.total_volume) : "—"}</span>
        {activity.total_volume && auction.want_token.symbol ? <span className="ml-1.5 text-tertiary">{auction.want_token.symbol}</span> : null}
        {partialVolume ? <span className="stat-note">partial</span> : null}
      </Fact>
      {auction.protocol === "curve" ? (
        // A burner's lots share one curve, from a start to a floor over a fixed
        // window, so its price range is the one setting worth stating here.
        <Fact label="Lot price" title="Every lot's price falls from the first figure to the floor over its window">
          <span className="font-mono">
            {formatAmount(parameters.starting_price)} → {formatAmount(parameters.floor_price)} {auction.want_token.symbol}
          </span>
        </Fact>
      ) : (
        <>
          <Fact label="Decay">
            <span className="font-mono">{parameters.decay_percent ?? "—"}</span>
            {parameters.decay_percent && parameters.update_interval ? (
              <span className="ml-1.5 text-tertiary">{`/ ${formatDuration(parameters.update_interval)}`}</span>
            ) : null}
          </Fact>
          <Fact label="Duration"><span className="font-mono">{formatDuration(parameters.auction_length)}</span></Fact>
          <Fact label="Min price"><span className="font-mono">{formatPrice(parameters.minimum_price)}</span></Fact>
        </>
      )}
    </dl>
  );
}

/**
 * An auction opened on the rounds list. Its identity and settings head the
 * card its rounds are listed in, so opening an auction narrows the list where
 * it stands instead of leaving for another page. The head opens with the way
 * back to the whole list.
 */
export default function AuctionScopeHead({
  chainId,
  address,
  auctionQuery,
  backTo,
}: {
  chainId: number;
  address: string;
  auctionQuery: UseQueryResult<AuctionDetails | null>;
  /** The whole list as the reader left it. */
  backTo: To;
}) {
  const auction = auctionQuery.data;

  return (
    <header className="scope-head" aria-label="Auction" aria-busy={auctionQuery.isLoading}>
      <div className="scope-title reveal-row">
        <Link to={backTo} className="scope-back">
          <ArrowLeft className="h-3.5 w-3.5" strokeWidth={1.6} aria-hidden="true" />
          All rounds
        </Link>
        <span className="scope-sep" aria-hidden="true">/</span>
        <ChainIcon chainId={chainId} size="md" />
        {/* The address reads exactly as it did on the row that opened it. */}
        <h1 className="m-0 min-w-0 whitespace-nowrap text-heading font-normal text-primary [&_.identity-link]:text-heading">
          <AuctionAddressValue
            address={auction?.address ?? address}
            chainId={chainId}
            label={auctionLabel(auction?.protocol)}
            showCowExplorerIcon
          />
        </h1>
        <AuctionVersionBadge version={auction?.version} />
      </div>
      {auctionQuery.isLoading ? (
        <div className="scope-facts" aria-hidden="true">
          {[72, 150, 40, 40, 90, 64, 48, 64].map((width, index) => (
            <div key={index} className="space-y-2.5 py-1">
              <span className="skeleton-bar w-10" />
              <span className="skeleton-bar" style={{ width }} />
            </div>
          ))}
        </div>
      ) : auction ? (
        <Facts auction={auction} />
      ) : auctionQuery.isError ? (
        <div className="-mx-4"><RequestError message="Unable to load auction." onRetry={() => { void auctionQuery.refetch(); }} /></div>
      ) : null}
    </header>
  );
}
