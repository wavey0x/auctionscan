from __future__ import annotations

import json
import logging
import time

from .facts import _deterministic_round_id, _resolve_event_from_token, persist_prepared_events, persist_snapshot_facts
from .auction_params import RawAuctionParams, decode_params, param_schema_for_version
from .types import AuctionSnapshot, ChainConfig, FactorySeed, IndexedBlockRecord, PreparedEvent, decimal_text


logger = logging.getLogger(__name__)


def _now() -> int:
    return int(time.time())


def _json_dumps(payload) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def chain_start_block(chain: ChainConfig, factories: list[FactorySeed]) -> int:
    starts = [factory.start_block for factory in factories if factory.enabled]
    if chain.registry is not None:
        starts.append(chain.registry.start_block)
    return min(starts) if starts else 0


def ensure_sync_state(conn, chain: ChainConfig, start_block: int) -> None:
    initial_cursor = max(-1, start_block - 1)
    conn.execute(
        """
        INSERT INTO sync_state (
            chain_id, network_name, last_confirmed_processed, last_live_processed, reorg_count, health
        ) VALUES (?, ?, ?, ?, 0, 'idle')
        ON CONFLICT(chain_id) DO NOTHING
        """,
        (chain.chain_id, chain.name, initial_cursor, initial_cursor),
    )


def upsert_tracked_factories(conn, chain_id: int, factories: list[FactorySeed]) -> list[FactorySeed]:
    inserted_factories: list[FactorySeed] = []
    now = _now()
    for factory in factories:
        row = conn.execute(
            "SELECT start_block FROM tracked_factories WHERE chain_id = ? AND factory_address = ?",
            (chain_id, factory.address),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO tracked_factories (
                    chain_id, factory_address, version, capability_family, discovery_source,
                    start_block, deploy_block, deploy_block_source, active_flag, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chain_id,
                    factory.address,
                    factory.version,
                    factory.capability_family,
                    factory.discovery_source,
                    factory.start_block,
                    factory.deploy_block,
                    factory.deploy_block_source,
                    1 if factory.enabled else 0,
                    now,
                    now,
                ),
            )
            inserted_factories.append(factory)
            continue

        conn.execute(
            """
            UPDATE tracked_factories
               SET version = ?,
                   capability_family = ?,
                   discovery_source = ?,
                   start_block = ?,
                   deploy_block = ?,
                   deploy_block_source = ?,
                   active_flag = ?,
                   updated_at = ?
             WHERE chain_id = ? AND factory_address = ?
            """,
            (
                factory.version,
                factory.capability_family,
                factory.discovery_source,
                factory.start_block,
                factory.deploy_block,
                factory.deploy_block_source,
                1 if factory.enabled else 0,
                now,
                chain_id,
                factory.address,
            ),
        )
    return inserted_factories


def load_tracked_factories(conn, chain_id: int):
    return list(
        conn.execute(
            """
            SELECT *
              FROM tracked_factories
             WHERE chain_id = ? AND active_flag = 1
             ORDER BY start_block ASC, factory_address ASC
            """,
            (chain_id,),
        ).fetchall()
    )


def load_tracked_auctions(conn, chain_id: int):
    return list(
        conn.execute(
            """
            SELECT *
              FROM tracked_auctions
             WHERE chain_id = ? AND active_flag = 1
             ORDER BY discovered_block ASC, auction_address ASC
            """,
            (chain_id,),
        ).fetchall()
    )


def _upsert_token_metadata(conn, prepared: PreparedEvent) -> None:
    now = _now()
    for token in prepared.token_metadata:
        conn.execute(
            """
            INSERT INTO tokens (
                chain_id, token_address, symbol, name, decimals, metadata_updated_at, metadata_block
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chain_id, token_address) DO UPDATE SET
                symbol = excluded.symbol,
                name = excluded.name,
                decimals = excluded.decimals,
                metadata_updated_at = excluded.metadata_updated_at,
                metadata_block = excluded.metadata_block
            WHERE excluded.metadata_block >= tokens.metadata_block
            """,
            (
                token.chain_id,
                token.token_address,
                token.symbol,
                token.name,
                token.decimals,
                now,
                prepared.domain_event.block_number,
            ),
        )


def rebuild_token_metadata(conn, chain_id: int, events: list[PreparedEvent]) -> None:
    conn.execute("DELETE FROM tokens WHERE chain_id = ?", (chain_id,))
    for prepared in events:
        _upsert_token_metadata(conn, prepared)


def _merge_extra_params(existing_json: str | None, new_payload: dict) -> str:
    payload = {}
    if existing_json:
        payload.update(json.loads(existing_json))
    payload.update(new_payload)
    return _json_dumps(payload)


def _raw_params_from_snapshot(snapshot: AuctionSnapshot | None) -> RawAuctionParams:
    if snapshot is None:
        return RawAuctionParams()
    return RawAuctionParams(
        receiver=snapshot.receiver,
        minimum_price_raw=snapshot.minimum_price_raw,
        starting_price_raw=snapshot.starting_price_raw,
        step_decay_rate_raw=snapshot.step_decay_rate_raw,
        step_duration_raw=snapshot.step_duration_raw,
        auction_length_raw=snapshot.auction_length_raw,
    )


def _raw_params_from_row(row) -> RawAuctionParams:
    if row is None:
        return RawAuctionParams()
    return RawAuctionParams(
        receiver=row["receiver"],
        minimum_price_raw=row["minimum_price_raw"],
        starting_price_raw=row["starting_price_raw"],
        step_decay_rate_raw=row["step_decay_rate_raw"],
        step_duration_raw=row["step_duration_raw"],
        auction_length_raw=row["auction_length_raw"],
    )


def _persist_current_params(
    conn,
    *,
    chain_id: int,
    auction_address: str,
    param_schema: str | None,
    raw_params: RawAuctionParams,
    extra_params_json: str,
    block_number: int,
    updated_at: int,
) -> None:
    decoded = decode_params(param_schema, raw_params)
    conn.execute(
        """
        INSERT INTO auction_current_params (
            chain_id, auction_address, param_schema, receiver, minimum_price_raw, starting_price_raw,
            step_decay_rate_raw, step_duration_raw, auction_length_raw, minimum_price, starting_price,
            step_decay_percent, step_duration_seconds, auction_length_seconds, extra_params_json,
            last_updated_block, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chain_id, auction_address) DO UPDATE SET
            param_schema = excluded.param_schema,
            receiver = excluded.receiver,
            minimum_price_raw = excluded.minimum_price_raw,
            starting_price_raw = excluded.starting_price_raw,
            step_decay_rate_raw = excluded.step_decay_rate_raw,
            step_duration_raw = excluded.step_duration_raw,
            auction_length_raw = excluded.auction_length_raw,
            minimum_price = excluded.minimum_price,
            starting_price = excluded.starting_price,
            step_decay_percent = excluded.step_decay_percent,
            step_duration_seconds = excluded.step_duration_seconds,
            auction_length_seconds = excluded.auction_length_seconds,
            extra_params_json = excluded.extra_params_json,
            last_updated_block = excluded.last_updated_block,
            updated_at = excluded.updated_at
        """,
        (
            chain_id,
            auction_address,
            param_schema,
            raw_params.receiver,
            raw_params.minimum_price_raw,
            raw_params.starting_price_raw,
            raw_params.step_decay_rate_raw,
            raw_params.step_duration_raw,
            raw_params.auction_length_raw,
            decoded.minimum_price,
            decoded.starting_price,
            decoded.step_decay_percent,
            decoded.step_duration_seconds,
            decoded.auction_length_seconds,
            extra_params_json,
            block_number,
            updated_at,
        ),
    )


def _upsert_current_params(conn, event, snapshot: AuctionSnapshot | None, *, block_number: int) -> None:
    current_row = conn.execute(
        """
        SELECT receiver, minimum_price_raw, starting_price_raw, step_decay_rate_raw,
               step_duration_raw, auction_length_raw, extra_params_json, param_schema,
               last_updated_block
          FROM auction_current_params
         WHERE chain_id = ? AND auction_address = ?
        """,
        (event.chain_id, event.auction_address),
    ).fetchone()
    if current_row and int(current_row["last_updated_block"]) > block_number:
        return

    current_params = _raw_params_from_row(current_row)
    snapshot_params = _raw_params_from_snapshot(snapshot)
    merged_params = RawAuctionParams(
        receiver=snapshot_params.receiver if snapshot_params.receiver is not None else current_params.receiver,
        minimum_price_raw=(
            snapshot_params.minimum_price_raw
            if snapshot_params.minimum_price_raw is not None
            else current_params.minimum_price_raw
        ),
        starting_price_raw=(
            snapshot_params.starting_price_raw
            if snapshot_params.starting_price_raw is not None
            else current_params.starting_price_raw
        ),
        step_decay_rate_raw=(
            snapshot_params.step_decay_rate_raw
            if snapshot_params.step_decay_rate_raw is not None
            else current_params.step_decay_rate_raw
        ),
        step_duration_raw=(
            snapshot_params.step_duration_raw
            if snapshot_params.step_duration_raw is not None
            else current_params.step_duration_raw
        ),
        auction_length_raw=(
            snapshot_params.auction_length_raw
            if snapshot_params.auction_length_raw is not None
            else current_params.auction_length_raw
        ),
    )
    extra_params_json = _json_dumps(snapshot.extra_params) if snapshot else "{}"
    if current_row and extra_params_json == "{}":
        extra_params_json = current_row["extra_params_json"]
    param_schema = (
        current_row["param_schema"]
        if current_row and current_row["param_schema"]
        else param_schema_for_version(event.version)
    )
    _persist_current_params(
        conn,
        chain_id=event.chain_id,
        auction_address=event.auction_address,
        param_schema=param_schema,
        raw_params=merged_params,
        extra_params_json=extra_params_json,
        block_number=block_number,
        updated_at=_now(),
    )


def _append_param_history(conn, event, param_key: str, value_text: str | None, value_json: str | None) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO auction_param_history (
            chain_id, auction_address, param_key, value_text, value_json, source_event,
            version, effective_block, tx_hash, log_index
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.chain_id,
            event.auction_address,
            param_key,
            value_text,
            value_json,
            event.event_name,
            event.version,
            event.block_number,
            event.tx_hash,
            event.log_index,
        ),
    )


def _recompute_enabled_tokens(conn, chain_id: int, auction_address: str) -> None:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
          FROM auction_tokens
         WHERE chain_id = ? AND auction_address = ? AND currently_enabled = 1
        """,
        (chain_id, auction_address),
    ).fetchone()
    conn.execute(
        """
        UPDATE auctions
           SET has_enabled_tokens = ?,
               updated_at = ?
         WHERE chain_id = ? AND auction_address = ?
        """,
        (1 if int(row["count"]) > 0 else 0, _now(), chain_id, auction_address),
    )


def _project_deployment(conn, prepared: PreparedEvent) -> None:
    event = prepared.domain_event
    snapshot = prepared.snapshot
    now = _now()
    conn.execute(
        """
        INSERT INTO tracked_auctions (
            chain_id, auction_address, factory_address, version, capability_family,
            discovered_block, discovered_tx_hash, active_flag, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(chain_id, auction_address) DO UPDATE SET
            factory_address = excluded.factory_address,
            version = excluded.version,
            capability_family = excluded.capability_family,
            active_flag = 1,
            updated_at = excluded.updated_at
        """,
        (
            event.chain_id,
            event.auction_address,
            event.address,
            event.version,
            event.capability_family,
            event.block_number,
            event.tx_hash,
            now,
            now,
        ),
    )

    want_token = None
    if snapshot and snapshot.want_token:
        want_token = snapshot.want_token
    elif event.payload.get("want"):
        want_token = event.payload["want"]

    conn.execute(
        """
        INSERT INTO auctions (
            chain_id, auction_address, factory_address, version, capability_family,
            governance, receiver, want_token, has_enabled_tokens, deployment_block,
            latest_lifecycle_block, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
        ON CONFLICT(chain_id, auction_address) DO UPDATE SET
            factory_address = excluded.factory_address,
            version = excluded.version,
            capability_family = excluded.capability_family,
            governance = COALESCE(excluded.governance, auctions.governance),
            receiver = COALESCE(excluded.receiver, auctions.receiver),
            want_token = COALESCE(excluded.want_token, auctions.want_token),
            latest_lifecycle_block = MAX(auctions.latest_lifecycle_block, excluded.latest_lifecycle_block),
            updated_at = excluded.updated_at
        """,
        (
            event.chain_id,
            event.auction_address,
            event.address,
            event.version,
            event.capability_family,
            snapshot.governance if snapshot else None,
            snapshot.receiver if snapshot else None,
            want_token,
            event.block_number,
            event.block_number,
            now,
            now,
        ),
    )
    if snapshot is not None:
        _upsert_current_params(conn, event, snapshot, block_number=event.block_number)


def _project_governance_transferred(conn, prepared: PreparedEvent) -> None:
    event = prepared.domain_event
    new_governance = event.payload.get("newGovernance")
    conn.execute(
        """
        UPDATE auctions
           SET governance = ?,
               latest_lifecycle_block = ?,
               updated_at = ?
         WHERE chain_id = ? AND auction_address = ?
        """,
        (new_governance, event.block_number, _now(), event.chain_id, event.auction_address),
    )


def _project_auction_enabled(conn, prepared: PreparedEvent) -> None:
    event = prepared.domain_event
    from_token = event.payload["from"]
    want_token = event.payload.get("to")
    conn.execute(
        """
        INSERT INTO auction_tokens (
            chain_id, auction_address, from_token, want_token, currently_enabled,
            enabled_at, enabled_at_block, latest_lifecycle_block
        ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
        ON CONFLICT(chain_id, auction_address, from_token) DO UPDATE SET
            want_token = COALESCE(excluded.want_token, auction_tokens.want_token),
            currently_enabled = 1,
            enabled_at = COALESCE(auction_tokens.enabled_at, excluded.enabled_at),
            enabled_at_block = COALESCE(auction_tokens.enabled_at_block, excluded.enabled_at_block),
            disabled_at = NULL,
            disabled_at_block = NULL,
            latest_lifecycle_block = excluded.latest_lifecycle_block
        """,
        (
            event.chain_id,
            event.auction_address,
            from_token,
            want_token,
            event.timestamp,
            event.block_number,
            event.block_number,
        ),
    )
    conn.execute(
        """
        UPDATE auctions
           SET want_token = COALESCE(?, want_token),
               latest_lifecycle_block = ?,
               updated_at = ?
         WHERE chain_id = ? AND auction_address = ?
        """,
        (want_token, event.block_number, _now(), event.chain_id, event.auction_address),
    )
    _recompute_enabled_tokens(conn, event.chain_id, event.auction_address)


def _project_auction_disabled(conn, prepared: PreparedEvent) -> None:
    event = prepared.domain_event
    from_token = event.payload["from"]
    conn.execute(
        """
        UPDATE auction_tokens
           SET currently_enabled = 0,
               disabled_at = ?,
               disabled_at_block = ?,
               latest_lifecycle_block = ?
         WHERE chain_id = ? AND auction_address = ? AND from_token = ?
        """,
        (
            event.timestamp,
            event.block_number,
            event.block_number,
            event.chain_id,
            event.auction_address,
            from_token,
        ),
    )
    conn.execute(
        """
        UPDATE auctions
           SET latest_lifecycle_block = ?,
               updated_at = ?
         WHERE chain_id = ? AND auction_address = ?
        """,
        (event.block_number, _now(), event.chain_id, event.auction_address),
    )
    _recompute_enabled_tokens(conn, event.chain_id, event.auction_address)


def _project_kick(conn, prepared: PreparedEvent) -> None:
    event = prepared.domain_event
    snapshot = prepared.snapshot
    if snapshot is None:
        raise ValueError("AuctionKicked projection requires a hydrated snapshot")
    from_token = _resolve_event_from_token(conn, event)
    round_id = _deterministic_round_id(conn, event)
    event.payload.setdefault("roundId", round_id)
    initial_available_raw = decimal_text(event.payload.get("available")) or "0"
    param_schema = param_schema_for_version(event.version)

    snapshot_params = _raw_params_from_snapshot(snapshot)
    decoded = decode_params(param_schema, snapshot_params)
    auction_length = decoded.auction_length_seconds
    end_at = event.timestamp + auction_length if auction_length is not None else None
    conn.execute(
        """
        INSERT INTO rounds (
            chain_id, auction_address, round_id, from_token, want_token, status, kicked_at,
            scheduled_end_at, end_at, settled_at, initial_available_raw, remaining_available_raw, sold_amount_raw,
            paid_amount_raw, take_count, last_take_at, last_take_price_raw, receiver,
            minimum_price_raw, starting_price_raw, step_decay_rate_raw, step_duration_raw,
            auction_length_raw, minimum_price, starting_price, step_decay_percent,
            step_duration_seconds, auction_length_seconds, snapshot_block, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'live', ?, ?, ?, NULL, ?, ?, '0', NULL, 0, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chain_id, auction_address, round_id) DO NOTHING
        """,
        (
            event.chain_id,
            event.auction_address,
            round_id,
            from_token,
            snapshot.want_token,
            event.timestamp,
            end_at,
            end_at,
            initial_available_raw,
            initial_available_raw,
            snapshot.receiver,
            snapshot.minimum_price_raw,
            snapshot.starting_price_raw,
            snapshot.step_decay_rate_raw,
            snapshot.step_duration_raw,
            snapshot.auction_length_raw,
            decoded.minimum_price,
            decoded.starting_price,
            decoded.step_decay_percent,
            decoded.step_duration_seconds,
            decoded.auction_length_seconds,
            event.block_number,
            _now(),
            _now(),
        ),
    )
    conn.execute(
        """
        UPDATE auctions
           SET want_token = COALESCE(?, want_token),
               receiver = COALESCE(?, receiver),
               latest_lifecycle_block = ?,
               updated_at = ?
         WHERE chain_id = ? AND auction_address = ?
        """,
        (
            snapshot.want_token,
            snapshot.receiver,
            event.block_number,
            _now(),
            event.chain_id,
            event.auction_address,
        ),
    )


PARAM_EVENT_FIELDS = {
    "UpdatedReceiver": ("receiver", "receiver"),
    "UpdatedMinimumPrice": ("minimum_price_raw", "minimumPrice"),
    "UpdatedStartingPrice": ("starting_price_raw", "startingPrice"),
    "UpdatedStepDecayRate": ("step_decay_rate_raw", "stepDecayRate"),
    "UpdatedStepDuration": ("step_duration_raw", "stepDuration"),
}


def _resolve_param_schema(row, event) -> str | None:
    if row and row["param_schema"]:
        return row["param_schema"]
    return param_schema_for_version(event.version)


def _fetch_current_params_row(conn, event):
    return conn.execute(
        """
        SELECT receiver, minimum_price_raw, starting_price_raw, step_decay_rate_raw,
               step_duration_raw, auction_length_raw, extra_params_json, param_schema
          FROM auction_current_params
         WHERE chain_id = ? AND auction_address = ?
        """,
        (event.chain_id, event.auction_address),
    ).fetchone()


def _project_param_event(conn, prepared: PreparedEvent) -> None:
    event = prepared.domain_event
    now = _now()
    if event.event_name == "UpdatedLetCowPeek":
        row = _fetch_current_params_row(conn, event)
        merged = _merge_extra_params(
            row["extra_params_json"] if row else None,
            {"letCowPeek": bool(event.payload["letCowPeek"])},
        )
        _persist_current_params(
            conn,
            chain_id=event.chain_id,
            auction_address=event.auction_address,
            param_schema=_resolve_param_schema(row, event),
            raw_params=_raw_params_from_row(row),
            extra_params_json=merged,
            block_number=event.block_number,
            updated_at=now,
        )
        _append_param_history(conn, event, "letCowPeek", "1" if event.payload["letCowPeek"] else "0", merged)
        return

    column_name, payload_key = PARAM_EVENT_FIELDS[event.event_name]
    value = event.payload[payload_key]
    value_text = value if isinstance(value, str) else decimal_text(value)

    row = _fetch_current_params_row(conn, event)
    raw_params = _raw_params_from_row(row)
    updated_params = RawAuctionParams(
        receiver=value_text if column_name == "receiver" else raw_params.receiver,
        minimum_price_raw=value_text if column_name == "minimum_price_raw" else raw_params.minimum_price_raw,
        starting_price_raw=value_text if column_name == "starting_price_raw" else raw_params.starting_price_raw,
        step_decay_rate_raw=(
            value_text if column_name == "step_decay_rate_raw" else raw_params.step_decay_rate_raw
        ),
        step_duration_raw=value_text if column_name == "step_duration_raw" else raw_params.step_duration_raw,
        auction_length_raw=value_text if column_name == "auction_length_raw" else raw_params.auction_length_raw,
    )
    _persist_current_params(
        conn,
        chain_id=event.chain_id,
        auction_address=event.auction_address,
        param_schema=_resolve_param_schema(row, event),
        raw_params=updated_params,
        extra_params_json=(row["extra_params_json"] if row else "{}"),
        block_number=event.block_number,
        updated_at=now,
    )
    if event.event_name == "UpdatedReceiver":
        conn.execute(
            """
            UPDATE auctions
               SET receiver = ?,
                   latest_lifecycle_block = ?,
                   updated_at = ?
             WHERE chain_id = ? AND auction_address = ?
            """,
            (value_text, event.block_number, now, event.chain_id, event.auction_address),
        )
    else:
        conn.execute(
            """
            UPDATE auctions
               SET latest_lifecycle_block = ?,
                   updated_at = ?
             WHERE chain_id = ? AND auction_address = ?
            """,
            (event.block_number, now, event.chain_id, event.auction_address),
        )
    _append_param_history(conn, event, column_name, value_text, None)


def _project_settled(conn, prepared: PreparedEvent) -> None:
    event = prepared.domain_event
    from_token = event.payload.get("from")
    round_row = conn.execute(
        """
        SELECT round_id, status, settled_at
          FROM rounds
         WHERE chain_id = ?
           AND auction_address = ?
           AND from_token = ?
           AND round_id = (
               SELECT MAX(round_id)
                 FROM rounds
                WHERE chain_id = ?
                  AND auction_address = ?
                  AND from_token = ?
           )
        """,
        (
            event.chain_id,
            event.auction_address,
            from_token,
            event.chain_id,
            event.auction_address,
            from_token,
        ),
    ).fetchone()
    conn.execute(
        """
        UPDATE rounds
           SET status = CASE
                   WHEN remaining_available_raw = '0' THEN 'sold_out'
                   ELSE 'settled'
               END,
               settled_at = ?,
               end_at = COALESCE(end_at, ?),
               updated_at = ?
         WHERE chain_id = ?
           AND auction_address = ?
           AND from_token = ?
           AND round_id = (
               SELECT MAX(round_id)
                 FROM rounds
                WHERE chain_id = ?
                  AND auction_address = ?
                  AND from_token = ?
           )
        """,
        (
            event.timestamp,
            event.timestamp,
            _now(),
            event.chain_id,
            event.auction_address,
            from_token,
            event.chain_id,
            event.auction_address,
            from_token,
        ),
    )
    conn.execute(
        """
        UPDATE auctions
           SET latest_lifecycle_block = ?,
               updated_at = ?
         WHERE chain_id = ? AND auction_address = ?
        """,
        (event.block_number, _now(), event.chain_id, event.auction_address),
    )
    if round_row is not None and (
        str(round_row["status"]) != "settled" or round_row["settled_at"] is None
    ):
        logger.info(
            "round settled chain_id=%d auction=%s round_id=%d settled_at=%d tx=%s",
            event.chain_id,
            event.auction_address,
            int(round_row["round_id"]),
            event.timestamp,
            event.tx_hash,
        )


def _project_swept(conn, prepared: PreparedEvent) -> None:
    event = prepared.domain_event
    from_token = event.payload.get("token")
    if from_token:
        round_row = conn.execute(
            """
            SELECT round_id, status, settled_at, end_at
              FROM rounds
             WHERE chain_id = ?
               AND auction_address = ?
               AND from_token = ?
               AND round_id = (
                   SELECT MAX(round_id)
                     FROM rounds
                    WHERE chain_id = ?
                      AND auction_address = ?
                      AND from_token = ?
               )
            """,
            (
                event.chain_id,
                event.auction_address,
                from_token,
                event.chain_id,
                event.auction_address,
                from_token,
            ),
        ).fetchone()
        if round_row is not None and str(round_row["status"]) == "live" and round_row["settled_at"] is None:
            conn.execute(
                """
                UPDATE rounds
                   SET status = 'settled',
                       settled_at = ?,
                       end_at = CASE
                           WHEN end_at IS NULL OR end_at > ? THEN ?
                           ELSE end_at
                       END,
                       updated_at = ?
                 WHERE chain_id = ?
                   AND auction_address = ?
                   AND from_token = ?
                   AND round_id = ?
                """,
                (
                    event.timestamp,
                    event.timestamp,
                    event.timestamp,
                    _now(),
                    event.chain_id,
                    event.auction_address,
                    from_token,
                    int(round_row["round_id"]),
                ),
            )
            logger.info(
                "round swept chain_id=%d auction=%s round_id=%d swept_at=%d tx=%s",
                event.chain_id,
                event.auction_address,
                int(round_row["round_id"]),
                event.timestamp,
                event.tx_hash,
            )
    conn.execute(
        """
        UPDATE auctions
           SET latest_lifecycle_block = ?,
               updated_at = ?
         WHERE chain_id = ? AND auction_address = ?
        """,
        (event.block_number, _now(), event.chain_id, event.auction_address),
    )


def _take_sequence(conn, event) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
          FROM takes
         WHERE chain_id = ?
           AND auction_address = ?
           AND round_id = ?
        """,
        (
            event.chain_id,
            event.auction_address,
            int(event.payload["roundId"]),
        ),
    ).fetchone()
    return int(row["count"]) + 1


def _project_take(conn, prepared: PreparedEvent) -> None:
    event = prepared.domain_event
    payload = event.payload
    round_id = int(payload["roundId"])
    take_seq = _take_sequence(conn, event)
    amount_taken_raw = decimal_text(payload.get("amountTaken")) or "0"
    amount_paid_raw = decimal_text(payload.get("amountPaid"))
    expected_amount_paid_raw = decimal_text(payload.get("expectedAmountPaid"))
    price_e18 = decimal_text(payload.get("priceE18")) if amount_paid_raw is not None else None

    conn.execute(
        """
        INSERT OR IGNORE INTO takes (
            chain_id, auction_address, round_id, take_seq, tx_hash, tx_index, log_index,
            taker, receiver, from_token, want_token, amount_taken_raw, amount_paid_raw,
            expected_amount_paid_raw, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.chain_id,
            event.auction_address,
            round_id,
            take_seq,
            event.tx_hash,
            event.tx_index,
            event.log_index,
            payload["taker"],
            payload.get("receiver"),
            payload["from"],
            payload.get("to"),
            amount_taken_raw,
            amount_paid_raw,
            expected_amount_paid_raw,
            event.timestamp,
        ),
    )

    round_row = conn.execute(
        """
        SELECT initial_available_raw, sold_amount_raw, paid_amount_raw, paid_sold_amount_raw, status, end_at, settled_at
          FROM rounds
         WHERE chain_id = ? AND auction_address = ? AND round_id = ?
        """,
        (event.chain_id, event.auction_address, round_id),
    ).fetchone()
    if round_row is None:
        raise ValueError(
            f"Take projection requires round {event.chain_id}:{event.auction_address}:{round_id}"
        )

    sold_amount_raw = str(int(round_row["sold_amount_raw"]) + int(amount_taken_raw))
    paid_amount_total = round_row["paid_amount_raw"]
    paid_sold_amount_raw = round_row["paid_sold_amount_raw"]
    if amount_paid_raw is not None:
        paid_amount_total = str(int(paid_amount_total or 0) + int(amount_paid_raw))
        paid_sold_amount_raw = str(int(paid_sold_amount_raw) + int(amount_taken_raw))
    remaining_available_raw = str(
        max(0, int(round_row["initial_available_raw"]) - int(sold_amount_raw))
    )
    round_status = str(round_row["status"])
    round_end_at = int(round_row["end_at"]) if round_row["end_at"] is not None else None
    if remaining_available_raw == "0":
        round_status = "sold_out"
        if round_end_at is None or round_end_at > event.timestamp:
            round_end_at = event.timestamp

    conn.execute(
        """
        UPDATE rounds
           SET sold_amount_raw = ?,
               paid_amount_raw = ?,
               paid_sold_amount_raw = ?,
               paid_take_count = paid_take_count + ?,
               remaining_available_raw = ?,
               status = ?,
               take_count = take_count + 1,
               last_take_at = ?,
               last_take_price_raw = ?,
               end_at = ?,
               updated_at = ?
         WHERE chain_id = ? AND auction_address = ? AND round_id = ?
        """,
        (
            sold_amount_raw,
            paid_amount_total,
            paid_sold_amount_raw,
            int(amount_paid_raw is not None),
            remaining_available_raw,
            round_status,
            event.timestamp,
            price_e18,
            round_end_at,
            _now(),
            event.chain_id,
            event.auction_address,
            round_id,
        ),
    )
    if round_status == "sold_out" and str(round_row["status"]) != "sold_out":
        logger.info(
            "round sold_out chain_id=%d auction=%s round_id=%d closed_at=%d tx=%s",
            event.chain_id,
            event.auction_address,
            round_id,
            event.timestamp,
            event.tx_hash,
        )

    conn.execute(
        """INSERT INTO taker_summary (chain_id, taker, take_count, first_seen_at, last_seen_at)
           VALUES (?, ?, 1, ?, ?)
           ON CONFLICT (chain_id, taker) DO UPDATE SET
               take_count = take_count + 1,
               first_seen_at = MIN(first_seen_at, excluded.first_seen_at),
               last_seen_at = MAX(last_seen_at, excluded.last_seen_at)""",
        (event.chain_id, payload["taker"], event.timestamp, event.timestamp),
    )


def apply_native_event_projections(conn, prepared_events: list[PreparedEvent]) -> None:
    for prepared in prepared_events:
        _upsert_token_metadata(conn, prepared)
        event_name = prepared.domain_event.event_name
        if event_name == "DeployedNewAuction":
            _project_deployment(conn, prepared)
        elif event_name == "GovernanceTransferred":
            _project_governance_transferred(conn, prepared)
        elif event_name == "AuctionEnabled":
            _project_auction_enabled(conn, prepared)
        elif event_name == "AuctionDisabled":
            _project_auction_disabled(conn, prepared)
        elif event_name == "AuctionKicked":
            _project_kick(conn, prepared)
        elif event_name in PARAM_EVENT_FIELDS or event_name == "UpdatedLetCowPeek":
            _project_param_event(conn, prepared)
        elif event_name == "AuctionSettled":
            _project_settled(conn, prepared)
        elif event_name == "AuctionSwept":
            _project_swept(conn, prepared)


def apply_take_event_projections(conn, prepared_events: list[PreparedEvent]) -> None:
    for prepared in prepared_events:
        _upsert_token_metadata(conn, prepared)
        if prepared.domain_event.event_name == "Take":
            _project_take(conn, prepared)


def apply_batch_with_results(conn, prepared_events: list[PreparedEvent]) -> list[PreparedEvent]:
    inserted_events = persist_prepared_events(conn, prepared_events)
    persist_snapshot_facts(conn, inserted_events)
    native_events = [event for event in inserted_events if event.domain_event.event_name != "Take"]
    take_events = [event for event in inserted_events if event.domain_event.event_name == "Take"]
    apply_native_event_projections(conn, native_events)
    apply_take_event_projections(conn, take_events)
    return inserted_events


def apply_batch(conn, prepared_events: list[PreparedEvent]) -> int:
    return len(apply_batch_with_results(conn, prepared_events))


def clear_take_state(conn, chain_id: int) -> None:
    conn.execute("DELETE FROM pricing_capture_queue WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM taker_pricing_summary WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM take_pricing_source WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM round_pricing_source WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM take_pricing WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM round_pricing WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM takes WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM taker_summary WHERE chain_id = ?", (chain_id,))
    conn.execute(
        """
        UPDATE rounds
           SET remaining_available_raw = initial_available_raw,
               sold_amount_raw = '0',
               paid_amount_raw = NULL,
               paid_sold_amount_raw = '0',
               paid_take_count = 0,
               take_count = 0,
               last_take_at = NULL,
               last_take_price_raw = NULL,
               end_at = CASE
                   WHEN settled_at IS NOT NULL THEN COALESCE(end_at, scheduled_end_at)
                   ELSE scheduled_end_at
               END,
               status = CASE
                   WHEN settled_at IS NOT NULL THEN 'settled'
                   ELSE 'live'
               END,
               updated_at = ?
         WHERE chain_id = ?
        """,
        (_now(), chain_id),
    )


def clear_projection_state(conn, chain_id: int) -> None:
    clear_take_state(conn, chain_id)
    conn.execute("DELETE FROM tokens WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM tracked_auctions WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM auction_param_history WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM auction_current_params WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM auction_tokens WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM rounds WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM auctions WHERE chain_id = ?", (chain_id,))


def clear_rebuildable_chain_state(conn, chain_id: int) -> None:
    conn.execute("DELETE FROM tokens WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM tracked_auctions WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM taker_pricing_summary WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM take_pricing_source WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM round_pricing_source WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM take_pricing WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM round_pricing WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM taker_summary WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM takes WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM auction_param_history WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM auction_current_params WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM auction_tokens WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM rounds WHERE chain_id = ?", (chain_id,))
    conn.execute("DELETE FROM auctions WHERE chain_id = ?", (chain_id,))


def reconcile_round_statuses(conn, chain_id: int, confirmed_timestamp: int) -> None:
    expired_rows = list(
        conn.execute(
            """
            SELECT round_id, auction_address, end_at
              FROM rounds
             WHERE chain_id = ?
               AND status = 'live'
               AND settled_at IS NULL
               AND remaining_available_raw <> '0'
               AND end_at IS NOT NULL
               AND end_at < ?
            """,
            (chain_id, confirmed_timestamp),
        ).fetchall()
    )
    conn.execute(
        """
        UPDATE rounds
           SET status = 'settled',
               updated_at = ?
         WHERE chain_id = ?
           AND settled_at IS NOT NULL
           AND remaining_available_raw <> '0'
           AND status <> 'settled'
        """,
        (_now(), chain_id),
    )
    conn.execute(
        """
        UPDATE rounds
           SET end_at = CASE
               WHEN last_take_at IS NOT NULL
                    AND (end_at IS NULL OR end_at > last_take_at)
                    THEN last_take_at
               ELSE end_at
           END,
               updated_at = ?
         WHERE chain_id = ?
           AND remaining_available_raw = '0'
           AND last_take_at IS NOT NULL
           AND (end_at IS NULL OR end_at > last_take_at)
        """,
        (_now(), chain_id),
    )
    conn.execute(
        """
        UPDATE rounds
           SET status = 'sold_out',
               end_at = CASE
                   WHEN end_at IS NULL OR end_at > COALESCE(last_take_at, end_at) THEN last_take_at
                   ELSE end_at
               END,
               updated_at = ?
         WHERE chain_id = ?
           AND remaining_available_raw = '0'
           AND status <> 'sold_out'
        """,
        (_now(), chain_id),
    )
    conn.execute(
        """
        UPDATE rounds
           SET status = 'expired',
               end_at = COALESCE(end_at, scheduled_end_at),
               updated_at = ?
         WHERE chain_id = ?
           AND status = 'live'
           AND settled_at IS NULL
           AND remaining_available_raw <> '0'
           AND end_at IS NOT NULL
           AND end_at < ?
        """,
        (_now(), chain_id, confirmed_timestamp),
    )
    for row in expired_rows:
        logger.info(
            "round expired chain_id=%d auction=%s round_id=%d end_at=%d confirmed_timestamp=%d",
            chain_id,
            row["auction_address"],
            int(row["round_id"]),
            int(row["end_at"]),
            confirmed_timestamp,
        )


def update_sync_state(
    conn,
    *,
    chain_id: int,
    network_name: str,
    latest_rpc_head: int,
    confirmed_head: int,
    last_confirmed_processed: int,
    last_live_processed: int,
    health: str,
    last_error: str | None = None,
    last_reorg_at: int | None = None,
    reorg_count: int | None = None,
    touch_success_at: bool = True,
    observed_head: IndexedBlockRecord | None = None,
    observed_finality: IndexedBlockRecord | None = None,
    finality_mode: str | None = None,
    finality_warning: str | None = None,
) -> None:
    if last_confirmed_processed > last_live_processed:
        raise ValueError("Finalized indexed checkpoint cannot exceed the indexed head")
    previous = conn.execute(
        "SELECT last_confirmed_processed FROM sync_state WHERE chain_id = ?", (chain_id,),
    ).fetchone()
    advanced = previous is None or previous[0] is None or last_confirmed_processed > int(previous[0])
    now = _now() if touch_success_at else None
    conn.execute(
        """
        INSERT INTO sync_state (
            chain_id, network_name, latest_rpc_head, confirmed_head,
            last_confirmed_processed, last_live_processed, last_reorg_at,
            reorg_count, last_success_at, last_error, health
        ) VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, 0), ?, ?, ?)
        ON CONFLICT(chain_id) DO UPDATE SET
            network_name = excluded.network_name,
            latest_rpc_head = excluded.latest_rpc_head,
            confirmed_head = excluded.confirmed_head,
            last_confirmed_processed = excluded.last_confirmed_processed,
            last_live_processed = excluded.last_live_processed,
            last_reorg_at = CASE WHEN ? IS NOT NULL THEN ? ELSE sync_state.last_reorg_at END,
            reorg_count = CASE WHEN ? IS NOT NULL THEN ? ELSE sync_state.reorg_count END,
            last_success_at = COALESCE(?, sync_state.last_success_at),
            last_error = excluded.last_error,
            health = excluded.health
        """,
        (
            chain_id,
            network_name,
            latest_rpc_head,
            confirmed_head,
            last_confirmed_processed,
            last_live_processed,
            last_reorg_at,
            reorg_count,
            now,
            last_error,
            health,
            # ON CONFLICT params for CASE expressions
            last_reorg_at, last_reorg_at,
            reorg_count, reorg_count,
            now,
        ),
    )
    conn.execute(
        """UPDATE sync_state SET
               confirmed_head_hash = COALESCE(?, confirmed_head_hash),
               confirmed_head_timestamp = COALESCE(?, confirmed_head_timestamp),
               latest_rpc_head_timestamp = COALESCE(?, latest_rpc_head_timestamp),
               finality_mode = COALESCE(?, finality_mode),
               finality_warning = CASE WHEN ? THEN ? ELSE finality_warning END,
               last_confirmed_hash = (SELECT block_hash FROM indexed_blocks
                   WHERE chain_id = ? AND block_number = ?),
               last_finality_advance_at = CASE WHEN ? THEN ? ELSE last_finality_advance_at END
           WHERE chain_id = ?""",
        (observed_finality.block_hash if observed_finality else None,
         observed_finality.timestamp if observed_finality else None,
         observed_head.timestamp if observed_head else None, finality_mode,
         observed_head is not None, finality_warning,
         chain_id, last_confirmed_processed, advanced and touch_success_at, now, chain_id),
    )
