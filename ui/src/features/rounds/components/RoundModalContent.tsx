import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { ArrowRight, ChevronDown, Link2, Maximize2, Minimize2, X } from "lucide-react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError } from "../../../shared/api/client";
import {
  cn,
  coerceFiniteNumber,
  formatAddress,
  formatAmount,
  formatDateTime,
  formatFullAmount,
  formatPrice,
  formatSignedPercent,
  formatSignedUsdDelta,
  formatUsd,
  renderKickedValue,
  signedMetricTone,
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
import PriceSourceSelect from "../../../shared/ui/PriceSourceSelect";
import RequestError from "../../../shared/ui/RequestError";
import RoundProgressMini from "../../../shared/ui/RoundProgressMini";
import StatusBadge, { statusLabel } from "../../../shared/ui/StatusBadge";
import TokenLogo from "../../../shared/ui/TokenLogo";
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

/** One figure of the round's result: its label, the figure, and a quieter line beneath. */
function OutcomeCell({
  label,
  title,
  children,
  sub,
  note,
  noteTitle,
}: {
  label: string;
  title?: string;
  children: ReactNode;
  sub?: ReactNode;
  note?: string | null;
  noteTitle?: string;
}) {
  return (
    <div className="outcome-cell" title={title}>
      <dt>{label}</dt>
      <dd className="outcome-figure">{children}</dd>
      <dd className="outcome-sub">
        {sub}
        {note ? <span className={cn("stat-note", !sub && "!ml-0")} title={noteTitle}>{note}</span> : null}
      </dd>
    </div>
  );
}

function SectionHead({ children, note, aside }: { children: ReactNode; note?: ReactNode; aside?: ReactNode }) {
  return (
    <h3 className="sec-head">
      {children}
      {note !== null && note !== undefined && note !== "" ? <span className="sec-note">{note}</span> : null}
      {aside ? <span className="sec-aside">{aside}</span> : null}
    </h3>
  );
}

/**
 * The round's timeline in one line: when it was kicked and how it ended. A
 * live round adds the only meter, since it is the one thing still moving.
 */
function RoundFacts({
  round,
  kickedDisplayMode,
  onToggleKicked,
}: {
  round: RoundListItem;
  kickedDisplayMode: KickedDisplayMode;
  onToggleKicked: () => void;
}) {
  const progress = {
    status: round.status,
    kickedAt: round.kicked_at,
    scheduledEndAt: round.scheduled_end_at,
    endAt: round.end_at,
    availableAmount: round.available_amount,
    initialAvailable: round.initial_available,
    soldAmount: round.sold_amount,
    fromTokenSymbol: round.from_token_symbol,
  };
  const metrics = getRoundProgressMetrics(progress);
  const elapsed = metrics.elapsedDurationLabel;
  const live = round.status === "live";
  const ending = round.status === "sold_out" ? "sold in" : round.status === "expired" ? "expired after" : "settled after";
  const hasInventory = Number(round.initial_available ?? 0) > 0;
  // An expiry that left only dust reads as sold; the share is worth stating once it rounds below 100%.
  const showShare = hasInventory && Math.round(metrics.soldPercent) < 100 && (round.take_count > 0 || !live);

  return (
    <div className="facts">
      <span>
        Kicked{" "}
        <button type="button" className="fact-value underline-offset-4 hover:underline" title={formatDateTime(round.kicked_at)} onClick={onToggleKicked}>
          {renderKickedValue(round.kicked_at, kickedDisplayMode)}
        </button>
      </span>
      {live ? (
        <span title="Time elapsed of the scheduled length"><span className="fact-value">{metrics.timeDetail}</span></span>
      ) : elapsed ? (
        <span>{ending} <span className="fact-value">{elapsed}</span></span>
      ) : (
        <span>{statusLabel(round.status).toLowerCase()}</span>
      )}
      {!showShare ? null : round.take_count === 0 ? (
        <span title={metrics.soldDetail}>nothing sold</span>
      ) : (
        <span title={metrics.soldDetail}><span className="fact-value">{formatPercent(metrics.soldPercent)}</span> of the lot sold</span>
      )}
      {live ? <RoundProgressMini {...progress} takeCount={round.take_count} mode="time" className="ml-auto" /> : null}
    </div>
  );
}

function DrawerSkeleton({ onClose }: { onClose: () => void }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col" aria-busy="true">
      <header className="drawer-head">
        <div className="min-w-0 flex-1">
          <div className="drawer-title">
            <span className="skeleton-bar w-8" />
            <span className="skeleton-bar w-36" />
          </div>
          <div className="drawer-meta"><span className="skeleton-bar w-28" /></div>
        </div>
        <ModalCloseButton onClose={onClose} />
      </header>
      <div className="drawer-scroll">
        <div className="outcome">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="space-y-2.5 py-0.5">
              <span className="skeleton-bar w-10" />
              <span className="skeleton-bar w-24" />
              <span className="skeleton-bar w-14" />
            </div>
          ))}
        </div>
        <div className="facts"><span className="skeleton-bar w-48" /></div>
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
          <div className="drawer-title flex-1">Round detail</div>
          <ModalCloseButton onClose={onClose} />
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
  const fromSymbol = round.from_token_symbol || formatAddress(round.from_token, 6);
  const wantSymbol = round.want_token_symbol || formatAddress(round.want_token, 6);
  const hasTakes = round.take_count > 0;
  // Once something has sold, the first figure is what the result is measured
  // on: the amount sold, valued at the market quote that PnL compares against.
  const offered = hasTakes ? round.sold_amount : round.initial_available ?? round.sold_amount;
  const offeredUsd = hasTakes ? roundPricing.total_market_quote_usd : round.kick_market_quote_usd;
  const pricedTakes = roundPricing.priced_take_count ?? 0;
  const usdPricedTakes = roundPricing.usd_priced_take_count ?? 0;
  const pnlPercent = coerceFiniteNumber(roundPricing.total_auction_profit_bps);
  const pnlUsd = coerceFiniteNumber(roundPricing.total_auction_profit_usd);
  const livePriceUnavailable = roundQuery.isError || livePriceQuery.isError || !priceReference;

  // Absence is only stated once a response has confirmed it, never while loading or failed.
  const takesNote = takesQuery.data && !takesNotFound ? takes.length || (round.status === "live" ? "none yet" : "none") : null;

  const takesSection = (
    <section className="sec" aria-label="Takes">
      <SectionHead
        note={takesNote}
        aside={showPriceSourceSelector ? (
          <PriceSourceSelect quiet value={selectedPriceSource} options={sourceOptions} onChange={setPriceSource} />
        ) : null}
      >
        Takes
      </SectionHead>
      {selectedTakeNotice}
      {takesNotFound ? <EmptyState title="Round not found" description="Takes are unavailable for this occurrence." className="py-4" /> : takesQuery.isError ? <RequestError message={takesQuery.data ? "Could not refresh takes. Showing previously loaded data." : "Unable to load takes."} onRetry={() => { void takesQuery.refetch(); }} /> : null}
      {takesQuery.isLoading ? (
        <div className="space-y-3 px-4 py-3">
          {Array.from({ length: 3 }).map((_, index) => <span key={index} className="skeleton-bar w-full" />)}
        </div>
      ) : takesNotFound || (takesQuery.isError && !takesQuery.data) || !takes.length ? null : (
        <RoundTakesTable
          takes={takes}
          kickedAt={round.kicked_at}
          fromSymbol={fromSymbol}
          wantSymbol={wantSymbol}
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
      unit={`${wantSymbol} per ${fromSymbol}`}
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
        <div className="min-w-0 flex-1">
          <div className="drawer-title">
            <span className="shrink-0 text-tertiary">R{round.round_id}</span>
            <span className="pair" title={`${round.from_token_name ?? fromSymbol} → ${round.want_token_name ?? wantSymbol}`}>
              <TokenLogo logoUrl={round.from_token_logo_url} symbol={fromSymbol} size="md" />
              <span className="truncate">{fromSymbol}</span>
              <ArrowRight className="h-3.5 w-3.5 shrink-0 text-faint" strokeWidth={1.5} aria-hidden="true" />
              <TokenLogo logoUrl={round.want_token_logo_url} symbol={wantSymbol} size="md" />
              <span className="truncate">{wantSymbol}</span>
            </span>
            <StatusBadge status={round.status} className="ml-1 shrink-0" />
          </div>
          <div className="drawer-meta reveal-row">
            <ChainIcon chainId={round.chain_id} size="xs" />
            <AuctionVersionBadge version={round.version ?? auctionQuery.data?.version} />
            <AuctionAddressValue address={round.auction_address} chainId={round.chain_id} showCowExplorerIcon />
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
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

        <dl className={cn("outcome", round.is_active && "is-four")}>
          <OutcomeCell
            label={hasTakes ? "Sold" : "Lot"}
            title={`${formatFullAmount(offered)} ${fromSymbol}${offeredUsd ? ` · ${hasTakes ? "market quote at take time" : "market quote at kick"} ${formatUsd(offeredUsd)}` : ""}`}
            sub={offeredUsd ? formatUsd(offeredUsd) : null}
            note={hasTakes && usdPricedTakes < round.take_count ? "partial" : null}
            noteTitle={`Market value known for ${usdPricedTakes} of ${round.take_count} takes`}
          >
            {formatAmount(offered)} <small>{fromSymbol}</small>
          </OutcomeCell>
          <OutcomeCell
            label="Received"
            title={hasTakes ? `${formatFullAmount(round.paid_amount)} ${wantSymbol}` : undefined}
            sub={round.total_actual_paid_usd ? formatUsd(round.total_actual_paid_usd) : null}
            note={round.paid_take_count < round.take_count ? "partial" : null}
            noteTitle={`Payment observed for ${round.paid_take_count} of ${round.take_count} takes`}
          >
            {hasTakes && round.paid_amount ? <>{formatAmount(round.paid_amount)} <small>{wantSymbol}</small></> : <span className="text-faint">—</span>}
          </OutcomeCell>
          <OutcomeCell
            label="PnL"
            title={hasTakes ? `Against the market quote. Quoted for ${pricedTakes} of ${round.take_count} takes; USD for ${usdPricedTakes}` : undefined}
            sub={pnlUsd !== null ? formatSignedUsdDelta(pnlUsd) : null}
            note={hasTakes && pnlPercent !== null && pricedTakes < round.take_count ? "partial" : null}
            noteTitle={`Quoted for ${pricedTakes} of ${round.take_count} takes`}
          >
            {pnlPercent !== null || pnlUsd !== null ? (
              <span className={signedMetricTone(pnlPercent ?? pnlUsd)}>{formatSignedPercent(pnlPercent)}</span>
            ) : <span className="text-faint">—</span>}
          </OutcomeCell>
          {round.is_active ? (
            <OutcomeCell
              label="Price now"
              title={displayedLivePrice ? `${wantSymbol} per ${fromSymbol} at indexed block ${displayedLivePrice.indexed_block}` : undefined}
              sub={round.expected_price_per_unit ? `quote ${formatPrice(round.expected_price_per_unit, 8)}` : null}
            >
              {displayedLivePrice?.current_price ? formatPrice(displayedLivePrice.current_price, 8) : (
                <span className="text-faint">{livePriceUnavailable ? "unavailable" : "—"}</span>
              )}
            </OutcomeCell>
          ) : null}
        </dl>

        <RoundFacts round={round} kickedDisplayMode={kickedDisplayMode} onToggleKicked={() => setKickedDisplayMode(toggleKickedDisplayMode)} />

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
