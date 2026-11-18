import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link2, X } from "lucide-react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError } from "../../../shared/api/client";
import {
  cn,
  formatAmount,
  formatCompactUsd,
  formatDateTime,
  formatFullAmount,
  renderKickedValue,
  toggleKickedDisplayMode,
} from "../../../shared/lib/format";
import type { KickedDisplayMode } from "../../../shared/lib/format";
import { DEFAULT_PRICE_SOURCE, getRoundPricingBySource, resolvePriceSource, shouldShowPriceSourceSelector } from "../../../shared/lib/pricingSource";
import { formatPercent, getRoundProgressMetrics } from "../../../shared/lib/roundProgress";
import { buildRoundPath, parseOccurrence, parseRoundId } from "../../../shared/lib/routes";
import type { RoundListItem } from "../../../shared/types/api";
import AuctionAddressValue from "../../../shared/ui/AuctionAddressValue";
import AuctionVersionBadge from "../../../shared/ui/AuctionVersionBadge";
import ChainIcon from "../../../shared/ui/ChainIcon";
import EmptyState from "../../../shared/ui/EmptyState";
import PnlValue from "../../../shared/ui/PnlValue";
import PriceSourceSelect from "../../../shared/ui/PriceSourceSelect";
import RequestError from "../../../shared/ui/RequestError";
import RoundProgressMini from "../../../shared/ui/RoundProgressMini";
import StatusBadge from "../../../shared/ui/StatusBadge";
import TokenValue from "../../../shared/ui/TokenValue";
import { useRoundDetails } from "../useRoundDetails";
import DecayChart from "./DecayChart";
import RoundSettingsPanel from "./RoundSettingsPanel";
import RoundTakesTable from "./RoundTakesTable";

function IconButton({
  label,
  onClick,
  children,
  autoFocus = false,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
  autoFocus?: boolean;
}) {
  return (
    <button
      type="button"
      className="icon-button"
      aria-label={label}
      title={label}
      data-autofocus={autoFocus ? "true" : undefined}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function ModalCloseButton({ onClose }: { onClose: () => void; autoFocus?: boolean }) {
  return (
    <IconButton label="Close round detail" onClick={onClose}>
      <X className="h-4 w-4" strokeWidth={1.6} />
    </IconButton>
  );
}

function ShareButton() {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return undefined;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);
  return (
    <IconButton
      label={copied ? "Link copied" : "Copy link to this round"}
      onClick={() => {
        void navigator.clipboard?.writeText(window.location.href).then(() => setCopied(true), () => undefined);
      }}
    >
      <Link2 className={cn("h-4 w-4", copied && "text-positive")} strokeWidth={1.6} />
    </IconButton>
  );
}

function SummaryItem({ label, children, title }: { label: string; children: ReactNode; title?: string }) {
  return (
    <dl className="summary-item m-0 min-w-0" title={title}>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </dl>
  );
}

function SectionHead({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <h3 className="sec-head">
      <span className="font-medium text-tertiary">{children}</span>
      {aside}
    </h3>
  );
}

function ProgressSection({ round }: { round: RoundListItem }) {
  const metrics = getRoundProgressMetrics({
    status: round.status,
    kickedAt: round.kicked_at,
    scheduledEndAt: round.scheduled_end_at,
    endAt: round.end_at,
    availableAmount: round.available_amount,
    initialAvailable: round.initial_available,
    soldAmount: round.sold_amount,
    fromTokenSymbol: round.from_token_symbol,
  });
  const common = {
    status: round.status,
    kickedAt: round.kicked_at,
    scheduledEndAt: round.scheduled_end_at,
    endAt: round.end_at,
    availableAmount: round.available_amount,
    initialAvailable: round.initial_available,
    soldAmount: round.sold_amount,
    fromTokenSymbol: round.from_token_symbol,
    takeCount: round.take_count,
    width: 132,
    showFigure: false,
  };
  return (
    <div className="grid grid-cols-2 gap-x-6 px-5 pb-1">
      <div className="min-w-0">
        <div className="flex items-baseline justify-between text-[11px] text-tertiary">
          <span>Time</span>
          <span className="font-mono text-secondary">{formatPercent(metrics.timePercent)}</span>
        </div>
        <RoundProgressMini {...common} mode="time" className="mt-1.5 w-full [&_.bar]:!w-full" />
        <div className="mt-1 truncate text-[11px] text-tertiary">{metrics.timeDetail}</div>
      </div>
      <div className="min-w-0">
        <div className="flex items-baseline justify-between text-[11px] text-tertiary">
          <span>Sold</span>
          <span className="font-mono text-secondary">{formatPercent(metrics.soldPercent)}</span>
        </div>
        <RoundProgressMini {...common} mode="take" className="mt-1.5 w-full [&_.bar]:!w-full" />
        <div className="mt-1 truncate text-[11px] text-tertiary">{metrics.soldDetail}</div>
      </div>
    </div>
  );
}

function DrawerSkeleton({ onClose }: { onClose: () => void }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col" aria-busy="true">
      <header className="drawer-head">
        <span className="skeleton-bar w-10" />
        <span className="skeleton-bar w-16" />
        <span className="skeleton-bar w-28" />
        <div className="ml-auto"><ModalCloseButton onClose={onClose} /></div>
      </header>
      <div className="drawer-scroll">
        <div className="drawer-summary">
          <div className="summary-main space-y-2">
            <span className="skeleton-bar w-10" />
            <span className="skeleton-bar h-[22px] w-40" />
          </div>
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="space-y-2">
              <span className="skeleton-bar w-10" />
              <span className="skeleton-bar w-16" />
            </div>
          ))}
        </div>
        <div className="space-y-3 px-5 pt-4">
          <span className="skeleton-bar w-16" />
          <span className="skeleton-block block h-28 w-full" />
        </div>
        <div className="space-y-4 px-5 pt-6">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={index} className="flex gap-6">
              <span className="skeleton-bar w-16" />
              <span className="skeleton-bar" style={{ width: `${120 - index * 9}px` }} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function RoundModalContent({
  onClose,
}: {
  onClose: () => void;
}) {
  const { chainId, auctionAddress, roundId: roundIdParam } = useParams<{
    chainId: string;
    auctionAddress: string;
    roundId: string;
  }>();
  const location = useLocation();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [kickedDisplayMode, setKickedDisplayMode] = useState<KickedDisplayMode>("absolute");

  const chain = Number(chainId);
  const roundId = parseRoundId(roundIdParam);
  const validRound = Number.isSafeInteger(chain) && chain > 0 && roundId !== null && !!auctionAddress;
  const selectedTakeParam = searchParams.get("take");
  const requestedPriceSource = searchParams.get("priceSource");
  const selectedOccurrence = parseOccurrence(chain, selectedTakeParam);
  const {
    roundQuery,
    auctionQuery,
    takesQuery,
    selectedTakeQuery,
    livePriceQuery,
    round,
    selectedTake,
    roundNotFound,
    selectedTakeNotFound,
    priceReference,
    displayedLivePrice,
  } = useRoundDetails(chain, auctionAddress, roundId, selectedOccurrence);

  useEffect(() => {
    const take = selectedTakeQuery.isError ? undefined : selectedTakeQuery.data;
    if (!take || !validRound || (take.round_id === roundId && take.auction.toLowerCase() === auctionAddress?.toLowerCase())) return;
    // The transfer remains the identity even if corrected inference moves it to another round.
    navigate({ pathname: buildRoundPath(chain, take.auction, take.round_id), search: location.search }, { replace: true, state: location.state });
  }, [selectedTakeQuery.data, selectedTakeQuery.isError, roundId, auctionAddress, validRound, chain, location.search, location.state, navigate]);

  const replaceModalSearchParams = (next: URLSearchParams) => {
    setSearchParams(next, { replace: true, state: location.state });
  };

  const setSelectedTake = (key?: string) => {
    const next = new URLSearchParams(searchParams);
    if (!key) {
      next.delete("take");
    } else {
      next.set("take", key);
    }
    replaceModalSearchParams(next);
  };

  const setPriceSource = (sourceId: string) => {
    const next = new URLSearchParams(searchParams);
    if (sourceId === DEFAULT_PRICE_SOURCE) {
      next.delete("priceSource");
    } else {
      next.set("priceSource", sourceId);
    }
    replaceModalSearchParams(next);
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }

      event.preventDefault();
      if (selectedTakeParam) {
        setSelectedTake(undefined);
        return;
      }

      onClose();
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, searchParams, selectedTakeParam, setSearchParams]);

  const takesNotFound = takesQuery.error instanceof ApiError && takesQuery.error.status === 404;
  const takes = takesNotFound ? [] : takesQuery.data?.takes || [];
  const selectedTakeNotice = !selectedTakeParam ? null : !selectedOccurrence ? (
    <EmptyState title="Invalid take link" className="py-4" />
  ) : selectedTakeNotFound || (selectedTakeQuery.isSuccess && !selectedTake) ? (
    <EmptyState title="Take not found" description="This occurrence is absent from the indexed round." className="py-4" />
  ) : selectedTakeQuery.isError ? (
    <RequestError message={selectedTake ? "Could not refresh take. Showing previously loaded data." : "Unable to load take."} onRetry={() => { void selectedTakeQuery.refetch(); }} />
  ) : null;
  const sourceOptions = takesQuery.data?.available_price_sources || [];
  const selectedPriceSource = resolvePriceSource(requestedPriceSource, sourceOptions);
  const showPriceSourceSelector = shouldShowPriceSourceSelector(sourceOptions);

  useEffect(() => {
    if (!sourceOptions.length) {
      return;
    }
    const normalized = requestedPriceSource?.trim().toLowerCase() || DEFAULT_PRICE_SOURCE;
    if (normalized === selectedPriceSource) {
      return;
    }
    setPriceSource(selectedPriceSource);
  }, [requestedPriceSource, selectedPriceSource, sourceOptions.length]);

  if (validRound && roundQuery.isLoading) {
    return <DrawerSkeleton onClose={onClose} />;
  }

  if (!round) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <header className="drawer-head">
          <span className="text-heading font-medium text-primary">Round detail</span>
          <div className="ml-auto"><ModalCloseButton onClose={onClose} /></div>
        </header>
        <div className="drawer-scroll">
          {!validRound ? <EmptyState title="Invalid round link" /> : roundQuery.isError && !roundNotFound ? (
            <RequestError message="Unable to load round." onRetry={() => { void roundQuery.refetch(); }} />
          ) : <EmptyState title="Round not found" description="This round is absent from the indexed auction." />}
        </div>
      </div>
    );
  }

  const roundPricing = getRoundPricingBySource(round, selectedPriceSource);
  const lotAmount = round.initial_available ?? round.sold_amount;
  const lotUsd = round.kick_market_quote_usd ?? roundPricing.total_market_quote_usd ?? null;
  const receivedUsd = round.total_actual_paid_usd ? formatCompactUsd(round.total_actual_paid_usd) : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="drawer-head">
        <ChainIcon chainId={round.chain_id} />
        <span className="font-mono text-[15px] font-semibold text-primary">R{round.round_id}</span>
        <StatusBadge status={round.status} className="ml-1" />
        <span className="ml-2 hidden min-w-0 items-center gap-1.5 sm:inline-flex">
          <AuctionAddressValue address={round.auction_address} chainId={round.chain_id} showCowExplorerIcon />
          <AuctionVersionBadge version={round.version ?? auctionQuery.data?.version} />
        </span>
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          <ShareButton />
          <ModalCloseButton onClose={onClose} />
        </div>
      </header>

      <div data-round-modal-scroll-root="true" className="drawer-scroll">
        {roundQuery.isError && <RequestError message="Could not refresh round. Showing previously loaded data." onRetry={() => { void roundQuery.refetch(); }} />}
        {auctionQuery.isError && <RequestError message={auctionQuery.data ? "Could not refresh auction. Showing previously loaded data." : "Unable to load auction details."} onRetry={() => { void auctionQuery.refetch(); }} />}
        {auctionQuery.isSuccess && auctionQuery.data === null && <EmptyState title="Auction not found" className="py-4" />}

        <div className="drawer-summary">
          <div className="summary-main" title={[formatFullAmount(lotAmount), round.from_token_symbol].filter(Boolean).join(" ")}>
            <span className="summary-label">Lot</span>
            <span className="summary-figure">
              {formatAmount(lotAmount)}
              <small>{round.from_token_symbol ?? ""}{lotUsd ? ` · ${formatCompactUsd(lotUsd)}` : ""}</small>
            </span>
          </div>
          <SummaryItem label="Sold" title={[formatFullAmount(round.sold_amount), round.from_token_symbol].filter(Boolean).join(" ")}>
            {formatAmount(round.sold_amount)} <span className="text-tertiary">{round.from_token_symbol}</span>
          </SummaryItem>
          <SummaryItem
            label="Received"
            title={`${[formatFullAmount(round.paid_amount), round.want_token_symbol].filter(Boolean).join(" ")}${round.paid_take_count < round.take_count ? ` · payment observed for ${round.paid_take_count} of ${round.take_count} takes` : ""}`}
          >
            <span className="inline-flex items-center gap-1.5">
              <TokenValue
                address={round.want_token}
                symbol={[formatAmount(round.paid_amount), round.want_token_symbol].filter(Boolean).join(" ").trim() || "—"}
                logoUrl={round.want_token_logo_url}
                chainId={round.chain_id}
                showCopy={false}
              />
              {receivedUsd ? <span className="usd-note">{receivedUsd}</span> : null}
            </span>
          </SummaryItem>
          <SummaryItem label="PnL" title={`Quoted for ${roundPricing.priced_take_count ?? 0} of ${round.take_count} takes; USD for ${roundPricing.usd_priced_take_count ?? 0}`}>
            <PnlValue percent={roundPricing.total_auction_profit_bps} usd={roundPricing.total_auction_profit_usd} />
          </SummaryItem>
          <SummaryItem label="Kicked" title={formatDateTime(round.kicked_at)}>
            <button
              type="button"
              className="font-mono underline-offset-4 hover:underline"
              onClick={() => setKickedDisplayMode(toggleKickedDisplayMode)}
            >
              {renderKickedValue(round.kicked_at, kickedDisplayMode)}
            </button>
          </SummaryItem>
        </div>

        <ProgressSection round={round} />

        <DecayChart
          round={round}
          takes={takes}
          livePrice={displayedLivePrice?.current_price ?? null}
          title={<SectionHead aside={<span>{round.want_token_symbol ?? "want"} per {round.from_token_symbol ?? "unit"}</span>}>Price</SectionHead>}
        />

        <section className="sec">
          <SectionHead>Settings</SectionHead>
          <RoundSettingsPanel
            round={round}
            chainId={chain}
            startingPricePerUnit={round.starting_price_per_unit}
            minimumPrice={round.minimum_price}
            duration={round.auction_length}
            stepDuration={round.update_interval}
            decay={round.decay_percent}
            livePrice={displayedLivePrice}
            isLivePriceLoading={livePriceQuery.isLoading}
            isLivePriceError={roundQuery.isError || livePriceQuery.isError || !priceReference}
            livePriceError={livePriceQuery.error}
          />
        </section>

        <section className="sec">
          <SectionHead
            aside={showPriceSourceSelector ? (
              <PriceSourceSelect value={selectedPriceSource} options={sourceOptions} onChange={setPriceSource} />
            ) : <span>{takes.length ? `${takes.length}` : ""}</span>}
          >
            Takes
          </SectionHead>
          {selectedTakeNotice}
          {takesNotFound ? <EmptyState title="Round not found" description="Takes are unavailable for this occurrence." className="py-4" /> : takesQuery.isError ? <RequestError message={takesQuery.data ? "Could not refresh takes. Showing previously loaded data." : "Unable to load takes."} onRetry={() => { void takesQuery.refetch(); }} /> : null}
          {takesQuery.isLoading ? (
            <div className="space-y-3 px-5 py-3">
              {Array.from({ length: 3 }).map((_, index) => <span key={index} className="skeleton-bar w-full" />)}
            </div>
          ) : takesNotFound || (takesQuery.isError && !takesQuery.data) ? null : (
            <RoundTakesTable
              takes={takes}
              priceSource={selectedPriceSource}
              selectedOccurrenceKey={selectedTakeParam}
              selectedTake={selectedTake}
              isSelectedTakeLoading={selectedTakeQuery.isLoading}
              onSelect={(key) => setSelectedTake(selectedTakeParam === key ? undefined : key)}
            />
          )}
        </section>
      </div>
    </div>
  );
}
