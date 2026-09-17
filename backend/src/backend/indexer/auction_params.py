from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext

from .versioning import param_schema_for_version


FIXED_DECAY_FACTOR = Decimal("0.988514020352896135356867505")


@dataclass(frozen=True)
class RawAuctionParams:
    receiver: str | None = None
    minimum_price_raw: str | None = None
    starting_price_raw: str | None = None
    step_decay_rate_raw: str | None = None
    step_duration_raw: str | None = None
    auction_length_raw: str | None = None


@dataclass(frozen=True)
class DecodedAuctionParams:
    starting_price: str | None
    minimum_price: str | None
    step_decay_percent: str | None
    step_duration_seconds: int | None
    auction_length_seconds: int | None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _raw_decimal(value: str | int | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _scaled_decimal(value: str | int | None, decimals: int) -> str | None:
    raw_decimal = _raw_decimal(value)
    if raw_decimal is None:
        return None
    with localcontext() as context:
        context.prec = 80
        return _decimal_text(raw_decimal / (Decimal(10) ** decimals))


def _seconds_int(value: str | int | None) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _fixed_decay_percent_text() -> str:
    with localcontext() as context:
        context.prec = 80
        value = (Decimal("1") - FIXED_DECAY_FACTOR) * Decimal("100")
    return _decimal_text(value) or "0"


def decode_params(param_schema: str | None, raw: RawAuctionParams) -> DecodedAuctionParams:
    if param_schema == "v1_fixed_decay":
        return DecodedAuctionParams(
            starting_price=_scaled_decimal(raw.starting_price_raw, 0),
            minimum_price=None,
            step_decay_percent=_fixed_decay_percent_text(),
            step_duration_seconds=None,
            auction_length_seconds=_seconds_int(raw.auction_length_raw),
        )
    if param_schema == "v1_bps_decay":
        step_decay_raw = _raw_decimal(raw.step_decay_rate_raw)
        step_decay_percent = None
        if step_decay_raw is not None:
            with localcontext() as context:
                context.prec = 80
                step_decay_percent = _decimal_text(step_decay_raw / Decimal("100"))
        return DecodedAuctionParams(
            starting_price=_scaled_decimal(raw.starting_price_raw, 0),
            minimum_price=None if raw.minimum_price_raw is None else _scaled_decimal(raw.minimum_price_raw, 0),
            step_decay_percent=step_decay_percent,
            step_duration_seconds=_seconds_int(raw.step_duration_raw),
            auction_length_seconds=_seconds_int(raw.auction_length_raw),
        )
    if param_schema == "v1_wad_bps":
        step_decay_raw = _raw_decimal(raw.step_decay_rate_raw)
        step_decay_percent = None
        if step_decay_raw is not None:
            with localcontext() as context:
                context.prec = 80
                step_decay_percent = _decimal_text(step_decay_raw / Decimal("100"))
        return DecodedAuctionParams(
            starting_price=_scaled_decimal(raw.starting_price_raw, 0),
            minimum_price=_scaled_decimal(raw.minimum_price_raw, 18),
            step_decay_percent=step_decay_percent,
            step_duration_seconds=_seconds_int(raw.step_duration_raw),
            auction_length_seconds=_seconds_int(raw.auction_length_raw),
        )
    if param_schema == "v1_wad_start_wad_bps":
        step_decay_raw = _raw_decimal(raw.step_decay_rate_raw)
        step_decay_percent = None
        if step_decay_raw is not None:
            with localcontext() as context:
                context.prec = 80
                step_decay_percent = _decimal_text(step_decay_raw / Decimal("100"))
        return DecodedAuctionParams(
            starting_price=_scaled_decimal(raw.starting_price_raw, 18),
            minimum_price=_scaled_decimal(raw.minimum_price_raw, 18),
            step_decay_percent=step_decay_percent,
            step_duration_seconds=_seconds_int(raw.step_duration_raw),
            auction_length_seconds=_seconds_int(raw.auction_length_raw),
        )
    return DecodedAuctionParams(
        starting_price=None,
        minimum_price=None,
        step_decay_percent=None,
        step_duration_seconds=_seconds_int(raw.step_duration_raw),
        auction_length_seconds=_seconds_int(raw.auction_length_raw),
    )
