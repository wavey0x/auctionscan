"""Rebuild pricing read models from stored canonical observations."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Any

from .pricing_summary import QuoteSelection, PriceSelection, summarize_quote, summarize_price


def _decimal_from_value(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _decimal_to_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _raw_to_units(raw_value: str | None, decimals: int | None) -> Decimal | None:
    if raw_value is None or decimals is None:
        return None
    raw = _decimal_from_value(raw_value)
    if raw is None:
        return None
    with localcontext() as context:
        context.prec = 80
        return raw / (Decimal(10) ** int(decimals or 0))


def _usd_value(raw_value: str | None, decimals: int | None, price_usd: str | None) -> str | None:
    units = _raw_to_units(raw_value, decimals)
    price = _decimal_from_value(price_usd)
    if units is None or price is None:
        return None
    with localcontext() as context:
        context.prec = 80
        return _decimal_to_text(units * price)


def _ratio_text(numerator: int, denominator: int) -> str | None:
    if denominator <= 0:
        return None
    with localcontext() as context:
        context.prec = 80
        return _decimal_to_text(Decimal(numerator) / Decimal(denominator))


def _decimal_ratio_text(numerator: Decimal, denominator: Decimal) -> str | None:
    if denominator <= 0:
        return None
    with localcontext() as context:
        context.prec = 80
        return _decimal_to_text(numerator / denominator)


def _bps_from_raws(actual_raw: str | None, benchmark_raw: str | None) -> int | None:
    actual = _decimal_from_value(actual_raw)
    benchmark = _decimal_from_value(benchmark_raw)
    if actual is None or benchmark is None or benchmark <= 0:
        return None
    with localcontext() as context:
        context.prec = 80
        bps = ((actual / benchmark) - Decimal(1)) * Decimal(10_000)
    return int(bps.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _source_round(conn, *, chain_id: int, block_hash: str, tx_hash: str, log_index: int,
                  event_name: str) -> tuple[str, int] | None:
    if not block_hash or event_name not in {"Take", "AuctionKicked"}:
        return None
    # Require both a surviving projection and its exact canonical source event.
    if event_name == "Take":
        source = "takes"
        tx_column, log_column = "tx_hash", "log_index"
    else:
        source = "round_param_snapshot"
        tx_column, log_column = "snapshot_tx_hash", "snapshot_log_index"
    row = conn.execute(
        f"""
        SELECT s.auction_address, s.round_id FROM {source} s JOIN domain_events e
          ON e.chain_id = s.chain_id AND e.tx_hash = s.{tx_column} AND e.log_index = s.{log_column}
         WHERE e.chain_id = ? AND e.block_hash = ? AND e.tx_hash = ? AND e.log_index = ? AND e.event_name = ?
        """,
        (chain_id, block_hash, tx_hash, log_index, event_name),
    ).fetchone()
    return (str(row[0]), int(row[1])) if row else None


def _latest_capture_state(rows: list[Any]) -> str | None:
    if not rows:
        return None
    return str(rows[0]["capture_state"])


def _take_pricing_status(
    *,
    quote_selection: QuoteSelection | None,
    price_selection: PriceSelection | None,
    quote_rows: list[Any],
    price_rows: list[Any],
) -> str:
    if quote_selection and price_selection:
        return "priced"
    if quote_selection:
        return "quote_only"
    states = [_latest_capture_state(quote_rows), _latest_capture_state(price_rows)]
    if "unsupported_chain" in states:
        return "unsupported_chain"
    if "stale" in states:
        return "stale"
    if "failed" in states:
        return "failed"
    return "unpriced"


def _round_filter(alias: str, rounds: set[tuple[str, int]] | None) -> tuple[str, tuple]:
    if rounds is None:
        return "", ()
    if not rounds:
        return " AND 0", ()
    placeholders = ",".join("(?, ?)" for _ in rounds)
    return (f" AND ({alias}.auction_address, {alias}.round_id) IN (VALUES {placeholders})",
            tuple(value for key in sorted(rounds) for value in key))


def _load_surviving_take_sources(conn, *, chain_id: int, rounds: set[tuple[str, int]] | None = None) -> dict[tuple[int, str, str, int], tuple[str, int, int]]:
    scope, params = _round_filter("t", rounds)
    rows = conn.execute(
        f"""
        SELECT t.chain_id, e.block_hash, t.tx_hash, t.log_index, t.auction_address, t.round_id, t.take_seq
          FROM takes t JOIN domain_events e
            ON e.chain_id = t.chain_id AND e.tx_hash = t.tx_hash AND e.log_index = t.log_index
           AND e.event_name = 'Take'
         WHERE t.chain_id = ? {scope}
        """, (chain_id, *params),
    ).fetchall()
    return {
        (int(row["chain_id"]), str(row["block_hash"]), str(row["tx_hash"]), int(row["log_index"])):
        (str(row["auction_address"]), int(row["round_id"]), int(row["take_seq"]))
        for row in rows
    }


def _load_surviving_kick_sources(conn, *, chain_id: int, rounds: set[tuple[str, int]] | None = None) -> dict[tuple[int, str, str, int], tuple[str, int]]:
    scope, params = _round_filter("s", rounds)
    rows = conn.execute(
        f"""
        SELECT s.chain_id, e.block_hash, s.snapshot_tx_hash, s.snapshot_log_index, s.auction_address, s.round_id
          FROM round_param_snapshot s JOIN domain_events e
            ON e.chain_id = s.chain_id AND e.tx_hash = s.snapshot_tx_hash AND e.log_index = s.snapshot_log_index
           AND e.event_name = 'AuctionKicked'
         WHERE s.chain_id = ? {scope}
        """, (chain_id, *params),
    ).fetchall()
    return {
        (int(row["chain_id"]), str(row["block_hash"]), str(row["snapshot_tx_hash"]), int(row["snapshot_log_index"])):
        (str(row["auction_address"]), int(row["round_id"]))
        for row in rows
    }


def _resolved_take_source_key(row, *, take_sources) -> tuple[str, int, int] | None:
    if row["source_block_hash"] is None or row["source_tx_hash"] is None or row["source_log_index"] is None:
        return None
    return take_sources.get((int(row["chain_id"]), str(row["source_block_hash"]), str(row["source_tx_hash"]), int(row["source_log_index"])))


def _resolved_kick_source_key(row, *, kick_sources) -> tuple[str, int] | None:
    if row["source_block_hash"] is None or row["source_tx_hash"] is None or row["source_log_index"] is None:
        return None
    return kick_sources.get((int(row["chain_id"]), str(row["source_block_hash"]), str(row["source_tx_hash"]), int(row["source_log_index"])))


def _resolved_quote_fact_key(
    row,
    *,
    take_sources: dict[tuple[int, str, str, int], tuple[str, int, int]],
    kick_sources: dict[tuple[int, str, str, int], tuple[str, int]],
) -> tuple[str, tuple[str, int, int] | tuple[str, int]] | None:
    context_kind = str(row["context_kind"])
    if context_kind == "take":
        key = _resolved_take_source_key(row, take_sources=take_sources)
        return ("take", key) if key is not None else None
    if context_kind == "round_kick":
        key = _resolved_kick_source_key(row, kick_sources=kick_sources)
        return ("round_kick", key) if key is not None else None
    return None


def _resolved_price_fact_key(
    row,
    *,
    take_sources: dict[tuple[int, str, str, int], tuple[str, int, int]],
    kick_sources: dict[tuple[int, str, str, int], tuple[str, int]],
) -> tuple[str, tuple[str, int, int] | tuple[str, int]] | None:
    if str(row["price_role"]) != "want_token":
        return None
    context_kind = str(row["context_kind"])
    if context_kind == "take":
        key = _resolved_take_source_key(row, take_sources=take_sources)
        return ("take", key) if key is not None else None
    if context_kind == "round_kick":
        key = _resolved_kick_source_key(row, kick_sources=kick_sources)
        return ("round_kick", key) if key is not None else None
    return None


def rebuild_pricing_projections(
    conn, *, chain_id: int, rounds: set[tuple[str, int]] | None = None,
    previous_takers: set[str] = frozenset(),
) -> int:
    """Use the same reducers for repair and updates. Capture old takers before deleting takes."""
    scope, params = _round_filter("takes", rounds)
    affected_takers = None if rounds is None else set(previous_takers) | {
        str(row[0]) for row in conn.execute(f"SELECT DISTINCT taker FROM takes WHERE chain_id = ? {scope}", (chain_id, *params))
    }
    for table in ("take_pricing_source", "round_pricing_source", "take_pricing", "round_pricing"):
        scope, params = _round_filter(table, rounds)
        conn.execute(f"DELETE FROM {table} WHERE chain_id = ? {scope}", (chain_id, *params))
    take_sources = _load_surviving_take_sources(conn, chain_id=chain_id, rounds=rounds)
    kick_sources = _load_surviving_kick_sources(conn, chain_id=chain_id, rounds=rounds)
    # Match canonical source occurrences, not fact-time round IDs (which replay can change).
    source_cte = ""
    source_join = ""
    source_params = ()
    if rounds is not None:
        take_scope, take_params = _round_filter("t", rounds)
        kick_scope, kick_params = _round_filter("s", rounds)
        source_cte = f"""WITH selected_sources(chain_id, block_hash, tx_hash, log_index) AS (
            SELECT e.chain_id, e.block_hash, e.tx_hash, e.log_index
              FROM takes t JOIN domain_events e ON e.chain_id = t.chain_id
               AND e.tx_hash = t.tx_hash AND e.log_index = t.log_index AND e.event_name = 'Take'
             WHERE t.chain_id = ? {take_scope}
            UNION
            SELECT e.chain_id, e.block_hash, e.tx_hash, e.log_index
              FROM round_param_snapshot s JOIN domain_events e ON e.chain_id = s.chain_id
               AND e.tx_hash = s.snapshot_tx_hash AND e.log_index = s.snapshot_log_index
               AND e.event_name = 'AuctionKicked'
             WHERE s.chain_id = ? {kick_scope}
        )"""
        source_params = (chain_id, *take_params, chain_id, *kick_params)
        source_join = """JOIN selected_sources selected ON selected.chain_id = {alias}.chain_id
            AND selected.block_hash = {alias}.source_block_hash
            AND selected.tx_hash = {alias}.source_tx_hash AND selected.log_index = {alias}.source_log_index"""

    quote_facts = list(
        conn.execute(
            f"""{source_cte}
            SELECT q.*
              FROM pricing_quote_facts q
              {source_join.format(alias="q")}
             WHERE q.chain_id = ?
             ORDER BY q.captured_at ASC, q.id ASC
            """,
            (*source_params, chain_id),
        ).fetchall()
    )
    quote_provider_rows = list(
        conn.execute(
            f"""{source_cte}
            SELECT qp.*, q.context_kind, q.auction_address, q.round_id, q.take_seq
              FROM pricing_quote_provider_facts qp
              JOIN pricing_quote_facts q
                ON q.id = qp.quote_fact_id
              {source_join.format(alias="q")}
             WHERE q.chain_id = ?
             ORDER BY qp.quote_fact_id ASC, qp.provider_position ASC
            """,
            (*source_params, chain_id),
        ).fetchall()
    )
    price_facts = list(
        conn.execute(
            f"""{source_cte}
            SELECT p.*
              FROM pricing_price_facts p
              {source_join.format(alias="p")}
             WHERE p.chain_id = ?
             ORDER BY p.captured_at ASC, p.id ASC
            """,
            (*source_params, chain_id),
        ).fetchall()
    )
    price_provider_rows = list(
        conn.execute(
            f"""{source_cte}
            SELECT pp.*, p.context_kind, p.price_role, p.auction_address, p.round_id, p.take_seq
              FROM pricing_price_provider_facts pp
              JOIN pricing_price_facts p
                ON p.id = pp.price_fact_id
              {source_join.format(alias="p")}
             WHERE p.chain_id = ?
             ORDER BY pp.price_fact_id ASC, pp.provider_position ASC
            """,
            (*source_params, chain_id),
        ).fetchall()
    )

    quote_providers_by_fact: dict[int, list[Any]] = {}
    for row in quote_provider_rows:
        quote_providers_by_fact.setdefault(int(row["quote_fact_id"]), []).append(row)

    price_providers_by_fact: dict[int, list[Any]] = {}
    for row in price_provider_rows:
        price_providers_by_fact.setdefault(int(row["price_fact_id"]), []).append(row)

    take_quote_rows: dict[tuple[str, int, int], list[Any]] = {}
    round_quote_rows: dict[tuple[str, int], list[Any]] = {}
    take_quote_selection: dict[tuple[str, int, int], QuoteSelection] = {}
    round_quote_selection: dict[tuple[str, int], QuoteSelection] = {}
    for row in quote_facts:
        resolved = _resolved_quote_fact_key(
            row,
            take_sources=take_sources,
            kick_sources=kick_sources,
        )
        if resolved is None:
            continue
        context_kind, key = resolved
        if context_kind == "take":
            take_quote_rows.setdefault(key, []).insert(0, row)
            selection = summarize_quote(row, quote_providers_by_fact.get(int(row["id"]), [])) if row["capture_state"] == "fresh" else None
            if selection is not None and key not in take_quote_selection:
                take_quote_selection[key] = selection
        elif context_kind == "round_kick":
            round_quote_rows.setdefault(key, []).insert(0, row)
            selection = summarize_quote(row, quote_providers_by_fact.get(int(row["id"]), [])) if row["capture_state"] == "fresh" else None
            if selection is not None and key not in round_quote_selection:
                round_quote_selection[key] = selection

    take_price_rows: dict[tuple[str, int, int], list[Any]] = {}
    round_price_rows: dict[tuple[str, int], list[Any]] = {}
    take_price_selection: dict[tuple[str, int, int], PriceSelection] = {}
    round_price_selection: dict[tuple[str, int], PriceSelection] = {}
    for row in price_facts:
        resolved = _resolved_price_fact_key(
            row,
            take_sources=take_sources,
            kick_sources=kick_sources,
        )
        if resolved is None:
            continue
        context_kind, key = resolved
        if context_kind == "take":
            take_price_rows.setdefault(key, []).insert(0, row)
            selection = summarize_price(row, price_providers_by_fact.get(int(row["id"]), [])) if row["capture_state"] == "fresh" else None
            if selection is not None and key not in take_price_selection:
                take_price_selection[key] = selection
        elif context_kind == "round_kick":
            round_price_rows.setdefault(key, []).insert(0, row)
            selection = summarize_price(row, price_providers_by_fact.get(int(row["id"]), [])) if row["capture_state"] == "fresh" else None
            if selection is not None and key not in round_price_selection:
                round_price_selection[key] = selection

    scope, params = _round_filter("t", rounds)
    take_rows = list(
        conn.execute(
            f"""
            SELECT t.chain_id,
                   t.auction_address,
                   t.round_id,
                   t.take_seq,
                   t.taker,
                   t.amount_taken_raw,
                   t.amount_paid_raw,
                   t.expected_amount_paid_raw,
                   t.timestamp,
                   t.from_token,
                   t.want_token,
                   wt.decimals AS want_token_decimals
              FROM takes t
              LEFT JOIN tokens wt
                ON wt.chain_id = t.chain_id
               AND wt.token_address = t.want_token
             WHERE t.chain_id = ? {scope}
             ORDER BY t.round_id ASC, t.take_seq ASC
            """,
            (chain_id, *params),
        ).fetchall()
    )

    take_pricing_rows: list[tuple[Any, ...]] = []
    take_pricing_source_rows: list[tuple[Any, ...]] = []
    take_rollups: dict[tuple[str, int], dict[str, Any]] = {}
    provider_round_rollups: dict[tuple[str, int, str], dict[str, Any]] = {}

    for row in take_rows:
        key = (str(row["auction_address"]), int(row["round_id"]), int(row["take_seq"]))
        quote_selection = take_quote_selection.get(key)
        price_selection = take_price_selection.get(key)
        want_decimals = int(row["want_token_decimals"]) if row["want_token_decimals"] is not None else None
        actual_paid_raw = row["amount_paid_raw"]
        market_quote_out_raw = quote_selection.amount_out_raw if quote_selection else None
        want_token_price_usd = price_selection.price_usd if price_selection else None
        auction_profit_raw = None
        if row["amount_paid_raw"] is not None and market_quote_out_raw is not None:
            auction_profit_raw = str(int(row["amount_paid_raw"]) - int(market_quote_out_raw))
        auction_profit_usd = _usd_value(auction_profit_raw, want_decimals, want_token_price_usd)
        actual_paid_usd = _usd_value(actual_paid_raw, want_decimals, want_token_price_usd)
        market_quote_out_usd = _usd_value(
            market_quote_out_raw,
            want_decimals,
            want_token_price_usd,
        )
        pricing_status = _take_pricing_status(
            quote_selection=quote_selection,
            price_selection=price_selection,
            quote_rows=take_quote_rows.get(key, []),
            price_rows=take_price_rows.get(key, []),
        )
        take_pricing_rows.append(
            (
                chain_id,
                row["auction_address"],
                int(row["round_id"]),
                int(row["take_seq"]),
                quote_selection.fact_id if quote_selection else None,
                price_selection.fact_id if price_selection else None,
                None,
                row["amount_taken_raw"],
                row["amount_paid_raw"],
                row["expected_amount_paid_raw"],
                market_quote_out_raw,
                market_quote_out_usd,
                want_token_price_usd,
                None,
                auction_profit_raw,
                _bps_from_raws(row["amount_paid_raw"], market_quote_out_raw),
                auction_profit_usd,
                actual_paid_usd,
                pricing_status,
                quote_selection.success_count if quote_selection else 0,
                quote_selection.spread_bps if quote_selection else None,
                quote_selection.capture_lag_seconds if quote_selection else None,
                1 if quote_selection else 0,
                1 if price_selection else 0,
            )
        )

        selected_provider_rows = (
            quote_providers_by_fact.get(quote_selection.fact_id, [])
            if quote_selection is not None
            else []
        )
        seen_source_ids: set[str] = set()
        for provider_row in selected_provider_rows:
            if provider_row["participation_status"] != "ok" or provider_row["amount_out_raw"] is None:
                continue
            source_id = str(provider_row["provider_id"] or "").strip().lower()
            if not source_id or source_id in seen_source_ids:
                continue
            seen_source_ids.add(source_id)
            provider_market_quote_out_raw = str(provider_row["amount_out_raw"])
            provider_profit_raw = None
            if actual_paid_raw is not None:
                provider_profit_raw = str(int(actual_paid_raw) - int(provider_market_quote_out_raw))
            provider_market_quote_usd = _usd_value(
                provider_market_quote_out_raw,
                want_decimals,
                want_token_price_usd,
            )
            provider_profit_usd = _usd_value(
                provider_profit_raw,
                want_decimals,
                want_token_price_usd,
            )
            provider_profit_bps = _bps_from_raws(
                actual_paid_raw,
                provider_market_quote_out_raw,
            )
            take_pricing_source_rows.append(
                (
                    chain_id,
                    row["auction_address"],
                    int(row["round_id"]),
                    int(row["take_seq"]),
                    source_id,
                    quote_selection.fact_id,
                    provider_market_quote_out_raw,
                    provider_market_quote_usd,
                    provider_profit_raw,
                    provider_profit_usd,
                    provider_profit_bps,
                    actual_paid_usd,
                    "priced",
                )
            )

            provider_rollup = provider_round_rollups.setdefault(
                (str(row["auction_address"]), int(row["round_id"]), source_id),
                {
                    "total_actual_paid_raw": 0,
                    "total_market_quote_out_raw": 0,
                    "total_actual_paid_usd": Decimal(0),
                    "total_market_quote_usd": Decimal(0),
                    "total_auction_profit_usd": Decimal(0),
                    "priced_take_count": 0,
                    "usd_priced_take_count": 0,
                    "has_actual_paid_usd": False,
                    "has_market_quote_usd": False,
                    "has_profit_usd": False,
                    "priced_volume_raw": 0,
                },
            )
            if actual_paid_raw is not None:
                provider_rollup["total_actual_paid_raw"] += int(actual_paid_raw)
                provider_rollup["total_market_quote_out_raw"] += int(provider_market_quote_out_raw)
                provider_rollup["priced_take_count"] += 1
                provider_rollup["priced_volume_raw"] += int(row["amount_taken_raw"])
            if provider_profit_usd is not None:
                provider_rollup["usd_priced_take_count"] += 1
                provider_rollup["has_actual_paid_usd"] = True
                provider_rollup["has_market_quote_usd"] = True
                provider_rollup["has_profit_usd"] = True
                provider_rollup["total_actual_paid_usd"] += Decimal(actual_paid_usd)
                provider_rollup["total_market_quote_usd"] += Decimal(provider_market_quote_usd)
                provider_rollup["total_auction_profit_usd"] += Decimal(provider_profit_usd)

        round_key = (str(row["auction_address"]), int(row["round_id"]))
        round_rollup = take_rollups.setdefault(
            round_key,
            {
                "total_actual_paid_raw": 0,
                "matched_actual_paid_raw": 0,
                "matched_market_quote_out_raw": 0,
                "total_market_quote_out_raw": 0,
                "priced_take_count": 0,
                "usd_priced_take_count": 0,
                "paid_usd_take_count": 0,
                "paid_take_count": 0,
                "priced_volume_raw": 0,
                "total_take_count": 0,
                "total_actual_paid_usd": Decimal(0),
                "total_market_quote_usd": Decimal(0),
                "total_auction_profit_usd": Decimal(0),
                "has_actual_paid_usd": False,
                "has_market_quote_usd": False,
                "has_profit_usd": False,
            },
        )
        if actual_paid_raw is not None:
            round_rollup["total_actual_paid_raw"] += int(actual_paid_raw)
            round_rollup["paid_take_count"] += 1
        # PnL must compare receipts and quotes for the same fills. Unknown
        # receipts or missing quotes contribute to neither side of the ratio.
        if row["amount_paid_raw"] is not None and market_quote_out_raw is not None:
            round_rollup["matched_actual_paid_raw"] += int(row["amount_paid_raw"])
            round_rollup["matched_market_quote_out_raw"] += int(market_quote_out_raw)
        round_rollup["total_take_count"] += 1
        if quote_selection is not None and actual_paid_raw is not None:
            round_rollup["total_market_quote_out_raw"] += int(market_quote_out_raw)
            round_rollup["priced_take_count"] += 1
            round_rollup["priced_volume_raw"] += int(row["amount_taken_raw"])
        actual_paid_usd = _usd_value(row["amount_paid_raw"], want_decimals, want_token_price_usd)
        market_quote_usd = _usd_value(market_quote_out_raw, want_decimals, want_token_price_usd)
        if actual_paid_usd is not None:
            round_rollup["paid_usd_take_count"] += 1
            round_rollup["has_actual_paid_usd"] = True
            round_rollup["total_actual_paid_usd"] += Decimal(actual_paid_usd)
        if auction_profit_usd is not None:
            round_rollup["has_market_quote_usd"] = True
            round_rollup["total_market_quote_usd"] += Decimal(market_quote_usd)
        if auction_profit_usd is not None:
            round_rollup["usd_priced_take_count"] += 1
            round_rollup["has_profit_usd"] = True
            round_rollup["total_auction_profit_usd"] += Decimal(auction_profit_usd)


    if take_pricing_rows:
        conn.executemany(
            """
            INSERT INTO take_pricing (
                chain_id, auction_address, round_id, take_seq,
                canonical_quote_fact_id, canonical_want_price_fact_id,
                canonical_from_price_fact_id, amount_taken_raw, actual_paid_raw,
                expected_paid_raw, market_quote_out_raw, market_quote_out_usd,
                want_token_price_usd,
                from_token_price_usd, auction_profit_raw, auction_profit_bps,
                auction_profit_usd, priced_volume_usd, pricing_status,
                provider_success_count, quote_spread_bps, capture_lag_seconds,
                fresh_quote, fresh_want_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            take_pricing_rows,
        )
    if take_pricing_source_rows:
        conn.executemany(
            """
            INSERT INTO take_pricing_source (
                chain_id, auction_address, round_id, take_seq, source_id,
                quote_fact_id, market_quote_out_raw, market_quote_out_usd,
                auction_profit_raw, auction_profit_usd, auction_profit_bps,
                priced_volume_usd, pricing_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            take_pricing_source_rows,
        )

    scope, params = _round_filter("r", rounds)
    round_rows = list(
        conn.execute(
            f"""
            SELECT r.chain_id,
                   r.auction_address,
                   r.round_id,
                   r.initial_available_raw,
                   r.sold_amount_raw,
                   r.take_count,
                   r.want_token,
                   wt.decimals AS want_token_decimals
              FROM rounds r
              LEFT JOIN tokens wt
                ON wt.chain_id = r.chain_id
               AND wt.token_address = r.want_token
             WHERE r.chain_id = ? {scope}
             ORDER BY r.round_id ASC
            """,
            (chain_id, *params),
        ).fetchall()
    )

    round_pricing_rows: list[tuple[Any, ...]] = []
    round_pricing_source_rows: list[tuple[Any, ...]] = []
    for row in round_rows:
        key = (str(row["auction_address"]), int(row["round_id"]))
        quote_selection = round_quote_selection.get(key)
        price_selection = round_price_selection.get(key)
        want_decimals = int(row["want_token_decimals"]) if row["want_token_decimals"] is not None else None
        rollup = take_rollups.get(
            key,
            {
                "total_actual_paid_raw": 0,
                "matched_actual_paid_raw": 0,
                "matched_market_quote_out_raw": 0,
                "total_market_quote_out_raw": 0,
                "priced_take_count": 0,
                "usd_priced_take_count": 0,
                "paid_usd_take_count": 0,
                "paid_take_count": 0,
                "priced_volume_raw": 0,
                "total_take_count": int(row["take_count"]),
                "total_actual_paid_usd": Decimal(0),
                "total_market_quote_usd": Decimal(0),
                "total_auction_profit_usd": Decimal(0),
                "has_actual_paid_usd": False,
                "has_market_quote_usd": False,
                "has_profit_usd": False,
            },
        )
        kick_market_quote_out_raw = quote_selection.amount_out_raw if quote_selection else None
        kick_market_quote_usd = _usd_value(
            kick_market_quote_out_raw,
            want_decimals,
            price_selection.price_usd if price_selection else None,
        )
        total_actual_paid_raw = str(rollup["total_actual_paid_raw"]) if rollup["paid_take_count"] else None
        total_market_quote_out_raw = str(rollup["total_market_quote_out_raw"]) if rollup["priced_take_count"] else None
        round_pricing_rows.append(
            (
                chain_id,
                row["auction_address"],
                int(row["round_id"]),
                quote_selection.fact_id if quote_selection else None,
                kick_market_quote_out_raw,
                kick_market_quote_usd,
                None,
                None,
                total_actual_paid_raw,
                total_market_quote_out_raw,
                _decimal_to_text(rollup["total_actual_paid_usd"]) if rollup["has_actual_paid_usd"] else None,
                _decimal_to_text(rollup["total_market_quote_usd"]) if rollup["has_market_quote_usd"] else None,
                _decimal_to_text(rollup["total_auction_profit_usd"]) if rollup["has_profit_usd"] else None,
                _bps_from_raws(
                    str(rollup["matched_actual_paid_raw"]),
                    str(rollup["matched_market_quote_out_raw"]),
                ),
                int(rollup["priced_take_count"]),
                int(rollup["usd_priced_take_count"]),
                int(rollup["paid_usd_take_count"]),
                int(row["take_count"]),
                _ratio_text(int(rollup["priced_volume_raw"]), int(row["sold_amount_raw"] or 0)),
            )
        )
        provider_keys = sorted(
            (
                provider_key
                for provider_key in provider_round_rollups
                if provider_key[0] == key[0] and provider_key[1] == key[1]
            ),
            key=lambda provider_key: provider_key[2],
        )
        for provider_key in provider_keys:
            source_id = provider_key[2]
            provider_rollup = provider_round_rollups[provider_key]
            provider_actual_raw = str(provider_rollup["total_actual_paid_raw"]) if provider_rollup["priced_take_count"] else None
            provider_market_raw = str(provider_rollup["total_market_quote_out_raw"]) if provider_rollup["priced_take_count"] else None
            provider_volume_share = _ratio_text(provider_rollup["priced_volume_raw"], int(row["sold_amount_raw"]))
            round_pricing_source_rows.append(
                (
                    chain_id,
                    row["auction_address"],
                    int(row["round_id"]),
                    source_id,
                    provider_actual_raw,
                    provider_market_raw,
                    _decimal_to_text(provider_rollup["total_actual_paid_usd"])
                    if provider_rollup["has_actual_paid_usd"]
                    else None,
                    _decimal_to_text(provider_rollup["total_market_quote_usd"])
                    if provider_rollup["has_market_quote_usd"]
                    else None,
                    _decimal_to_text(provider_rollup["total_auction_profit_usd"])
                    if provider_rollup["has_profit_usd"]
                    else None,
                    _bps_from_raws(provider_actual_raw, provider_market_raw),
                    int(provider_rollup["priced_take_count"]),
                    int(provider_rollup["usd_priced_take_count"]),
                    int(row["take_count"]),
                    provider_volume_share,
                )
            )

    if round_pricing_rows:
        conn.executemany(
            """
            INSERT INTO round_pricing (
                chain_id, auction_address, round_id, kick_quote_fact_id,
                kick_market_quote_out_raw, kick_market_quote_usd,
                kick_contract_expected_out_raw, kick_start_premium_bps,
                total_actual_paid_raw,
                total_market_quote_out_raw, total_actual_paid_usd,
                total_market_quote_usd, total_auction_profit_usd,
                total_auction_profit_bps, priced_take_count, usd_priced_take_count, paid_usd_take_count, total_take_count,
                priced_volume_share
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            round_pricing_rows,
        )
    if round_pricing_source_rows:
        conn.executemany(
            """
            INSERT INTO round_pricing_source (
                chain_id, auction_address, round_id, source_id,
                total_actual_paid_raw, total_market_quote_out_raw,
                total_actual_paid_usd, total_market_quote_usd,
                total_auction_profit_usd, total_auction_profit_bps,
                priced_take_count, usd_priced_take_count, total_take_count, priced_volume_share
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            round_pricing_source_rows,
        )

    taker_rows_written = _rebuild_taker_pricing_summaries(conn, chain_id=chain_id, takers=affected_takers)
    return (
        len(take_pricing_rows)
        + len(take_pricing_source_rows)
        + len(round_pricing_rows)
        + len(round_pricing_source_rows)
        + taker_rows_written
    )


def _rebuild_taker_pricing_summaries(conn, *, chain_id: int, takers: set[str] | None) -> int:
    if takers == set():
        return 0
    scope = "" if takers is None else " AND taker IN (" + ",".join("?" for _ in takers) + ")"
    params = (chain_id, *sorted(takers or ()))
    conn.execute(f"DELETE FROM taker_pricing_summary WHERE chain_id = ? {scope}", params)
    rows = conn.execute(f"""
        SELECT t.taker, t.timestamp, t.amount_paid_raw, wt.decimals AS want_token_decimals,
               p.canonical_quote_fact_id, p.want_token_price_usd, p.market_quote_out_usd,
               p.auction_profit_usd, p.priced_volume_usd
          FROM takes t
          LEFT JOIN take_pricing p ON p.chain_id = t.chain_id AND p.auction_address = t.auction_address
               AND p.round_id = t.round_id AND p.take_seq = t.take_seq
          LEFT JOIN tokens wt ON wt.chain_id = t.chain_id AND wt.token_address = t.want_token
         WHERE t.chain_id = ? {scope}
         ORDER BY t.auction_address, t.round_id, t.take_seq
    """, params).fetchall()
    taker_rollups: dict[str, dict[str, Any]] = {}
    for row in rows:
        actual_paid_usd = _usd_value(row["amount_paid_raw"], row["want_token_decimals"], row["want_token_price_usd"])
        market_quote_usd = row["market_quote_out_usd"]
        auction_profit_usd = row["auction_profit_usd"]
        taker = str(row["taker"])
        taker_rollup = taker_rollups.setdefault(
            taker,
            {
                "total_take_count": 0,
                "priced_take_count": 0,
                "paid_usd_take_count": 0,
                "total_actual_paid_usd": Decimal(0),
                "total_market_quote_usd": Decimal(0),
                "total_taker_profit_usd": Decimal(0),
                "priced_volume_usd": Decimal(0),
                "total_volume_usd_for_share": Decimal(0),
                "has_actual_paid_usd": False,
                "has_market_quote_usd": False,
                "has_taker_profit_usd": False,
                "first_priced_take_at": None,
                "last_priced_take_at": None,
            },
        )
        taker_rollup["total_take_count"] += 1
        if actual_paid_usd is not None:
            taker_rollup["total_volume_usd_for_share"] += Decimal(actual_paid_usd)
            if row["canonical_quote_fact_id"] is not None:
                taker_rollup["priced_volume_usd"] += Decimal(actual_paid_usd)
        if auction_profit_usd is not None:
            taker_rollup["priced_take_count"] += 1
            timestamp = int(row["timestamp"])
            if taker_rollup["first_priced_take_at"] is None:
                taker_rollup["first_priced_take_at"] = timestamp
                taker_rollup["last_priced_take_at"] = timestamp
            else:
                taker_rollup["first_priced_take_at"] = min(taker_rollup["first_priced_take_at"], timestamp)
                taker_rollup["last_priced_take_at"] = max(taker_rollup["last_priced_take_at"], timestamp)
        if actual_paid_usd is not None:
            taker_rollup["paid_usd_take_count"] += 1
            taker_rollup["has_actual_paid_usd"] = True
            taker_rollup["total_actual_paid_usd"] += Decimal(actual_paid_usd)
        if auction_profit_usd is not None:
            taker_rollup["has_market_quote_usd"] = True
            taker_rollup["total_market_quote_usd"] += Decimal(market_quote_usd)
        if auction_profit_usd is not None:
            taker_rollup["has_taker_profit_usd"] = True
            taker_rollup["total_taker_profit_usd"] += -Decimal(auction_profit_usd)

    taker_pricing_rows: list[tuple[Any, ...]] = []
    for taker, rollup in sorted(taker_rollups.items()):
        average_profit = None
        if rollup["priced_take_count"] > 0 and rollup["has_taker_profit_usd"]:
            with localcontext() as context:
                context.prec = 80
                average_profit = _decimal_to_text(
                    rollup["total_taker_profit_usd"] / Decimal(rollup["priced_take_count"])
                )
        taker_pricing_rows.append(
            (
                chain_id,
                taker,
                int(rollup["priced_take_count"]),
                int(rollup["total_take_count"]),
                int(rollup["paid_usd_take_count"]),
                _decimal_to_text(rollup["total_actual_paid_usd"]) if rollup["has_actual_paid_usd"] else None,
                _decimal_to_text(rollup["total_market_quote_usd"]) if rollup["has_market_quote_usd"] else None,
                _decimal_to_text(rollup["total_taker_profit_usd"]) if rollup["has_taker_profit_usd"] else None,
                average_profit,
                _decimal_to_text(rollup["priced_volume_usd"]),
                _decimal_to_text(rollup["total_volume_usd_for_share"]),
                _decimal_ratio_text(rollup["priced_volume_usd"], rollup["total_volume_usd_for_share"]),
                rollup["first_priced_take_at"],
                rollup["last_priced_take_at"],
            )
        )

    if taker_pricing_rows:
        conn.executemany(
            """
            INSERT INTO taker_pricing_summary (
                chain_id, taker, priced_take_count, total_take_count, paid_usd_take_count,
                total_actual_paid_usd, total_market_quote_usd,
                total_taker_profit_usd, avg_taker_profit_usd,
                priced_volume_usd, total_volume_usd_for_share,
                priced_volume_share, first_priced_take_at, last_priced_take_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            taker_pricing_rows,
        )
    return len(taker_pricing_rows)
