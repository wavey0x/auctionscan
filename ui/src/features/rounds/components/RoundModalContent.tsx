import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { ChevronDown, Link2, Maximize2, Minimize2, X } from "lucide-react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError } from "../../../shared/api/client";
import {
  cn,
  formatAmount,
  formatCompactUsd,
  formatDateTime,
  formatFullAmount,
  formatPrice,
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
      <dd className="truncate">{children}</dd>
    </dl>
  );
}

function SectionHead({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <h3 className="sec-head">
      {children}
      {aside ? <span className="sec-aside">{aside}</span> : null}
    </h3>
  );
}

function ProgressRow({ round }: { round: RoundListItem }) {
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
    showFigure: false,
    className: "w-full [&_.bar]:!w-full",
  };
  return (
    <div className="grid grid-cols-2 gap-x-5 px-4 pb-3">
      <div className="min-w-0" title={metrics.timeDetail}>
        <div className="mb-1.5 flex items-baseline justify-between gap-2">
          <span className="label">Time</span>
          <span className="truncate text-[11px] text-tertiary">{formatPercent(metrics.timePercent)} · {metrics.timeDetail}</span>
        </div>
        <RoundProgressMini {...common} mode="time" />
      </div>
      <div className="min-w-0" title={metrics.soldDetail}>
        <div className="mb-1.5 flex items-baseline justify-between gap-2">
          <span className="label">Sold</span>
          <span className="truncate text-[11px] text-tertiary">{formatPercent(metrics.soldPercent)}</span>
        </div>
        <RoundProgressMini {...common} mode="take" />
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
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="space-y-2">
              <span className="skeleton-bar w-10" />
              <span className="skeleton-bar w-20" />
            </div>
          ))}
        </div>
        <div className="space-y-4 border-t border-divider-subtle px-4 pt-4">
          <span className="skeleton-bar w-14" />
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="flex gap-6">
              <span className="skeleton-bar w-8" />
              <span className="skeleton-bar w-24" />
              <span className="skeleton-bar ml-auto w-16" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function RoundModalContent({
  onClose,
  wide = false,
  onToggleWide,
}: {
  onClose: () => void;
  wide?: boolean;
  onToggleWide?: () => void;
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
  const [settingsOpen, setSettingsOpen] = useState(false);

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

  const takesSection = (
    <section className="sec" aria-label="Takes">
      <SectionHead
        aside={showPriceSourceSelector ? (
          <PriceSourceSelect value={selectedPriceSource} options={sourceOptions} onChange={setPriceSource} />
        ) : takes.length ? `${takes.length}` : null}
      >
        Takes
      </SectionHead>
      {selectedTakeNotice}
      {takesNotFound ? <EmptyState title="Round not found" description="Takes are unavailable for this occurrence." className="py-4" /> : takesQuery.isError ? <RequestError message={takesQuery.data ? "Could not refresh takes. Showing previously loaded data." : "Unable to load takes."} onRetry={() => { void takesQuery.refetch(); }} /> : null}
      {takesQuery.isLoading ? (
        <div className="space-y-3 px-4 py-3">
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
  );

  const chart = (
    <DecayChart
      round={round}
      takes={takes}
      height={wide ? 132 : 92}
      livePrice={displayedLivePrice?.current_price ?? null}
      title={<SectionHead aside={`${round.want_token_symbol ?? "want"} per ${round.from_token_symbol ?? "unit"}`}>Price</SectionHead>}
    />
  );

  const settings = (
    <RoundSettingsPanel
      round={round}
      chainId={chain}
      startingPricePerUnit={round.starting_price_per_unit}
      minimumPrice={round.minimum_price}
      duration={round.auction_length}
      stepDuration={round.update_interval}
      decay={round.decay_percent}
    />
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="drawer-head">
        <ChainIcon chainId={round.chain_id} />
        <span className="text-heading text-primary">R{round.round_id}</span>
        <StatusBadge status={round.status} className="ml-1" />
        <span className="ml-3 hidden min-w-0 items-center gap-1.5 sm:inline-flex">
          <AuctionAddressValue address={round.auction_address} chainId={round.chain_id} showCowExplorerIcon />
          <AuctionVersionBadge version={round.version ?? auctionQuery.data?.version} />
        </span>
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          {onToggleWide ? (
            <span className="wide-toggle">
              <IconButton label={wide ? "Narrow the round workspace" : "Expand the round workspace"} onClick={onToggleWide}>
                {wide ? <Minimize2 className="h-3.5 w-3.5" strokeWidth={1.6} /> : <Maximize2 className="h-3.5 w-3.5" strokeWidth={1.6} />}
              </IconButton>
            </span>
          ) : null}
          <ShareButton />
          <ModalCloseButton onClose={onClose} />
        </div>
      </header>

      <div data-round-modal-scroll-root="true" className="drawer-scroll">
        {roundQuery.isError && <RequestError message="Could not refresh round. Showing previously loaded data." onRetry={() => { void roundQuery.refetch(); }} />}
        {auctionQuery.isError && <RequestError message={auctionQuery.data ? "Could not refresh auction. Showing previously loaded data." : "Unable to load auction details."} onRetry={() => { void auctionQuery.refetch(); }} />}
        {auctionQuery.isSuccess && auctionQuery.data === null && <EmptyState title="Auction not found" className="py-4" />}

        <div className="drawer-summary">
          <SummaryItem label="Lot" title={[formatFullAmount(lotAmount), round.from_token_symbol].filter(Boolean).join(" ")}>
            {formatAmount(lotAmount)} <span className="text-tertiary">{round.from_token_symbol}</span>
            {lotUsd ? <span className="usd-note ml-1.5">{formatCompactUsd(lotUsd)}</span> : null}
          </SummaryItem>
          <SummaryItem
            label="Received"
            title={`${[formatFullAmount(round.paid_amount), round.want_token_symbol].filter(Boolean).join(" ")}${round.paid_take_count < round.take_count ? ` · payment observed for ${round.paid_take_count} of ${round.take_count} takes` : ""}`}
          >
            <span className="inline-flex max-w-full items-center gap-1.5">
              <TokenValue
                address={round.want_token}
                symbol={[formatAmount(round.paid_amount), round.want_token_symbol].filter(Boolean).join(" ").trim() || "—"}
                logoUrl={round.want_token_logo_url}
                chainId={round.chain_id}
                showCopy={false}
              />
              {receivedUsd ? <span className="usd-note shrink-0">{receivedUsd}</span> : null}
            </span>
          </SummaryItem>
          <SummaryItem label="PnL" title={`Quoted for ${roundPricing.priced_take_count ?? 0} of ${round.take_count} takes; USD for ${roundPricing.usd_priced_take_count ?? 0}`}>
            <PnlValue percent={roundPricing.total_auction_profit_bps} usd={roundPricing.total_auction_profit_usd} />
          </SummaryItem>
          {round.is_active ? (
            <SummaryItem label="Price now" title={displayedLivePrice ? `At indexed block ${displayedLivePrice.indexed_block}` : undefined}>
              {displayedLivePrice?.current_price ? formatPrice(displayedLivePrice.current_price, 8) : (
                <span className="text-tertiary">{roundQuery.isError || livePriceQuery.isError || !priceReference ? "unavailable" : "—"}</span>
              )}
            </SummaryItem>
          ) : round.take_count > 0 ? (
            <SummaryItem label="Execution" title={`Average execution price from ${round.paid_take_count}/${round.take_count} takes with observed payment`}>
              {round.avg_execution_price ? formatPrice(round.avg_execution_price, 8) : <span className="text-faint">—</span>}
            </SummaryItem>
          ) : null}
          <SummaryItem label="Kicked" title={formatDateTime(round.kicked_at)}>
            <button
              type="button"
              className="underline-offset-4 hover:underline"
              onClick={() => setKickedDisplayMode(toggleKickedDisplayMode)}
            >
              {renderKickedValue(round.kicked_at, kickedDisplayMode)}
            </button>
          </SummaryItem>
        </div>

        <ProgressRow round={round} />

        {takesSection}

        {wide ? (
          <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,22rem)] border-t border-divider-subtle">
            <div className="min-w-0 [&>.sec]:border-t-0">{chart}</div>
            <section className="sec min-w-0 border-l border-t-0 border-divider-subtle">
              <SectionHead>Settings</SectionHead>
              {settings}
            </section>
          </div>
        ) : (
          <>
            {chart}
            <details className="sec" open={settingsOpen} onToggle={(event) => setSettingsOpen(event.currentTarget.open)}>
              <summary>
                <SectionHead aside={<ChevronDown className={cn("h-3.5 w-3.5 text-faint transition-transform", settingsOpen && "rotate-180")} strokeWidth={1.6} />}>
                  Settings
                </SectionHead>
              </summary>
              {settings}
            </details>
          </>
        )}
      </div>
    </div>
  );
}
