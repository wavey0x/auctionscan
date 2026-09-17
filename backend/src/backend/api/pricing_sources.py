from __future__ import annotations

from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Mapping

from backend.indexer.types import normalize_address

from .serializers import bps_to_percent_value, decimal_string, float_value


CANONICAL_PRICE_SOURCE = "canonical"

SOURCE_LABELS = {
    CANONICAL_PRICE_SOURCE: "Default",
    "odos": "Odos",
    "cowswap": "CowSwap",
    "enso": "Enso",
    "lifi": "LiFi",
}


def _row_value(row: Mapping[str, Any] | Any, key: str, default: Any = None) -> Any:
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _take_key(row: Mapping[str, Any] | Any) -> tuple[int, str, int, int]:
    return (
        int(_row_value(row, "chain_id")),
        normalize_address(str(_row_value(row, "auction_address"))),
        int(_row_value(row, "round_id")),
        int(_row_value(row, "take_seq")),
    )


def _decimal_value(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def price_source_label(source_id: str) -> str:
    normalized = str(source_id or "").strip().lower()
    if not normalized:
        return "Unknown"
    if normalized in SOURCE_LABELS:
        return SOURCE_LABELS[normalized]
    return normalized.replace("_", " ").replace("-", " ").title()


def build_take_pricing_maps(
    rows: list[Mapping[str, Any] | Any],
    source_rows: list[Mapping[str, Any] | Any],
) -> tuple[
    dict[tuple[int, str, int, int], dict[str, dict[str, Any]]],
    list[dict[str, Any]],
]:
    sources_by_take: dict[tuple[int, str, int, int], dict[str, Mapping[str, Any] | Any]] = {}
    for source_row in source_rows:
        source_id = str(_row_value(source_row, "source_id") or "").strip().lower()
        if source_id:
            sources_by_take.setdefault(_take_key(source_row), {})[source_id] = source_row

    public_maps: dict[tuple[int, str, int, int], dict[str, dict[str, Any]]] = {}
    total_volume_usd = Decimal(0)
    has_total_volume = False
    source_counts: dict[str, int] = {}
    usd_source_counts: dict[str, int] = {}
    source_volumes: dict[str, Decimal] = {}
    source_has_volume: set[str] = set()

    for row in rows:
        take_key = _take_key(row)
        take_sources = dict(sources_by_take.get(take_key, {}))
        canonical = take_sources.get(CANONICAL_PRICE_SOURCE)
        if canonical is None:
            canonical = {
                "source_id": CANONICAL_PRICE_SOURCE,
                "market_quote_out_raw": _row_value(row, "market_quote_out_raw"),
                "market_quote_out_usd": _row_value(row, "market_quote_out_usd"),
                "auction_profit_usd": _row_value(row, "auction_profit_usd"),
                "auction_profit_bps": _row_value(row, "auction_profit_bps"),
                "priced_volume_usd": _row_value(row, "priced_volume_usd"),
                "pricing_status": _row_value(row, "pricing_status"),
            }
            take_sources[CANONICAL_PRICE_SOURCE] = canonical

        want_decimals_raw = _row_value(
            row,
            "to_token_decimals",
            _row_value(row, "want_token_decimals"),
        )
        want_decimals = int(want_decimals_raw) if want_decimals_raw is not None else None
        public_map: dict[str, dict[str, Any]] = {}
        for source_id, source_row in sorted(
            take_sources.items(),
            key=lambda item: (item[0] != CANONICAL_PRICE_SOURCE, price_source_label(item[0])),
        ):
            benchmark_raw = _row_value(source_row, "market_quote_out_raw")
            if source_id != CANONICAL_PRICE_SOURCE and benchmark_raw is None:
                continue
            public_map[source_id] = {
                "market_quote_out": decimal_string(benchmark_raw, want_decimals),
                "market_quote_out_usd": _row_value(source_row, "market_quote_out_usd"),
                "pnl_usd": _row_value(source_row, "auction_profit_usd"),
                "pnl_percent": bps_to_percent_value(_row_value(source_row, "auction_profit_bps")),
                "pricing_status": _row_value(source_row, "pricing_status"),
            }
            if benchmark_raw is not None and _row_value(row, "amount_paid_raw") is not None:
                source_counts[source_id] = source_counts.get(source_id, 0) + 1
                if _row_value(source_row, "auction_profit_usd") is not None:
                    usd_source_counts[source_id] = usd_source_counts.get(source_id, 0) + 1
                priced_volume = _decimal_value(_row_value(source_row, "priced_volume_usd"))
                if priced_volume is not None:
                    source_has_volume.add(source_id)
                    source_volumes[source_id] = source_volumes.get(source_id, Decimal(0)) + priced_volume

        canonical_volume = _decimal_value(_row_value(canonical, "priced_volume_usd"))
        if canonical_volume is not None:
            has_total_volume = True
            total_volume_usd += canonical_volume
        public_maps[take_key] = public_map

    source_ids = {CANONICAL_PRICE_SOURCE}
    for source_map in public_maps.values():
        source_ids.update(source_map)
    options: list[dict[str, Any]] = []
    for source_id in sorted(
        source_ids,
        key=lambda item: (item != CANONICAL_PRICE_SOURCE, price_source_label(item)),
    ):
        priced_volume_share = None
        if source_id in source_has_volume and has_total_volume and total_volume_usd > 0:
            with localcontext() as context:
                context.prec = 80
                priced_volume_share = float(source_volumes[source_id] / total_volume_usd)
        options.append(
            {
                "id": source_id,
                "label": price_source_label(source_id),
                "is_default": source_id == CANONICAL_PRICE_SOURCE,
                "priced_take_count": source_counts.get(source_id, 0),
                "usd_priced_take_count": usd_source_counts.get(source_id, 0),
                "total_take_count": len(rows),
                "priced_volume_share": priced_volume_share,
            }
        )
    return public_maps, options


def build_round_pricing_by_source(
    round_row: Mapping[str, Any] | Any,
    source_rows: list[Mapping[str, Any] | Any],
) -> dict[str, dict[str, Any]]:
    rows_by_source = {
        str(_row_value(source_row, "source_id") or "").strip().lower(): source_row
        for source_row in source_rows
        if str(_row_value(source_row, "source_id") or "").strip()
    }
    if CANONICAL_PRICE_SOURCE not in rows_by_source:
        rows_by_source[CANONICAL_PRICE_SOURCE] = {
            "total_market_quote_usd": _row_value(round_row, "total_market_quote_usd"),
            "total_auction_profit_usd": _row_value(round_row, "total_auction_profit_usd"),
            "total_auction_profit_bps": _row_value(round_row, "total_auction_profit_bps"),
            "priced_take_count": _row_value(round_row, "priced_take_count") or 0,
            "usd_priced_take_count": _row_value(round_row, "usd_priced_take_count") or 0,
            "total_take_count": _row_value(round_row, "total_take_count")
            or _row_value(round_row, "take_count")
            or 0,
            "priced_volume_share": _row_value(round_row, "priced_volume_share"),
        }
    return {
        source_id: {
            "total_market_quote_usd": _row_value(source_row, "total_market_quote_usd"),
            "total_auction_profit_usd": _row_value(source_row, "total_auction_profit_usd"),
            "total_auction_profit_bps": bps_to_percent_value(
                _row_value(source_row, "total_auction_profit_bps")
            ),
            "priced_take_count": int(_row_value(source_row, "priced_take_count") or 0),
            "usd_priced_take_count": int(_row_value(source_row, "usd_priced_take_count") or 0),
            "total_take_count": int(_row_value(source_row, "total_take_count") or 0),
            "priced_volume_share": float_value(_row_value(source_row, "priced_volume_share")),
        }
        for source_id, source_row in sorted(
            rows_by_source.items(),
            key=lambda item: (item[0] != CANONICAL_PRICE_SOURCE, price_source_label(item[0])),
        )
    }
