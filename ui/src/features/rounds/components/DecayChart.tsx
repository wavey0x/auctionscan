import { useEffect, useMemo, useRef, useState, type PointerEvent, type ReactNode } from "react";

import { formatCompactDateTime, formatDuration, formatPrice, parseTimestamp } from "../../../shared/lib/format";
import type { RoundListItem, TakeListItem } from "../../../shared/types/api";

const DEFAULT_HEIGHT = 112;
const PAD_TOP = 8;
const PAD_BOTTOM = 18;
const MAX_STEPS_DRAWN = 720;

function seconds(value: string | null | undefined): number | null {
  const date = parseTimestamp(value);
  return date ? Math.floor(date.getTime() / 1000) : null;
}

function positive(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
}

function parseDecay(value: string | null | undefined): number | null {
  if (!value) return null;
  const numeric = Number.parseFloat(value.replace("%", ""));
  return Number.isFinite(numeric) && numeric > 0 && numeric < 100 ? numeric / 100 : null;
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return undefined;
    setWidth(element.getBoundingClientRect().width);
    if (typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver((entries) => setWidth(entries[0]?.contentRect.width ?? 0));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

interface Model {
  kick: number;
  end: number;
  now: number | null;
  step: number;
  decay: number;
  start: number;
  minimum: number | null;
  quote: number | null;
  low: number;
  high: number;
  takes: Array<{ t: number; price: number; key: string }>;
  priceAt: (t: number) => number | null;
}

function buildModel(round: RoundListItem, takes: TakeListItem[]): Model | null {
  const kick = seconds(round.kicked_at);
  const start = positive(round.starting_price_per_unit);
  const decay = parseDecay(round.decay_percent);
  const step = round.update_interval && round.update_interval > 0 ? round.update_interval : null;
  if (kick === null || start === null || decay === null || step === null) return null;

  const scheduledEnd = seconds(round.scheduled_end_at) ?? (round.auction_length ? kick + round.auction_length : null);
  if (scheduledEnd === null || scheduledEnd <= kick) return null;
  const nowSec = Math.floor(Date.now() / 1000);
  const minimum = positive(round.minimum_price);
  const quote = positive(round.expected_price_per_unit);
  const takePoints = takes
    .map((take) => ({ t: seconds(take.timestamp), price: positive(take.price), key: `${take.tx_hash}:${take.take_seq}` }))
    .filter((point): point is { t: number; price: number; key: string } => point.t !== null && point.price !== null);

  let end = scheduledEnd;
  if (round.status !== "live") {
    const closed = seconds(round.end_at) ?? scheduledEnd;
    const lastTake = takePoints.reduce((latest, point) => Math.max(latest, point.t), kick);
    const activeUntil = Math.max(closed, lastTake);
    // A round that closed early is drawn to its close, with room either side.
    end = Math.min(scheduledEnd, Math.max(activeUntil + (activeUntil - kick) * 0.15, kick + step * 8));
  }

  const priceAt = (t: number) => {
    if (t < kick) return null;
    const price = start * (1 - decay) ** Math.floor((t - kick) / step);
    return minimum !== null && price < minimum ? null : price;
  };

  const endPrice = start * (1 - decay) ** Math.floor((end - kick) / step);
  const candidates = [endPrice, ...takePoints.map((point) => point.price)];
  if (quote !== null) candidates.push(quote);
  if (minimum !== null && minimum > endPrice * 0.5) candidates.push(minimum);
  const low = Math.min(...candidates) * 0.94;
  const high = Math.max(start, ...takePoints.map((point) => point.price)) * 1.03;

  return {
    kick,
    end,
    now: round.status === "live" ? Math.min(Math.max(nowSec, kick), end) : null,
    step,
    decay,
    start,
    minimum,
    quote,
    low,
    high,
    takes: takePoints,
    priceAt,
  };
}

/**
 * The round's price path: the start price stepping down by its decay, the
 * kick-time market quote it should meet, and where each take landed on it.
 */
export default function DecayChart({
  round,
  takes,
  livePrice,
  title,
  height = DEFAULT_HEIGHT,
}: {
  round: RoundListItem;
  takes: TakeListItem[];
  livePrice?: string | null;
  title?: ReactNode;
  height?: number;
}) {
  const model = useMemo(() => buildModel(round, takes), [round, takes]);
  if (!model) {
    return null;
  }
  return (
    <section className="sec">
      {title}
      <DecayPlot model={model} round={round} livePrice={livePrice} height={height} />
    </section>
  );
}

function DecayPlot({
  model,
  round,
  livePrice,
  height: HEIGHT,
}: {
  model: Model;
  round: RoundListItem;
  livePrice?: string | null;
  height: number;
}) {
  const { ref, width } = useWidth<HTMLDivElement>();
  const [hoverT, setHoverT] = useState<number | null>(null);

  const plotWidth = Math.max(width, 1);
  const plotHeight = HEIGHT - PAD_TOP - PAD_BOTTOM;
  const x = (t: number) => ((t - model.kick) / (model.end - model.kick)) * plotWidth;
  const y = (price: number) => PAD_TOP + (1 - (price - model.low) / (model.high - model.low)) * plotHeight;

  const totalSteps = Math.floor((model.end - model.kick) / model.step);
  let line = "";
  if (totalSteps <= MAX_STEPS_DRAWN) {
    for (let i = 0; i <= totalSteps; i += 1) {
      const t = model.kick + i * model.step;
      const price = model.priceAt(t);
      if (price === null) break;
      const nextT = Math.min(t + model.step, model.end);
      line += i === 0 ? `M${x(t).toFixed(2)},${y(price).toFixed(2)}` : `V${y(price).toFixed(2)}`;
      line += `H${x(nextT).toFixed(2)}`;
    }
  } else {
    const samples = Math.max(2, Math.floor(plotWidth));
    for (let i = 0; i <= samples; i += 1) {
      const t = model.kick + ((model.end - model.kick) * i) / samples;
      const price = model.priceAt(t);
      if (price === null) break;
      line += `${i === 0 ? "M" : "L"}${x(t).toFixed(2)},${y(price).toFixed(2)}`;
    }
  }
  const area = line ? `${line}V${PAD_TOP + plotHeight}H0Z` : "";

  const live = positive(livePrice);
  const hoverPrice = hoverT !== null ? model.priceAt(hoverT) : null;
  const marker = hoverT !== null && hoverPrice !== null
    ? { t: hoverT, price: hoverPrice }
    : model.now !== null
      ? { t: model.now, price: live ?? model.priceAt(model.now) }
      : null;

  const onPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(Math.max((event.clientX - bounds.left) / bounds.width, 0), 1);
    setHoverT(model.kick + ratio * (model.end - model.kick));
  };

  return (
    <div className="chart" ref={ref}>
      <div className="chart-key">
        <span><i className="key-line" />Start <b>{formatPrice(model.start, 8)}</b></span>
        {model.quote !== null ? <span><i className="key-dash" />Kick quote <b>{formatPrice(model.quote, 8)}</b></span> : null}
        {model.takes.length ? <span><i className="key-dot" />{model.takes.length === 1 ? "Take" : `${model.takes.length} takes`}</span> : null}
        {hoverT !== null && hoverPrice !== null ? (
          <span className="ml-auto">+{formatDuration(Math.max(0, Math.round(hoverT - model.kick)))} <b>{formatPrice(hoverPrice, 8)}</b></span>
        ) : model.now !== null && marker?.price ? (
          <span className="ml-auto">Now <b>{formatPrice(marker.price, 8)}</b></span>
        ) : null}
      </div>
      {width > 0 ? (
        <svg
          width={plotWidth}
          height={HEIGHT}
          viewBox={`0 0 ${plotWidth} ${HEIGHT}`}
          role="img"
          aria-label={`Price from ${formatPrice(model.start, 8)} decaying ${round.decay_percent ?? ""} every ${formatDuration(model.step)}`}
          className="mt-1.5 cursor-crosshair touch-pan-y"
          onPointerMove={onPointerMove}
          onPointerLeave={() => setHoverT(null)}
        >
          <line x1={0} x2={plotWidth} y1={PAD_TOP + plotHeight} y2={PAD_TOP + plotHeight} stroke="var(--color-divider)" />
          {area ? <path d={area} fill="color-mix(in srgb, var(--color-primary) 6%, transparent)" /> : null}
          {model.minimum !== null && model.minimum > model.low ? (
            <line x1={0} x2={plotWidth} y1={y(model.minimum)} y2={y(model.minimum)} stroke="var(--color-faint)" strokeDasharray="2 4" />
          ) : null}
          {model.quote !== null ? (
            <line x1={0} x2={plotWidth} y1={y(model.quote)} y2={y(model.quote)} stroke="var(--color-tertiary)" strokeDasharray="3 3" />
          ) : null}
          {line ? <path d={line} fill="none" stroke="var(--color-primary)" strokeWidth={1.5} strokeLinejoin="round" /> : null}
          {marker && marker.price !== null ? (
            <g>
              <line x1={x(marker.t)} x2={x(marker.t)} y1={PAD_TOP} y2={PAD_TOP + plotHeight} stroke="var(--color-divider-strong)" />
              <circle
                cx={x(marker.t)}
                cy={y(marker.price)}
                r={4}
                fill={hoverT === null ? "var(--color-active-mark)" : "var(--color-primary)"}
                stroke="var(--color-surface)"
                strokeWidth={2}
              />
            </g>
          ) : null}
          {model.takes.map((point) => (
            <circle key={point.key} cx={x(point.t)} cy={y(point.price)} r={3.5} fill="var(--color-accent)" stroke="var(--color-surface)" strokeWidth={2}>
              <title>{`Take at ${formatCompactDateTime(new Date(point.t * 1000))}: ${formatPrice(point.price, 8)}`}</title>
            </circle>
          ))}
          <text x={0} y={HEIGHT - 4} fill="var(--color-faint)" fontSize={11} fontFamily="var(--font-mono)">
            {formatCompactDateTime(new Date(model.kick * 1000))}
          </text>
          <text x={plotWidth} y={HEIGHT - 4} fill="var(--color-faint)" fontSize={11} fontFamily="var(--font-mono)" textAnchor="end">
            {model.now !== null ? `ends ${formatCompactDateTime(new Date(model.end * 1000))}` : formatCompactDateTime(new Date(model.end * 1000))}
          </text>
        </svg>
      ) : (
        <div style={{ height: HEIGHT }} />
      )}
    </div>
  );
}
