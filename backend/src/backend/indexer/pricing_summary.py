"""Deterministic audit summaries; eligibility for canonical use belongs to the caller."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any

def _decimal_from_value(value):
    if value is None:
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _decimal_to_text(value):
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


@dataclass(frozen=True)
class QuoteSelection:
    fact_id: int
    capture_lag_seconds: int
    amount_out_raw: str
    success_count: int
    low_amount_out_raw: str
    high_amount_out_raw: str
    spread_bps: int | None


@dataclass(frozen=True)
class PriceSelection:
    fact_id: int
    capture_lag_seconds: int
    price_usd: str


def _quote_spread_bps(low_raw: str | None, high_raw: str | None, canonical_raw: str | None) -> int | None:
    low = _decimal_from_value(low_raw)
    high = _decimal_from_value(high_raw)
    canonical = _decimal_from_value(canonical_raw)
    if low is None or high is None or canonical is None or canonical <= 0:
        return None
    with localcontext() as context:
        context.prec = 80
        spread = ((high - low) / canonical) * Decimal(10_000)
    return int(spread.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def summarize_quote(fact_row, provider_rows: list[Any]) -> QuoteSelection | None:
    with localcontext() as context:
        context.prec = 80
        eligible = [
            row
            for row in provider_rows
            if row["participation_status"] == "ok" and row["amount_out_raw"] is not None
        ]
        if not eligible:
            return None
        sorted_rows = sorted(
            eligible,
            key=lambda row: (int(row["amount_out_raw"]), int(row["provider_position"]), str(row["provider_id"])),
        )
        low_amount = str(sorted_rows[0]["amount_out_raw"])
        high_amount = str(sorted_rows[-1]["amount_out_raw"])
        if len(sorted_rows) % 2 == 1:
            target = Decimal(int(sorted_rows[len(sorted_rows) // 2]["amount_out_raw"]))
        else:
            lower = Decimal(int(sorted_rows[(len(sorted_rows) // 2) - 1]["amount_out_raw"]))
            upper = Decimal(int(sorted_rows[len(sorted_rows) // 2]["amount_out_raw"]))
            target = (lower + upper) / Decimal(2)
        selected = min(
            sorted_rows,
            key=lambda row: (
                abs(Decimal(int(row["amount_out_raw"])) - target),
                int(row["provider_position"]),
                str(row["provider_id"]),
            ),
        )
        canonical_amount = str(selected["amount_out_raw"])
        return QuoteSelection(
            fact_id=int(fact_row["id"]),
            capture_lag_seconds=int(fact_row["capture_lag_seconds"]),
            amount_out_raw=canonical_amount,
            success_count=len(sorted_rows),
            low_amount_out_raw=low_amount,
            high_amount_out_raw=high_amount,
            spread_bps=_quote_spread_bps(low_amount, high_amount, canonical_amount),
        )


def summarize_price(fact_row, provider_rows: list[Any]) -> PriceSelection | None:
    with localcontext() as context:
        context.prec = 80
        eligible = []
        for row in provider_rows:
            if row["participation_status"] != "ok" or row["price_usd"] is None:
                continue
            price = _decimal_from_value(row["price_usd"])
            if price is None:
                continue
            eligible.append((row, price))
        if not eligible:
            return None
        sorted_rows = sorted(
            eligible,
            key=lambda item: (item[1], int(item[0]["provider_position"]), str(item[0]["provider_id"])),
        )
        if len(sorted_rows) % 2 == 1:
            target = sorted_rows[len(sorted_rows) // 2][1]
        else:
            lower = sorted_rows[(len(sorted_rows) // 2) - 1][1]
            upper = sorted_rows[len(sorted_rows) // 2][1]
            target = (lower + upper) / Decimal(2)
        selected = min(
            sorted_rows,
            key=lambda item: (
                abs(item[1] - target),
                int(item[0]["provider_position"]),
                str(item[0]["provider_id"]),
            ),
        )
        return PriceSelection(
            fact_id=int(fact_row["id"]),
            capture_lag_seconds=int(fact_row["capture_lag_seconds"]),
            price_usd=_decimal_to_text(selected[1]) or str(selected[0]["price_usd"]),
        )
