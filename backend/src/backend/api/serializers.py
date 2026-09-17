from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext

from web3 import Web3

from backend.indexer.pricing_summary import summarize_quote, summarize_price

from .queries import occurrence_from_row
from .models import (
    AuctionListItem,
    AuctionRound,
    PricingPriceFact,
    PricingPriceProvider,
    PricingQuoteFact,
    PricingQuoteProvider,
    RoundListItem,
    TakeDetail,
    TakeListItem,
    TokenModel,
)

TOKEN_LOGO_ORIGIN = "https://prices.wavey.info"


def iso_utc(timestamp: int | str | None) -> str | None:
    if timestamp is None:
        return None
    return (
        datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def checksum_address(value: str | None) -> str | None:
    if not value:
        return None
    return Web3.to_checksum_address(value)


def token_logo_url(chain_id: int | None, address: str | None) -> str | None:
    if chain_id is None or chain_id <= 0 or not address:
        return None
    normalized = checksum_address(address)
    if normalized is None:
        return None
    return f"{TOKEN_LOGO_ORIGIN}/token-logos/{chain_id}/{normalized.lower()}"


def decimal_string(raw_value: str | int | None, decimals: int | None = 0) -> str | None:
    if raw_value is None:
        return None
    if decimals is None:
        return None
    try:
        with localcontext() as context:
            context.prec = 80
            value = Decimal(str(raw_value)) / (Decimal(10) ** decimals)
    except (InvalidOperation, ValueError):
        return str(raw_value)
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def percent_string(value: Decimal | None, *, maximum_fraction_digits: int = 2) -> str | None:
    if value is None:
        return None
    quantizer = Decimal(1).scaleb(-maximum_fraction_digits)
    normalized = value.quantize(quantizer)
    text = format(normalized, "f").rstrip("0").rstrip(".")
    if "." not in text:
        text = f"{text}.00" if maximum_fraction_digits == 2 else text
    elif maximum_fraction_digits == 2:
        whole, fraction = text.split(".", 1)
        text = f"{whole}.{fraction.ljust(2, '0')}"
    return f"{text}%"


def quote_price(
    *,
    paid_raw: str | None,
    sold_raw: str | None,
    from_decimals: int | None,
    want_decimals: int | None,
) -> str | None:
    if paid_raw is None or sold_raw is None or from_decimals is None or want_decimals is None:
        return None
    try:
        sold = int(sold_raw)
        paid = int(paid_raw)
    except ValueError:
        return None
    if sold <= 0:
        return None
    from_decimals = from_decimals or 0
    want_decimals = want_decimals or 0
    numerator = Decimal(paid) * (Decimal(10) ** from_decimals)
    denominator = Decimal(sold) * (Decimal(10) ** want_decimals)
    if denominator == 0:
        return None
    with localcontext() as context:
        context.prec = 80
        return decimal_string(numerator / denominator, 0)


def price_from_e18(raw_value: str | None) -> str | None:
    return decimal_string(raw_value, 18)


def decimal_text_value(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    return str(raw_value)


def percent_text_value(raw_value: str | None) -> str | None:
    try:
        if raw_value is not None:
            raw_decimal = Decimal(str(raw_value))
        else:
            raw_decimal = None
    except (InvalidOperation, ValueError):
        raw_decimal = None

    return percent_string(raw_decimal)


def float_value(raw_value: str | None) -> float | None:
    try:
        return float(raw_value) if raw_value is not None else None
    except (TypeError, ValueError):
        return None


def bps_to_percent_value(raw_value: str | int | None) -> float | None:
    if raw_value is None:
        return None
    try:
        return float(raw_value) / 100.0
    except (TypeError, ValueError):
        return None


def starting_price_per_unit_value(
    *,
    starting_price: str | None,
    initial_available_raw: str | None,
    from_decimals: int | None,
) -> str | None:
    if starting_price is None or initial_available_raw is None:
        return None
    try:
        with localcontext() as context:
            context.prec = 80
            starting = Decimal(str(starting_price))
            initial_available = Decimal(str(initial_available_raw))
            if initial_available <= 0:
                return None
            scaled_starting_price = starting * (Decimal(10) ** int(from_decimals or 0))
            value = scaled_starting_price / initial_available
    except (InvalidOperation, ValueError):
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def token_payload(
    *,
    chain_id: int,
    address: str | None,
    symbol: str | None,
    name: str | None,
    decimals: int | None,
) -> TokenModel | None:
    if not address:
        return None
    checksum = checksum_address(address)
    fallback = checksum or address
    return TokenModel(
        address=fallback,
        symbol=symbol or fallback,
        name=name or fallback,
        decimals=int(decimals or 0),
        chain_id=chain_id,
        logo_url=token_logo_url(chain_id, address),
    )


def auction_list_item_from_row(row) -> AuctionListItem:
    want_token = token_payload(
        chain_id=int(row["chain_id"]),
        address=row["want_token"],
        symbol=row["want_token_symbol"],
        name=row["want_token_name"],
        decimals=row["want_token_decimals"],
    )
    return AuctionListItem(
        address=checksum_address(row["auction_address"]) or row["auction_address"],
        chain_id=int(row["chain_id"]),
        receiver=checksum_address(row["receiver"]) if row["receiver"] else None,
        receiver_name=row["receiver_name"],
        version=row["version"],
        want_token=want_token,
        total_rounds=int(row["total_rounds"] or 0),
        total_takes=int(row["total_takes"] or 0),
        latest_activity_at=iso_utc(row["latest_activity_at"]),
    )


def round_list_item_from_row(row, *, pricing_by_source: dict | None = None) -> RoundListItem:
    from_decimals = int(row["from_token_decimals"]) if row["from_token_decimals"] is not None else None
    want_decimals = int(row["want_token_decimals"]) if row["want_token_decimals"] is not None else None
    return RoundListItem(
        occurrence=occurrence_from_row(row, kick=True),
        chain_id=int(row["chain_id"]),
        auction_address=checksum_address(row["auction_address"]),
        round_id=int(row["round_id"]),
        status=str(row["status"]),
        is_active=str(row["status"]) == "live",
        from_token=checksum_address(row["from_token"]) if row["from_token"] else None,
        from_token_symbol=row["from_token_symbol"],
        from_token_name=row["from_token_name"],
        from_token_decimals=from_decimals,
        from_token_logo_url=token_logo_url(int(row["chain_id"]), row["from_token"]),
        want_token=checksum_address(row["want_token"]) if row["want_token"] else None,
        want_token_symbol=row["want_token_symbol"],
        want_token_name=row["want_token_name"],
        want_token_decimals=want_decimals,
        want_token_logo_url=token_logo_url(int(row["chain_id"]), row["want_token"]),
        kicked_at=iso_utc(row["kicked_at"]),
        scheduled_end_at=iso_utc(row["scheduled_end_at"]),
        end_at=iso_utc(row["end_at"]),
        last_take_at=iso_utc(row["last_take_at"]),
        activity_at=iso_utc(row["activity_at"]),
        take_count=int(row["take_count"]),
        sold_amount=decimal_string(row["sold_amount_raw"], from_decimals),
        paid_amount=decimal_string(row["paid_amount_raw"], want_decimals),
        paid_take_count=int(row["paid_take_count"]),
        avg_execution_price=quote_price(
            paid_raw=row["paid_amount_raw"],
            sold_raw=row["paid_sold_amount_raw"],
            from_decimals=from_decimals,
            want_decimals=want_decimals,
        ),
        last_take_price=price_from_e18(row["last_take_price_raw"]),
        available_amount=decimal_string(row["remaining_available_raw"], from_decimals),
        initial_available=decimal_string(row["initial_available_raw"], from_decimals),
        receiver=checksum_address(row["receiver"]) if row["receiver"] else None,
        receiver_name=row["receiver_name"],
        version=row["version"],
        update_interval=int(row["step_duration_seconds"]) if row["step_duration_seconds"] is not None else None,
        decay_percent=percent_text_value(row["step_decay_percent"]),
        auction_length=int(row["auction_length_seconds"]) if row["auction_length_seconds"] is not None else None,
        starting_price=decimal_text_value(row["starting_price"]),
        starting_price_per_unit=starting_price_per_unit_value(
            starting_price=row["starting_price"],
            initial_available_raw=row["initial_available_raw"],
            from_decimals=from_decimals,
        ),
        minimum_price=decimal_text_value(row["minimum_price"]),
        expected_price_per_unit=quote_price(
            paid_raw=row["kick_market_quote_out_raw"],
            sold_raw=row["initial_available_raw"],
            from_decimals=from_decimals,
            want_decimals=want_decimals,
        ),
        kick_market_quote=decimal_string(row["kick_market_quote_out_raw"], want_decimals),
        kick_market_quote_usd=decimal_text_value(row["kick_market_quote_usd"]),
        total_actual_paid_usd=decimal_text_value(row["total_actual_paid_usd"]),
        paid_usd_take_count=int(row["paid_usd_take_count"] or 0),
        usd_priced_take_count=int(row["usd_priced_take_count"] or 0),
        total_market_quote_usd=decimal_text_value(row["total_market_quote_usd"]),
        total_auction_profit_usd=decimal_text_value(row["total_auction_profit_usd"]),
        total_auction_profit_bps=bps_to_percent_value(row["total_auction_profit_bps"]),
        priced_take_count=int(row["priced_take_count"]) if row["priced_take_count"] is not None else None,
        total_take_count=int(row["total_take_count"]) if row["total_take_count"] is not None else None,
        priced_volume_share=float_value(row["priced_volume_share"]),
        pricing_by_source=pricing_by_source,
    )


def auction_round_from_row(row) -> AuctionRound:
    from_decimals = int(row["from_token_decimals"]) if row["from_token_decimals"] is not None else None
    want_decimals = int(row["want_token_decimals"]) if row["want_token_decimals"] is not None else None
    return AuctionRound(
        occurrence=occurrence_from_row(row, kick=True),
        round_id=int(row["round_id"]),
        kicked_at=iso_utc(row["kicked_at"]),
        round_start=iso_utc(row["kicked_at"]),
        scheduled_end_at=iso_utc(row["scheduled_end_at"]),
        round_end=iso_utc(row["end_at"]),
        initial_available=decimal_string(row["initial_available_raw"], from_decimals) or "0",
        is_active=str(row["status"]) == "live",
        total_takes=int(row["take_count"]),
        from_token=checksum_address(row["from_token"]) if row["from_token"] else None,
        from_token_symbol=row["from_token_symbol"],
        from_token_name=row["from_token_name"],
        from_token_decimals=from_decimals,
        from_token_logo_url=token_logo_url(int(row["chain_id"]), row["from_token"]),
        want_token=checksum_address(row["want_token"]) if row["want_token"] else None,
        want_token_symbol=row["want_token_symbol"],
        want_token_name=row["want_token_name"],
        want_token_decimals=want_decimals,
        want_token_logo_url=token_logo_url(int(row["chain_id"]), row["want_token"]),
        receiver=checksum_address(row["receiver"]) if row["receiver"] else None,
        receiver_name=row["receiver_name"],
        available_amount=decimal_string(row["remaining_available_raw"], from_decimals),
        from_token_price_usd=None,
        want_token_price_usd=None,
        transaction_hash=row["snapshot_tx_hash"],
        version=row["version"],
        update_interval=int(row["step_duration_seconds"]) if row["step_duration_seconds"] is not None else None,
        decay_percent=percent_text_value(row["step_decay_percent"]),
        auction_length=int(row["auction_length_seconds"]) if row["auction_length_seconds"] is not None else None,
        starting_price=decimal_text_value(row["starting_price"]),
        starting_price_per_unit=starting_price_per_unit_value(
            starting_price=row["starting_price"],
            initial_available_raw=row["initial_available_raw"],
            from_decimals=from_decimals,
        ),
        minimum_price=decimal_text_value(row["minimum_price"]),
        expected_price_per_unit=quote_price(
            paid_raw=row["kick_market_quote_out_raw"],
            sold_raw=row["initial_available_raw"],
            from_decimals=from_decimals,
            want_decimals=want_decimals,
        ),
        kick_market_quote=decimal_string(row["kick_market_quote_out_raw"], want_decimals),
        kick_market_quote_usd=decimal_text_value(row["kick_market_quote_usd"]),
        total_actual_paid_usd=decimal_text_value(row["total_actual_paid_usd"]),
        paid_usd_take_count=int(row["paid_usd_take_count"] or 0),
        usd_priced_take_count=int(row["usd_priced_take_count"] or 0),
        total_market_quote_usd=decimal_text_value(row["total_market_quote_usd"]),
        total_auction_profit_usd=decimal_text_value(row["total_auction_profit_usd"]),
        total_auction_profit_bps=bps_to_percent_value(row["total_auction_profit_bps"]),
        priced_take_count=int(row["priced_take_count"]) if row["priced_take_count"] is not None else None,
        total_take_count=int(row["total_take_count"]) if row["total_take_count"] is not None else None,
        priced_volume_share=float_value(row["priced_volume_share"]),
    )


def take_list_item_from_row(row, *, pricing_by_source: dict | None = None) -> TakeListItem:
    from_decimals = int(row["from_token_decimals"]) if row["from_token_decimals"] is not None else None
    want_decimals = int(row["to_token_decimals"]) if row["to_token_decimals"] is not None else None
    actual_paid = row["amount_paid_raw"]
    return TakeListItem(
        occurrence=occurrence_from_row(row),
        round_occurrence=occurrence_from_row(row, kick=True),
        auction=checksum_address(row["auction_address"]),
        chain_id=int(row["chain_id"]),
        round_id=int(row["round_id"]),
        take_seq=int(row["take_seq"]),
        taker=checksum_address(row["taker"]),
        amount_taken=decimal_string(row["amount_taken_raw"], from_decimals) or "0",
        amount_paid=decimal_string(actual_paid, want_decimals),
        expected_amount_paid=decimal_string(row["expected_amount_paid_raw"], want_decimals),
        price=quote_price(
            paid_raw=actual_paid,
            sold_raw=row["amount_taken_raw"],
            from_decimals=from_decimals,
            want_decimals=want_decimals,
        ),
        timestamp=iso_utc(row["timestamp"]),
        tx_hash=str(row["tx_hash"]).lower(),
        block_number=int(row["block_number"]),
        confirmed=bool(row["confirmed"]),
        receiver=checksum_address(row["receiver"]) if row["receiver"] else None,
        receiver_name=row["receiver_name"],
        from_token=checksum_address(row["from_token"]) if row["from_token"] else None,
        to_token=checksum_address(row["want_token"]) if row["want_token"] else None,
        from_token_symbol=row["from_token_symbol"],
        from_token_name=row["from_token_name"],
        from_token_decimals=from_decimals,
        from_token_logo_url=token_logo_url(int(row["chain_id"]), row["from_token"]),
        to_token_symbol=row["to_token_symbol"],
        to_token_name=row["to_token_name"],
        to_token_decimals=want_decimals,
        to_token_logo_url=token_logo_url(int(row["chain_id"]), row["want_token"]),
        amount_taken_usd=None,
        amount_paid_usd=decimal_text_value(row["priced_volume_usd"]),
        market_quote_out=decimal_string(row["market_quote_out_raw"], want_decimals),
        market_quote_out_usd=decimal_text_value(row["market_quote_out_usd"]),
        want_token_price_usd=decimal_text_value(row["want_token_price_usd"]),
        price_differential_usd=decimal_text_value(row["auction_profit_usd"]),
        price_differential_percent=bps_to_percent_value(row["auction_profit_bps"]),
        pricing_status=row["pricing_status"],
        provider_success_count=int(row["provider_success_count"]) if row["provider_success_count"] is not None else None,
        quote_spread_bps=int(row["quote_spread_bps"]) if row["quote_spread_bps"] is not None else None,
        pricing_by_source=pricing_by_source,
    )


def _quote_provider_from_row(
    row,
    *,
    want_decimals: int | None,
    raw_provider_payload: dict | None,
) -> PricingQuoteProvider:
    return PricingQuoteProvider(
        provider_id=str(row["provider_id"]),
        provider_position=int(row["provider_position"]),
        participation_status=str(row["participation_status"]),
        amount_in_raw=decimal_text_value(row["amount_in_raw"]),
        amount_out_raw=decimal_text_value(row["amount_out_raw"]),
        amount_out=decimal_string(row["amount_out_raw"], want_decimals),
        amount_out_min_raw=decimal_text_value(row["amount_out_min_raw"]),
        amount_out_min=decimal_string(row["amount_out_min_raw"], want_decimals),
        price_impact_bps=int(row["price_impact_bps"]) if row["price_impact_bps"] is not None else None,
        estimated_gas=int(row["estimated_gas"]) if row["estimated_gas"] is not None else None,
        latency_ms=int(row["latency_ms"]) if row["latency_ms"] is not None else None,
        as_of=row["as_of"],
        retrieved_at=row["retrieved_at"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        error_retry_after_ms=int(row["error_retry_after_ms"]) if row["error_retry_after_ms"] is not None else None,
        route=_route_from_provider_payload(raw_provider_payload),
        raw_provider_payload=raw_provider_payload,
    )


def _price_provider_from_row(row, *, raw_provider_payload: dict | None) -> PricingPriceProvider:
    return PricingPriceProvider(
        provider_id=str(row["provider_id"]),
        provider_position=int(row["provider_position"]),
        participation_status=str(row["participation_status"]),
        price_usd=decimal_string(row["price_usd"], 0),
        latency_ms=int(row["latency_ms"]) if row["latency_ms"] is not None else None,
        as_of=row["as_of"],
        retrieved_at=row["retrieved_at"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        error_retry_after_ms=int(row["error_retry_after_ms"]) if row["error_retry_after_ms"] is not None else None,
        raw_provider_payload=raw_provider_payload,
    )


def _provider_payloads_from_fact(fact) -> dict[str, dict]:
    if not fact["aggregate_response_json"]:
        return {}
    try:
        aggregate_response = json.loads(fact["aggregate_response_json"])
    except (TypeError, ValueError):
        return {}
    if not isinstance(aggregate_response, dict):
        return {}
    providers = aggregate_response.get("providers")
    if isinstance(providers, dict):
        return {
            str(provider_id): payload
            for provider_id, payload in providers.items()
            if isinstance(payload, dict)
        }
    legacy_rows = aggregate_response.get("legacy_provider_rows")
    if not isinstance(legacy_rows, list):
        return {}
    return {
        str(payload["source"]): payload
        for payload in legacy_rows
        if isinstance(payload, dict) and payload.get("source") is not None
    }


def _route_from_provider_payload(raw_provider_payload: dict | None):
    if raw_provider_payload is None:
        return None
    if "route" in raw_provider_payload:
        return raw_provider_payload.get("route")
    routing_path = raw_provider_payload.get("routing_path")
    if not isinstance(routing_path, str):
        return routing_path
    try:
        return json.loads(routing_path)
    except ValueError:
        return routing_path


def _quote_fact_models(
    quote_fact_rows,
    quote_provider_rows,
    *,
    want_decimals: int | None,
) -> list[PricingQuoteFact]:
    providers_by_fact: dict[int, list] = {}
    for row in quote_provider_rows:
        providers_by_fact.setdefault(int(row["quote_fact_id"]), []).append(row)
    models: list[PricingQuoteFact] = []
    for fact in quote_fact_rows:
        provider_payloads = _provider_payloads_from_fact(fact)
        provider_models = [
            _quote_provider_from_row(
                item,
                want_decimals=want_decimals,
                raw_provider_payload=provider_payloads.get(str(item["provider_id"])),
            )
            for item in providers_by_fact.get(int(fact["id"]), [])
        ]
        summary = summarize_quote(fact, providers_by_fact.get(int(fact["id"]), []))
        models.append(
            PricingQuoteFact(
                id=int(fact["id"]),
                capture_state=str(fact["capture_state"]),
                context_kind=str(fact["context_kind"]),
                captured_at=iso_utc(fact["captured_at"]) or "",
                capture_lag_seconds=int(fact["capture_lag_seconds"]),
                request_id=fact["request_id"],
                canonical_amount_out=decimal_string(summary.amount_out_raw, want_decimals) if summary else None,
                low_amount_out=decimal_string(summary.low_amount_out_raw, want_decimals) if summary else None,
                high_amount_out=decimal_string(summary.high_amount_out_raw, want_decimals) if summary else None,
                spread_bps=summary.spread_bps if summary else None,
                provider_success_count=summary.success_count if summary else 0,
                providers=provider_models,
            )
        )
    return models


def _price_fact_models(price_fact_rows, price_provider_rows) -> list[PricingPriceFact]:
    providers_by_fact: dict[int, list] = {}
    for row in price_provider_rows:
        providers_by_fact.setdefault(int(row["price_fact_id"]), []).append(row)
    models: list[PricingPriceFact] = []
    for fact in price_fact_rows:
        provider_payloads = _provider_payloads_from_fact(fact)
        provider_models = [
            _price_provider_from_row(
                item,
                raw_provider_payload=provider_payloads.get(str(item["provider_id"])),
            )
            for item in providers_by_fact.get(int(fact["id"]), [])
        ]
        summary = summarize_price(fact, providers_by_fact.get(int(fact["id"]), []))
        models.append(
            PricingPriceFact(
                id=int(fact["id"]),
                capture_state=str(fact["capture_state"]),
                context_kind=str(fact["context_kind"]),
                captured_at=iso_utc(fact["captured_at"]) or "",
                capture_lag_seconds=int(fact["capture_lag_seconds"]),
                request_id=fact["request_id"],
                canonical_price_usd=summary.price_usd if summary else None,
                provider_success_count=sum(item.participation_status == "ok" and item.price_usd is not None for item in provider_models),
                providers=provider_models,
            )
        )
    return models


def take_detail_from_row(
    row,
    *,
    quote_fact_rows=None,
    quote_provider_rows=None,
    price_fact_rows=None,
    price_provider_rows=None,
    pricing_by_source: dict | None = None,
) -> TakeDetail:
    item = take_list_item_from_row(row, pricing_by_source=pricing_by_source)
    want_decimals = int(row["to_token_decimals"]) if row["to_token_decimals"] is not None else None
    quote_models = _quote_fact_models(
        quote_fact_rows or [],
        quote_provider_rows or [],
        want_decimals=want_decimals,
    )
    price_models = _price_fact_models(price_fact_rows or [], price_provider_rows or [])
    return TakeDetail(
        **item.model_dump(),
        auction_address=item.auction,
        token_prices=[
            {
                "source": model.capture_state,
                "token_address": item.to_token,
                "token_symbol": item.to_token_symbol,
                "price_usd": float_value(model.canonical_price_usd),
                "block_number": item.block_number,
                "timestamp": row["timestamp"],
            }
            for model in price_models
        ] or None,
        take_quotes=[
            {
                "source": model.capture_state,
                "from_token": item.from_token,
                "to_token": item.to_token,
                "quote": float_value(model.canonical_amount_out),
                "timestamp": row["timestamp"],
                "block_number": item.block_number,
            }
            for model in quote_models
        ] or None,
        quote_facts=quote_models or None,
        price_facts=price_models or None,
        gas_price=None,
        base_fee=None,
        priority_fee=None,
        gas_used=None,
        transaction_fee_eth=None,
        transaction_fee_usd=None,
    )
