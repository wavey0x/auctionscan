import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { ArrowRight, ChevronRight, Link2, Maximize2, Minimize2, X } from "lucide-react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";

import { ApiError } from "../../../shared/api/client";
import {
  cn,
  coerceFiniteNumber,
  formatAddress,
  formatAmount,
  formatDateTime,
  formatDuration,
  formatFullAmount,
  formatPrice,
  formatPriceSignificant,
  formatSignedPercent,
  formatSignedUsdDelta,
  formatUsd,
  renderKickedValue,
  signedMetricTone,
  toggleKickedDisplayMode,
} from "../../../shared/lib/format";
import type { KickedDisplayMode } from "../../../shared/lib/format";
import { useDenomination } from "../../../shared/lib/denomination";
import { DEFAULT_PRICE_SOURCE, getRoundPricingBySource, resolvePriceSource, shouldShowPriceSourceSelector } from "../../../shared/lib/pricingSource";
import { getRoundProgressMetrics, getSaleOutcome } from "../../../shared/lib/roundProgress";
import { useChainsQuery } from "../../../shared/lib/chains";
import { buildRoundPath, parseOccurrence, parseRoundId } from "../../../shared/lib/routes";
import type { RoundListItem } from "../../../shared/types/api";
import AuctionAddressValue from "../../../shared/ui/AuctionAddressValue";
import ChainIcon from "../../../shared/ui/ChainIcon";
import EmptyState from "../../../shared/ui/EmptyState";
import PriceSourceSelect from "../../../shared/ui/PriceSourceSelect";
import RequestError from "../../../shared/ui/RequestError";
import StatusBadge from "../../../shared/ui/StatusBadge";
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

/**
 * One figure of a round: its label and the figure. A cell that passes `sub`
 * keeps a quieter line beneath for context the figure cannot carry; a cell
 * that passes `onToggle` gives its figure once, in tokens or in dollars, and
 * clicking it switches every such figure in the round.
 */
function OutcomeCell({
  label,
  title,
  children,
  sub,
  note,
  noteTitle,
  onToggle,
}: {
  label: string;
  title?: string;
  children: ReactNode;
  sub?: ReactNode;
  note?: string | null;
  noteTitle?: string;
  onToggle?: () => void;
}) {
  const noteMark = note ? <span className="stat-note" title={noteTitle}>{note}</span> : null;
  return (
    <div className="outcome-cell" title={title}>
      <dt>{label}</dt>
      <dd className="outcome-figure">
        {onToggle ? <button type="button" className="figure-toggle" onClick={onToggle}>{children}</button> : children}
        {sub === undefined ? noteMark : null}
      </dd>
      {sub === undefined ? null : (
        <dd className="outcome-sub">
          {sub}
          {note ? <span className={cn("stat-note", !sub && "!ml-0")} title={noteTitle}>{note}</span> : null}
        </dd>
      )}
    </div>
  );
}

const dash = <span className="text-faint">—</span>;

function SectionHead({ children, note, aside }: { children: ReactNode; note?: ReactNode; aside?: ReactNode }) {
  return (
    <h3 className="sec-head">
      {children}
      {note !== null && note !== undefined && note !== "" ? <span className="sec-note">{note}</span> : null}
      {aside ? <span className="sec-aside">{aside}</span> : null}
    </h3>
  );
}

function progressInput(round: RoundListItem) {
  return {
    status: round.status,
    kickedAt: round.kicked_at,
    scheduledEndAt: round.scheduled_end_at,
    endAt: round.end_at,
    availableAmount: round.available_amount,
    initialAvailable: round.initial_available,
    soldAmount: round.sold_amount,
    fromTokenSymbol: round.from_token_symbol,
  };
}

/**
 * A finished round's timeline in bare figures: when it was kicked and how long
 * it ran. The head already says how it ended, so the line names neither; the
 * words are on hover. If the lot did not clear it adds what was left, because
 * an expiry is a fact about time, not about sales.
 */
function RoundFacts({
  round,
  fromSymbol,
  kickedDisplayMode,
  onToggleKicked,
}: {
  round: RoundListItem;
  fromSymbol: string;
  kickedDisplayMode: KickedDisplayMode;
  onToggleKicked: () => void;
}) {
  const metrics = getRoundProgressMetrics(progressInput(round));
  const elapsed = metrics.elapsedDurationLabel;
  const ending = round.status === "sold_out" ? "Sold in" : round.status === "expired" ? "Expired after" : "Settled after";
  const outcome = getSaleOutcome(round);
  const leftTitle = `${metrics.soldDetail} · ${formatFullAmount(round.available_amount)} ${fromSymbol} left`;

  return (
    <div className="facts">
      <span>
        <button type="button" className="fact-value underline-offset-4 hover:underline" title={`Kicked ${formatDateTime(round.kicked_at)}`} onClick={onToggleKicked}>
          {renderKickedValue(round.kicked_at, kickedDisplayMode)}
        </button>
      </span>
      {elapsed ? <span className="fact-value" title={`${ending} ${elapsed}`}>{elapsed}</span> : null}
      {outcome?.kind === "none" ? (
        <span>nothing sold</span>
      ) : outcome?.kind === "dust" ? (
        <span title={leftTitle}>all but dust sold</span>
      ) : outcome?.kind === "partial" ? (
        <>
          <span title={leftTitle}><span className="fact-value">{outcome.percent}%</span> sold</span>
          <span title={leftTitle}><span className="fact-value">{formatAmount(round.available_amount)} {fromSymbol}</span> left</span>
        </>
      ) : null}
    </div>
  );
}

/** Where the live price stands against the kick-time market quote it is decaying toward. */
function versusQuote(price: string | null | undefined, quote: string | null | undefined): string | null {
  const current = coerceFiniteNumber(price);
  const reference = coerceFiniteNumber(quote);
  if (current === null || reference === null || current <= 0 || reference <= 0) return null;
  const ratio = current / reference;
  if (ratio >= 2) return `${ratio >= 100 ? Math.round(ratio).toLocaleString("en-US") : ratio.toFixed(1)}× quote`;
  return `${formatSignedPercent((ratio - 1) * 100, 1)} vs quote`;
}

/**
 * What a round still running is worth watching for: what is left to sell, what
 * it costs right now against the quote, and how long it has. The cells have
 * the same shape as the result row: a bare figure over one short line. The
 * head names the tokens and the chart beneath marks the time, so neither a
 * unit nor a meter is repeated here.
 */
function LiveRow({
  round,
  fromSymbol,
  wantSymbol,
  price,
  priceBlock,
  pricePending,
}: {
  round: RoundListItem;
  fromSymbol: string;
  wantSymbol: string;
  price?: string | null;
  priceBlock?: number | null;
  pricePending: boolean;
}) {
  const metrics = getRoundProgressMetrics(progressInput(round));
  const remaining = round.available_amount ?? round.initial_available ?? null;
  const scheduled = metrics.scheduledDurationSeconds;
  const left = scheduled !== null && metrics.elapsedSeconds !== null ? scheduled - metrics.elapsedSeconds : null;
  const against = versusQuote(price, round.expected_price_per_unit);
  const quote = round.expected_price_per_unit ? formatPrice(round.expected_price_per_unit, 8) : null;

  return (
    <dl className="outcome outcome-end">
      <OutcomeCell
        label="Remaining"
        title={remaining === null ? undefined : `${formatFullAmount(remaining)} ${fromSymbol} left · ${metrics.soldDetail}`}
        sub={round.take_count > 0
          ? `${Math.floor(metrics.soldPercent)}% of ${formatAmount(round.initial_available)} sold`
          : round.kick_market_quote_usd ? formatUsd(round.kick_market_quote_usd) : null}
      >
        {remaining === null ? <span className="text-faint">—</span> : formatAmount(remaining)}
      </OutcomeCell>
      <OutcomeCell
        label="Price now"
        title={[
          price && priceBlock ? `${formatPrice(price, 8)} ${wantSymbol} per ${fromSymbol} at indexed block ${priceBlock}` : null,
          quote ? `Market quote at kick ${quote}` : null,
        ].filter(Boolean).join(" · ") || undefined}
        sub={against ?? (quote ? `quote ${quote}` : null)}
      >
        {price ? formatPriceSignificant(price) : pricePending ? (
          <span className="skeleton-bar my-[6.5px] w-20" aria-label="Loading price" />
        ) : (
          <span className="text-faint">—</span>
        )}
      </OutcomeCell>
      <OutcomeCell
        label="Time left"
        title={`Kicked ${formatDateTime(round.kicked_at)} · ${metrics.timeDetail}`}
        sub={scheduled === null ? null : `of ${formatDuration(scheduled)}`}
      >
        {left === null ? <span className="text-faint">—</span> : left > 0 ? formatDuration(left) : "ending"}
      </OutcomeCell>
    </dl>
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
  const [denomination, toggleDenomination] = useDenomination();
  const inUsd = denomination === "usd";

  const chain = Number(chainId);
  // The chain is worth a mark only once there is more than one to tell apart.
  const multiChain = Object.keys(useChainsQuery().data?.chains ?? {}).length > 1;
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
  ) : selectedTakeQuery.isError && !selectedTake ? (
    <RequestError message="Unable to load take." onRetry={() => { void selectedTakeQuery.refetch(); }} />
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
  const live = round.status === "live";
  // Once something has sold, the first figure is what the result is measured
  // on: the amount sold, valued at the market quote that PnL compares against.
  const offered = hasTakes ? round.sold_amount : round.initial_available ?? round.sold_amount;
  const offeredUsd = hasTakes ? roundPricing.total_market_quote_usd : round.kick_market_quote_usd;
  const pricedTakes = roundPricing.priced_take_count ?? 0;
  const usdPricedTakes = roundPricing.usd_priced_take_count ?? 0;
  const pnlPercent = coerceFiniteNumber(roundPricing.total_auction_profit_bps);
  const pnlUsd = coerceFiniteNumber(roundPricing.total_auction_profit_usd);

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
      {takesNotFound ? <EmptyState title="Round not found" description="Takes are unavailable for this occurrence." className="py-4" /> : takesQuery.isError && !takesQuery.data ? <RequestError message="Unable to load takes." onRetry={() => { void takesQuery.refetch(); }} /> : null}
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
          denomination={denomination}
          onToggleDenomination={toggleDenomination}
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
      height={wide ? 120 : 80}
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
      version={round.version ?? auctionQuery.data?.version}
    />
  );

  // What the round achieved. A cell exists only once there is something to put
  // in it: a live round shows this row after its first take, and a round that
  // ended without one shows the lot alone. Each figure is given once, in the
  // round's tokens or in dollars; clicking one switches them all.
  const switchHint = inUsd ? "Click for token amounts" : "Click for dollar values";
  const paidUsd = round.total_actual_paid_usd;
  const paidCount = inUsd ? round.paid_usd_take_count : round.paid_take_count;
  const pnlCount = inUsd ? usdPricedTakes : pricedTakes;
  const pnlFigure = inUsd ? pnlUsd : pnlPercent;
  const resultRow = !hasTakes && live ? null : (
    <dl className={cn("outcome", live && "outcome-ruled outcome-end")}>
      <OutcomeCell
        label={hasTakes ? "Sold" : "Lot"}
        title={`${formatFullAmount(offered)} ${fromSymbol}${offeredUsd ? ` · ${hasTakes ? "market quote at take time" : "market quote at kick"} ${formatUsd(offeredUsd)}` : ""}\n${switchHint}`}
        note={inUsd && offeredUsd && hasTakes && usdPricedTakes < round.take_count ? "partial" : null}
        noteTitle={`Market value known for ${usdPricedTakes} of ${round.take_count} takes`}
        onToggle={toggleDenomination}
      >
        {inUsd ? (offeredUsd ? formatUsd(offeredUsd) : dash) : formatAmount(offered)}
      </OutcomeCell>
      {hasTakes ? (
        <>
          <OutcomeCell
            label="Received"
            title={`${formatFullAmount(round.paid_amount)} ${wantSymbol}${paidUsd ? ` · ${formatUsd(paidUsd)}` : ""}\n${switchHint}`}
            note={(inUsd ? paidUsd : round.paid_amount) && paidCount < round.take_count ? "partial" : null}
            noteTitle={`${inUsd ? "Dollar value known" : "Payment observed"} for ${paidCount} of ${round.take_count} takes`}
            onToggle={toggleDenomination}
          >
            {inUsd ? (paidUsd ? formatUsd(paidUsd) : dash) : (round.paid_amount ? formatAmount(round.paid_amount) : dash)}
          </OutcomeCell>
          <OutcomeCell
            label="PnL"
            title={`Against the market quote. Quoted for ${pricedTakes} of ${round.take_count} takes; USD for ${usdPricedTakes}\n${inUsd ? "Click for percent" : "Click for dollar values"}`}
            note={pnlFigure !== null && pnlCount < round.take_count ? "partial" : null}
            noteTitle={`${inUsd ? "Priced in dollars" : "Quoted"} for ${pnlCount} of ${round.take_count} takes`}
            onToggle={toggleDenomination}
          >
            {pnlFigure === null ? dash : (
              <span className={signedMetricTone(pnlFigure)}>{inUsd ? formatSignedUsdDelta(pnlFigure) : formatSignedPercent(pnlFigure)}</span>
            )}
          </OutcomeCell>
        </>
      ) : null}
    </dl>
  );

  // While a round is live its price path leads; once it has ended, the takes do.
  const pricePanel = wide ? (
    <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,22rem)] border-t border-divider-subtle">
      <div className="min-w-0 [&>.sec]:border-t-0">{chart}</div>
      <section className="sec min-w-0 border-l border-t-0 border-divider-subtle">
        <SectionHead>Details</SectionHead>
        {settings}
      </section>
    </div>
  ) : chart;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="drawer-head">
        <div className="min-w-0 flex-1">
          {/* The pair has the line to itself, so both tokens keep their logo and their whole name. */}
          <div className="drawer-title" title={`${round.from_token_name ?? fromSymbol} → ${round.want_token_name ?? wantSymbol}`}>
            {/* The arrow stays with what was sold, so when a narrow sheet breaks the pair the two logos stack on one edge. */}
            <span className="token">
              <TokenLogo logoUrl={round.from_token_logo_url} symbol={fromSymbol} size="md" />
              <span className="truncate">{fromSymbol}</span>
              <ArrowRight className="h-3.5 w-3.5 shrink-0 text-faint" strokeWidth={1.5} aria-hidden="true" />
            </span>
            <span className="token is-want">
              <TokenLogo logoUrl={round.want_token_logo_url} symbol={wantSymbol} size="md" />
              <span className="truncate">{wantSymbol}</span>
            </span>
          </div>
          {/* Its state, which round, and where it lives. The address reveals its utilities when pointed at. */}
          <div className="drawer-meta">
            <StatusBadge status={round.status} />
            <span className="meta-item text-secondary">R{round.round_id}</span>
            <span className="meta-item reveal-row">
              {multiChain ? <ChainIcon chainId={round.chain_id} size="xs" /> : null}
              <AuctionAddressValue address={round.auction_address} chainId={round.chain_id} showCowExplorerIcon />
            </span>
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
        {auctionQuery.isError && !auctionQuery.data && <RequestError message="Unable to load auction details." onRetry={() => { void auctionQuery.refetch(); }} />}
        {auctionQuery.isSuccess && auctionQuery.data === null && <EmptyState title="Auction not found" className="py-4" />}

        {live ? (
          <>
            <LiveRow
              round={round}
              fromSymbol={fromSymbol}
              wantSymbol={wantSymbol}
              price={displayedLivePrice?.current_price}
              priceBlock={displayedLivePrice?.indexed_block}
              pricePending={livePriceQuery.isLoading}
            />
            {pricePanel}
          </>
        ) : null}

        {resultRow}
        {live ? null : (
          <RoundFacts
            round={round}
            fromSymbol={fromSymbol}
            kickedDisplayMode={kickedDisplayMode}
            onToggleKicked={() => setKickedDisplayMode(toggleKickedDisplayMode)}
          />
        )}

        {takesSection}

        {live ? null : pricePanel}
        {wide ? null : (
          <details className="sec" open={settingsOpen} onToggle={(event) => setSettingsOpen(event.currentTarget.open)}>
            <summary>
              {/* The same mark a row that opens in place ends in, beside the word it belongs to. */}
              <SectionHead>
                Details
                <ChevronRight className={cn("h-3.5 w-3.5 transition-transform", settingsOpen && "rotate-90")} strokeWidth={1.6} aria-hidden="true" />
              </SectionHead>
            </summary>
            {settings}
          </details>
        )}
      </div>
    </div>
  );
}
