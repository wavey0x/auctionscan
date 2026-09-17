"""Reconstruct projection inputs from local facts through an offline reader."""

from __future__ import annotations

import json
import logging
from dataclasses import replace

from .chains import ChainState
from .hydration import Hydrator
from .observations import MissingObservation
from .types import (
    AuctionSnapshot,
    DomainEventRecord,
    PreparedEvent,
    normalize_address,
    prepared_event_from_domain_row,
)


logger = logging.getLogger(__name__)


def load_native_events(conn, chain: ChainState, hydrator: Hydrator) -> list[PreparedEvent]:
    rows = list(
        conn.execute(
            """
            SELECT *
              FROM domain_events
             WHERE chain_id = ? AND event_name != 'Take'
             ORDER BY block_number ASC, tx_index ASC, log_index ASC
            """,
            (chain.config.chain_id,),
        ).fetchall()
    )
    total = len(rows)
    logger.info(
        "reproject native replay start network=%s chain_id=%d events=%d",
        chain.config.name,
        chain.config.chain_id,
        total,
    )
    prepared: list[PreparedEvent] = []
    for index, row in enumerate(rows, start=1):
        prepared.append(prepared_from_domain_event_row(conn, chain, hydrator, row))
        if index == total or index % 250 == 0:
            logger.info(
                "reproject native replay progress network=%s chain_id=%d processed=%d/%d progress=%.1f%%",
                chain.config.name,
                chain.config.chain_id,
                index,
                total,
                100.0 if total == 0 else (index * 100.0) / total,
            )
    return prepared


def load_take_events(conn, chain: ChainState, hydrator: Hydrator) -> list[PreparedEvent]:
    rows = list(
        conn.execute(
            """
            SELECT *
              FROM domain_events
             WHERE chain_id = ? AND event_name = 'Take'
             ORDER BY block_number ASC, tx_index ASC, log_index ASC
            """,
            (chain.config.chain_id,),
        ).fetchall()
    )
    return [prepared_from_domain_event_row(conn, chain, hydrator, row) for row in rows]


def _snapshot_from_fact_row(row) -> AuctionSnapshot | None:
    if row is None:
        return None
    extra_params = json.loads(row["extra_params_json"]) if row["extra_params_json"] else {}
    return AuctionSnapshot(
        chain_id=int(row["chain_id"]),
        auction_address=normalize_address(row["auction_address"]),
        block_number=int(row["block_number"]),
        want_token=normalize_address(row["want_token"]) if row["want_token"] else None,
        governance=normalize_address(row["governance"])
        if "governance" in row.keys() and row["governance"]
        else None,
        receiver=normalize_address(row["receiver"]) if row["receiver"] else None,
        starting_price_raw=row["starting_price_raw"],
        minimum_price_raw=row["minimum_price_raw"],
        step_decay_rate_raw=row["step_decay_rate_raw"],
        step_duration_raw=row["step_duration_raw"],
        auction_length_raw=row["auction_length_raw"],
        extra_params=extra_params,
    )


def _load_persisted_deploy_snapshot(conn, domain_event: DomainEventRecord) -> AuctionSnapshot | None:
    row = conn.execute(
        """
        SELECT chain_id, auction_address, block_number, want_token, governance, receiver,
               minimum_price_raw, starting_price_raw, step_decay_rate_raw, step_duration_raw,
               auction_length_raw, extra_params_json
          FROM auction_snapshot_facts
         WHERE chain_id = ?
           AND tx_hash = ?
           AND log_index = ?
           AND snapshot_kind = 'deploy' AND block_hash = ?
        """,
        (domain_event.chain_id, domain_event.tx_hash, domain_event.log_index, domain_event.block_hash),
    ).fetchone()
    return _snapshot_from_fact_row(row)


def _load_persisted_round_snapshot(conn, domain_event: DomainEventRecord) -> AuctionSnapshot | None:
    row = conn.execute(
        """
        SELECT chain_id, auction_address, snapshot_block AS block_number, want_token, receiver,
               minimum_price_raw, starting_price_raw, step_decay_rate_raw, step_duration_raw,
               auction_length_raw, extra_params_json
          FROM round_param_snapshot
         WHERE chain_id = ?
           AND snapshot_tx_hash = ?
           AND snapshot_log_index = ? AND block_hash = ?
        """,
        (domain_event.chain_id, domain_event.tx_hash, domain_event.log_index, domain_event.block_hash),
    ).fetchone()
    return _snapshot_from_fact_row(row)


def prepared_from_domain_event_row(conn, chain: ChainState, hydrator: Hydrator, row) -> PreparedEvent:
    base = prepared_event_from_domain_row(row)
    event = base.domain_event
    chain.reader.header(event.block_number, expected_hash=event.block_hash)
    snapshot = None
    if event.event_name in {"DeployedNewAuction", "AuctionKicked"}:
        if event.event_name == "DeployedNewAuction":
            snapshot = _load_persisted_deploy_snapshot(conn, event)
        else:
            snapshot = _load_persisted_round_snapshot(conn, event)
        if snapshot is None:
            raise MissingObservation(
                f"Missing {event.event_name} snapshot for {event.tx_hash}:{event.log_index}; run observation backfill"
            )
    prepared = replace(base, snapshot=snapshot)
    return replace(prepared, token_metadata=hydrator.read_event_token_metadata(chain, prepared))
