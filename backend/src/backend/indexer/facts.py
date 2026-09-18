"""Chain fact persistence and maintenance, using the caller's writer transaction."""

from __future__ import annotations

import json
import time

from .auction_params import param_schema_for_version
from .types import AuctionSnapshot, IndexedBlockRecord, PreparedEvent


def _now() -> int:
    return int(time.time())


def _json_dumps(payload) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _insert_raw_log(conn, prepared: PreparedEvent) -> None:
    raw = prepared.raw_log
    _insert_raw_log_record(conn, raw)



def _insert_raw_log_record(conn, raw) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO chain_logs (
            chain_id, block_number, block_hash, tx_hash, tx_index, log_index,
            address, topic0, topic1, topic2, topic3, data, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            raw.chain_id,
            raw.block_number,
            raw.block_hash,
            raw.tx_hash,
            raw.tx_index,
            raw.log_index,
            raw.address,
            raw.topic0,
            raw.topic1,
            raw.topic2,
            raw.topic3,
            raw.data,
            raw.timestamp,
        ),
    )



def _insert_domain_event(conn, prepared: PreparedEvent) -> bool:
    event = prepared.domain_event
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO domain_events (
            chain_id, block_number, block_hash, tx_hash, tx_index, log_index,
            event_name, address, auction_address, version, capability_family,
            payload_json, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.chain_id,
            event.block_number,
            event.block_hash,
            event.tx_hash,
            event.tx_index,
            event.log_index,
            event.event_name,
            event.address,
            event.auction_address,
            event.version,
            event.capability_family,
            _json_dumps(event.payload),
            event.timestamp,
        ),
    )
    return cursor.rowcount > 0



def _persist_deploy_snapshot_fact(conn, event, snapshot: AuctionSnapshot) -> None:
    param_schema = param_schema_for_version(event.version)
    conn.execute(
        """
        INSERT OR IGNORE INTO auction_snapshot_facts (
            chain_id, auction_address, snapshot_kind, round_id, version, param_schema,
            block_number, tx_hash, log_index, block_hash, want_token, governance, receiver,
            minimum_price_raw, starting_price_raw, step_decay_rate_raw, step_duration_raw,
            auction_length_raw, extra_params_json, created_at
        ) VALUES (?, ?, 'deploy', NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.chain_id,
            event.auction_address,
            event.version,
            param_schema,
            event.block_number,
            event.tx_hash,
            event.log_index,
            event.block_hash,
            snapshot.want_token,
            snapshot.governance,
            snapshot.receiver,
            snapshot.minimum_price_raw,
            snapshot.starting_price_raw,
            snapshot.step_decay_rate_raw,
            snapshot.step_duration_raw,
            snapshot.auction_length_raw,
            _json_dumps(snapshot.extra_params),
            _now(),
        ),
    )



def _deterministic_round_id(conn, event) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
          FROM domain_events
         WHERE chain_id = ?
           AND auction_address = ?
           AND event_name = 'AuctionKicked'
           AND (
                block_number < ?
                OR (block_number = ? AND tx_index < ?)
                OR (block_number = ? AND tx_index = ? AND log_index <= ?)
           )
        """,
        (
            event.chain_id,
            event.auction_address,
            event.block_number,
            event.block_number,
            event.tx_index,
            event.block_number,
            event.tx_index,
            event.log_index,
        ),
    ).fetchone()
    return int(row["count"])



def _resolve_event_from_token(conn, event) -> str:
    direct = event.payload.get("from")
    if direct:
        return direct

    auction_id = event.payload.get("auctionId")
    if not auction_id:
        raise KeyError("from")

    rows = conn.execute(
        """
        SELECT payload_json
          FROM domain_events
         WHERE chain_id = ?
           AND auction_address = ?
           AND event_name = 'AuctionEnabled'
           AND (
                block_number < ?
                OR (block_number = ? AND tx_index < ?)
                OR (block_number = ? AND tx_index = ? AND log_index < ?)
           )
         ORDER BY block_number DESC, tx_index DESC, log_index DESC
        """,
        (
            event.chain_id,
            event.auction_address,
            event.block_number,
            event.block_number,
            event.tx_index,
            event.block_number,
            event.tx_index,
            event.log_index,
        ),
    ).fetchall()
    for row in rows:
        payload = json.loads(row["payload_json"])
        if payload.get("auctionId") == auction_id and payload.get("from"):
            return payload["from"]

    raise KeyError("from")



def _persist_kick_snapshot_fact(conn, event, snapshot, round_id, from_token) -> None:
    param_schema = param_schema_for_version(event.version)
    conn.execute(
        """
        INSERT INTO round_param_snapshot (
            chain_id, auction_address, round_id, from_token, want_token, version,
            snapshot_block, snapshot_tx_hash, snapshot_log_index, block_hash, param_schema, receiver,
            minimum_price_raw, starting_price_raw, step_decay_rate_raw,
            step_duration_raw, auction_length_raw, extra_params_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chain_id, auction_address, round_id) DO NOTHING
        """,
        (
            event.chain_id,
            event.auction_address,
            round_id,
            from_token,
            snapshot.want_token,
            event.version,
            event.block_number,
            event.tx_hash,
            event.log_index,
            event.block_hash,
            param_schema,
            snapshot.receiver,
            snapshot.minimum_price_raw,
            snapshot.starting_price_raw,
            snapshot.step_decay_rate_raw,
            snapshot.step_duration_raw,
            snapshot.auction_length_raw,
            _json_dumps(snapshot.extra_params),
            _now(),
        ),
    )



def persist_raw_logs(conn, raw_logs) -> int:
    inserted = 0
    for raw in raw_logs:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO chain_logs (
                chain_id, block_number, block_hash, tx_hash, tx_index, log_index,
                address, topic0, topic1, topic2, topic3, data, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw.chain_id,
                raw.block_number,
                raw.block_hash,
                raw.tx_hash,
                raw.tx_index,
                raw.log_index,
                raw.address,
                raw.topic0,
                raw.topic1,
                raw.topic2,
                raw.topic3,
                raw.data,
                raw.timestamp,
            ),
        )
        inserted += cursor.rowcount
    return inserted



def persist_prepared_events(conn, prepared_events: list[PreparedEvent]) -> list[PreparedEvent]:
    inserted: list[PreparedEvent] = []
    for prepared in prepared_events:
        _insert_raw_log(conn, prepared)
        if not _insert_domain_event(conn, prepared):
            continue
        inserted.append(prepared)
    return inserted



def upsert_indexed_blocks(conn, blocks: list[IndexedBlockRecord]) -> None:
    if not blocks:
        return
    conn.executemany(
        """
        INSERT INTO indexed_blocks (
            chain_id, block_number, block_hash, parent_hash, timestamp
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(chain_id, block_number) DO UPDATE SET
            block_hash = excluded.block_hash,
            parent_hash = excluded.parent_hash,
            timestamp = excluded.timestamp
        """,
        [
            (
                block.chain_id,
                block.block_number,
                block.block_hash,
                block.parent_hash,
                block.timestamp,
            )
            for block in blocks
        ],
    )



def load_indexed_blocks(
    conn,
    *,
    chain_id: int,
    from_block: int | None = None,
    to_block: int | None = None,
    descending: bool = False,
):
    clauses = ["chain_id = ?"]
    params: list[int] = [chain_id]
    if from_block is not None:
        clauses.append("block_number >= ?")
        params.append(from_block)
    if to_block is not None:
        clauses.append("block_number <= ?")
        params.append(to_block)
    order = "DESC" if descending else "ASC"
    sql = f"""
        SELECT chain_id, block_number, block_hash, parent_hash, timestamp
          FROM indexed_blocks
         WHERE {" AND ".join(clauses)}
         ORDER BY block_number {order}
    """
    return list(conn.execute(sql, tuple(params)).fetchall())



def delete_fact_blocks_above(conn, *, chain_id: int, ancestor_block: int) -> None:
    conn.execute("DELETE FROM rpc_observations WHERE chain_id = ? AND block_number > ?", (chain_id, ancestor_block))
    conn.execute(
        "DELETE FROM chain_logs WHERE chain_id = ? AND block_number > ?",
        (chain_id, ancestor_block),
    )
    conn.execute(
        "DELETE FROM domain_events WHERE chain_id = ? AND block_number > ?",
        (chain_id, ancestor_block),
    )
    conn.execute(
        "DELETE FROM round_param_snapshot WHERE chain_id = ? AND snapshot_block > ?",
        (chain_id, ancestor_block),
    )
    conn.execute(
        "DELETE FROM auction_snapshot_facts WHERE chain_id = ? AND block_number > ?",
        (chain_id, ancestor_block),
    )
    conn.execute(
        "DELETE FROM indexed_blocks WHERE chain_id = ? AND block_number > ?",
        (chain_id, ancestor_block),
    )



def persist_snapshot_facts(conn, prepared_events: list[PreparedEvent]) -> None:
    for prepared in prepared_events:
        event, snapshot = prepared.domain_event, prepared.snapshot
        if snapshot is None:
            continue
        if event.event_name == "DeployedNewAuction":
            _persist_deploy_snapshot_fact(conn, event, snapshot)
        elif event.event_name == "AuctionKicked":
            _persist_kick_snapshot_fact(
                conn, event, snapshot, _deterministic_round_id(conn, event), _resolve_event_from_token(conn, event),
            )


def delete_derived_take_events(conn, chain_id: int) -> None:
    """Explicit maintenance regenerates takes; native event facts remain intact."""
    conn.execute("DELETE FROM domain_events WHERE chain_id = ? AND event_name = 'Take'", (chain_id,))
