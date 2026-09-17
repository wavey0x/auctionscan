from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from .chains import ChainState
from .decode import AbiRegistry
from .hydration import Hydrator
from .polling import chunked, fetch_logs, sort_logs
from .types import DomainEventRecord, PreparedEvent, RawLogRecord, TokenMetadata, normalize_address, normalize_hex
from .versioning import auction_token_key, uses_legacy_auction_id


logger = logging.getLogger(__name__)

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ADDRESS_CHUNK = 100
TOPIC_CHUNK = 100
SWEEP_SELECTOR = "0x01681a62"


def _to_hex(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    value_str = str(value)
    if value_str.startswith("0x"):
        return value_str.lower()
    if len(value_str) == 64 and all(char in "0123456789abcdefABCDEF" for char in value_str):
        return "0x" + value_str.lower()
    return None


def _topic_address(topic_value: Any) -> Optional[str]:
    hex_value = _to_hex(topic_value)
    if not hex_value or len(hex_value) != 66:
        return None
    return normalize_address("0x" + hex_value[-40:])


def _decode_amount(data_value: Any) -> Optional[int]:
    if data_value is None:
        return None
    if isinstance(data_value, (bytes, bytearray)):
        return int.from_bytes(bytes(data_value), byteorder="big")
    data_str = str(data_value)
    if data_str.startswith("0x"):
        return int(data_str, 16)
    return int(data_str, 16)


def _pad_topic_address(address: str) -> str:
    return "0x" + normalize_address(address)[2:].rjust(64, "0")


def _price_e18(amount_paid_raw: int | None, amount_taken_raw: int, from_decimals: int, want_decimals: int) -> Optional[int]:
    if amount_paid_raw is None or amount_taken_raw <= 0:
        return None
    denominator = amount_taken_raw * (10**want_decimals)
    if denominator == 0:
        return None
    return (amount_paid_raw * (10**from_decimals) * (10**18)) // denominator


def find_want_transfer_to_receiver(
    logs: list[Any],
    want_token: str,
    receiver: str,
    target_log_index: Optional[int] = None,
    expected_amount: Optional[int] = None,
) -> tuple[Optional[int], Optional[dict[str, Any]]]:
    want_norm = normalize_address(want_token)
    receiver_norm = normalize_address(receiver)
    candidates: list[dict[str, Any]] = []
    for raw in logs:
        if isinstance(raw, dict):
            address_value = raw.get("address")
            topics = list(raw.get("topics", []))
            data_value = raw.get("data")
            log_index = raw.get("logIndex")
        else:
            address_value = getattr(raw, "address", None)
            topics = list(getattr(raw, "topics", []) or [])
            data_value = getattr(raw, "data", None)
            log_index = getattr(raw, "logIndex", None)
        if address_value is None:
            continue
        address = normalize_address(address_value)
        if address != want_norm or len(topics) < 3:
            continue
        topic0 = _to_hex(topics[0])
        if topic0 != TRANSFER_TOPIC:
            continue
        to_address = _topic_address(topics[2])
        if to_address != receiver_norm:
            continue
        amount = _decode_amount(data_value)
        if amount is None:
            continue
        candidates.append(
            {
                "amount": amount,
                "log_index": log_index if isinstance(log_index, int) else None,
                "from_address": _topic_address(topics[1]),
                "to_address": to_address,
                "log": raw,
            }
        )

    if not candidates:
        return None, None

    def candidate_key(item: dict[str, Any]) -> tuple[int, int, int]:
        amount_diff = abs(item["amount"] - expected_amount) if expected_amount is not None else 0
        if target_log_index is not None and isinstance(item.get("log_index"), int):
            index_diff = abs(item["log_index"] - target_log_index)
        elif isinstance(item.get("log_index"), int):
            index_diff = item["log_index"]
        else:
            index_diff = 2**31
        raw_index = item["log_index"] if isinstance(item.get("log_index"), int) else 2**31
        return amount_diff, index_diff, raw_index

    best = min(candidates, key=candidate_key)
    return best["amount"], best


@dataclass(frozen=True)
class _TakeContext:
    auction_address: str
    round_id: int
    version: str
    capability_family: str
    from_token: str
    want_token: str | None
    receiver: str | None


class TakeDetector:
    def __init__(self, abi_registry: AbiRegistry, hydrator: Hydrator) -> None:
        self.abi_registry = abi_registry
        self.hydrator = hydrator
        self._token_metadata_cache: dict[tuple[int, str, int | None], TokenMetadata] = {}

    def scan_window(
        self,
        chain: ChainState,
        conn,
        *,
        from_block: int,
        to_block: int,
        native_events: list[PreparedEvent] = (),
    ) -> tuple[list[RawLogRecord], list[PreparedEvent]]:
        effective_rows = conn.execute(
            """
            SELECT auction_address, from_token
              FROM auction_tokens
             WHERE chain_id = ?
               AND enabled_at_block <= ?
               AND (disabled_at_block IS NULL OR disabled_at_block >= ?)
             ORDER BY auction_address ASC, from_token ASC
            """,
            (chain.config.chain_id, to_block, from_block),
        ).fetchall()
        effective_pairs = {
            (
                normalize_address(row["auction_address"]),
                normalize_address(row["from_token"]),
            )
            for row in effective_rows
        }
        effective_pairs.update(
            (item.domain_event.auction_address, normalize_address(item.domain_event.payload["from"]))
            for item in native_events
            if item.domain_event.event_name in {"AuctionEnabled", "AuctionKicked"}
            and item.domain_event.payload.get("from")
        )
        if not effective_pairs:
            return [], []
        self._token_metadata_cache.clear()
        auction_to_tokens: dict[str, list[str]] = {}
        token_to_auctions: dict[str, list[str]] = {}
        for auction_address, from_token in sorted(effective_pairs):
            auction_to_tokens.setdefault(auction_address, []).append(from_token)
            token_to_auctions.setdefault(from_token, []).append(auction_address)

        strategy, _planned_calls = self._transfer_scan_plan(
            auction_to_tokens,
            token_to_auctions,
        )
        fetched_logs: list[dict[str, Any]] = []
        if strategy == "matrix":
            for token_chunk in chunked(sorted(token_to_auctions), ADDRESS_CHUNK):
                for auction_chunk in chunked(sorted(auction_to_tokens), TOPIC_CHUNK):
                    fetched_logs.extend(
                        fetch_logs(
                            chain.w3,
                            block_hashes=getattr(getattr(chain, "reader", None), "log_hashes", None),
                            from_block=from_block,
                            to_block=to_block,
                            address=token_chunk,
                            topics=[
                                TRANSFER_TOPIC,
                                [_pad_topic_address(auction) for auction in auction_chunk],
                            ],
                        )
                    )
        elif strategy == "token":
            for from_token, auctions in token_to_auctions.items():
                for topics1 in chunked([_pad_topic_address(auction) for auction in auctions], TOPIC_CHUNK):
                    fetched_logs.extend(
                        fetch_logs(
                            chain.w3,
                            block_hashes=getattr(getattr(chain, "reader", None), "log_hashes", None),
                            from_block=from_block,
                            to_block=to_block,
                            address=from_token,
                            topics=[TRANSFER_TOPIC, topics1],
                        )
                    )
        else:
            for auction_address, tokens in auction_to_tokens.items():
                for token_chunk in chunked(tokens, ADDRESS_CHUNK):
                    fetched_logs.extend(
                        fetch_logs(
                            chain.w3,
                            block_hashes=getattr(getattr(chain, "reader", None), "log_hashes", None),
                            from_block=from_block,
                            to_block=to_block,
                            address=token_chunk,
                            topics=[TRANSFER_TOPIC, _pad_topic_address(auction_address)],
                        )
                    )

        raw_logs: list[RawLogRecord] = []
        seen: set[tuple[str, int]] = set()
        for log in sort_logs(fetched_logs):
            topics = list(log.get("topics", []))
            if len(topics) < 2 or normalize_hex(topics[0]) != TRANSFER_TOPIC:
                continue
            auction_address = _topic_address(topics[1])
            if auction_address is None:
                continue
            from_token = normalize_address(log["address"])
            if (auction_address, from_token) not in effective_pairs:
                continue
            identity = (normalize_hex(log["transactionHash"]), int(log["logIndex"]))
            if identity in seen:
                continue
            seen.add(identity)
            raw_logs.append(self._normalize_transfer_log(chain, log))

        return raw_logs, self._derive_take_events(chain, conn, raw_logs, native_events=native_events)

    def replay_chain(self, chain: ChainState, conn) -> list[PreparedEvent]:
        self._token_metadata_cache.clear()
        rows = conn.execute(
            """
            SELECT *
              FROM chain_logs
             WHERE chain_id = ? AND topic0 = ?
             ORDER BY block_number ASC, tx_index ASC, log_index ASC
            """,
            (chain.config.chain_id, TRANSFER_TOPIC),
        ).fetchall()
        raw_logs = [
            RawLogRecord(
                chain_id=int(row["chain_id"]),
                block_number=int(row["block_number"]),
                block_hash=row["block_hash"],
                tx_hash=row["tx_hash"],
                tx_index=int(row["tx_index"]),
                log_index=int(row["log_index"]),
                address=row["address"],
                topic0=row["topic0"],
                topic1=row["topic1"],
                topic2=row["topic2"],
                topic3=row["topic3"],
                data=row["data"],
                timestamp=int(row["timestamp"]),
            )
            for row in rows
        ]
        total = len(raw_logs)
        logger.info(
            "reproject take replay start chain_id=%d transfer_logs=%d",
            chain.config.chain_id,
            total,
        )
        return self._derive_take_events(
            chain,
            conn,
            raw_logs,
            log_progress=True,
        )

    def _transfer_scan_plan(
        self,
        auction_to_tokens: dict[str, list[str]],
        token_to_auctions: dict[str, list[str]],
    ) -> tuple[str, int]:
        auction_calls = sum(max(1, len(tokens) + ADDRESS_CHUNK - 1) // ADDRESS_CHUNK for tokens in auction_to_tokens.values())
        token_calls = sum(max(1, len(auctions) + TOPIC_CHUNK - 1) // TOPIC_CHUNK for auctions in token_to_auctions.values())
        matrix_calls = (
            max(1, len(token_to_auctions) + ADDRESS_CHUNK - 1)
            // ADDRESS_CHUNK
        ) * (
            max(1, len(auction_to_tokens) + TOPIC_CHUNK - 1)
            // TOPIC_CHUNK
        )
        if matrix_calls < min(auction_calls, token_calls):
            return "matrix", matrix_calls
        if token_calls < auction_calls:
            return "token", token_calls
        return "auction", auction_calls

    def _normalize_transfer_log(self, chain: ChainState, log: dict[str, Any]) -> RawLogRecord:
        if getattr(chain, "reader", None) is not None:
            chain.reader.header(int(log["blockNumber"]), expected_hash=normalize_hex(log["blockHash"]))
        return RawLogRecord(
            chain_id=chain.config.chain_id,
            block_number=int(log["blockNumber"]),
            block_hash=normalize_hex(log["blockHash"]),
            tx_hash=normalize_hex(log["transactionHash"]),
            tx_index=int(log.get("transactionIndex", 0)),
            log_index=int(log["logIndex"]),
            address=normalize_address(log["address"]),
            topic0=normalize_hex(log["topics"][0]) if len(log.get("topics", [])) > 0 else None,
            topic1=normalize_hex(log["topics"][1]) if len(log.get("topics", [])) > 1 else None,
            topic2=normalize_hex(log["topics"][2]) if len(log.get("topics", [])) > 2 else None,
            topic3=normalize_hex(log["topics"][3]) if len(log.get("topics", [])) > 3 else None,
            data=normalize_hex(log.get("data", "0x")),
            timestamp=chain.block_timestamp(int(log["blockNumber"])),
        )

    def _derive_take_events(
        self,
        chain: ChainState,
        conn,
        raw_logs: list[RawLogRecord],
        *,
        log_progress: bool = False,
        native_events: list[PreparedEvent] = (),
    ) -> list[PreparedEvent]:
        prepared: list[PreparedEvent] = []
        total = len(raw_logs)
        for index, raw_log in enumerate(raw_logs, start=1):
            event = self._derive_take_event(chain, conn, raw_log, native_events=native_events)
            if event is not None:
                prepared.append(event)
            if log_progress and (index == total or index % 250 == 0):
                logger.info(
                    "reproject take replay progress chain_id=%d processed=%d/%d progress=%.1f%% detected=%d",
                    chain.config.chain_id,
                    index,
                    total,
                    100.0 if total == 0 else (index * 100.0) / total,
                    len(prepared),
                )
        return prepared

    def _derive_take_event(
        self,
        chain: ChainState,
        conn,
        raw_log: RawLogRecord,
        *,
        native_events: list[PreparedEvent] = (),
    ) -> Optional[PreparedEvent]:
        # Capture even rejected candidates, so later detection fixes can reconsider them.
        transaction = chain.reader.transaction(raw_log)
        receipt = chain.reader.receipt(raw_log)
        input_hex = normalize_hex(transaction.get("input", "0x"))
        tx_selector = input_hex[:10] if len(input_hex) >= 10 else None
        if raw_log.topic0 != TRANSFER_TOPIC or not raw_log.topic1 or not raw_log.topic2:
            return None

        auction_address = _topic_address(raw_log.topic1)
        taker = _topic_address(raw_log.topic2)
        if auction_address is None or taker is None:
            return None

        amount_taken_raw = int(raw_log.data, 16)
        if amount_taken_raw <= 0:
            return None

        if any(item.domain_event.tx_hash == raw_log.tx_hash and item.domain_event.event_name == "AuctionSwept"
               for item in native_events) or self._tx_has_native_event(
            conn,
            chain_id=chain.config.chain_id,
            tx_hash=raw_log.tx_hash,
            event_name="AuctionSwept",
        ):
            return None

        take_context = self._resolve_round_context(
            conn,
            chain_id=chain.config.chain_id,
            auction_address=auction_address,
            from_token=raw_log.address,
            raw_log=raw_log,
            native_events=native_events,
        )
        if take_context is None:
            return None

        from_metadata = self._read_token_metadata(
            chain,
            conn,
            raw_log.address,
            block_number=raw_log.block_number,
        )
        token_metadata: list[TokenMetadata] = [from_metadata]
        want_metadata: TokenMetadata | None = None
        if take_context.want_token:
            want_metadata = self._read_token_metadata(
                chain,
                conn,
                take_context.want_token,
                block_number=raw_log.block_number,
            )
            token_metadata.append(want_metadata)

        matched_amount_raw = None
        matched_meta = None
        matching_method = "unmatched"
        if take_context.want_token and take_context.receiver:
            receipt_logs = list(receipt["logs"])
            matched_amount_raw, matched_meta = find_want_transfer_to_receiver(
                receipt_logs,
                take_context.want_token,
                take_context.receiver,
                raw_log.log_index,
                None,
            )
            if matched_amount_raw is not None:
                matching_method = "receiver_transfer"

        expected_amount_paid_raw = self._estimate_amount_paid_raw(
            chain,
            take_context=take_context,
            amount_taken_raw=amount_taken_raw,
            block_number=raw_log.block_number,
            timestamp=raw_log.timestamp,
        )
        if not self._should_derive_take(tx_selector):
            return None
        if matched_amount_raw is None and expected_amount_paid_raw is not None:
            matching_method = "amount_needed"

        from_decimals = from_metadata.decimals or 0
        want_decimals = want_metadata.decimals if want_metadata else 0
        effective_amount_paid_raw = matched_amount_raw
        if effective_amount_paid_raw is None:
            effective_amount_paid_raw = expected_amount_paid_raw
        price_e18 = _price_e18(
            effective_amount_paid_raw,
            amount_taken_raw,
            from_decimals,
            want_decimals or 0,
        )

        payload = {
            "source": "erc20_transfer",
            "auction": auction_address,
            "roundId": take_context.round_id,
            "taker": taker,
            "receiver": take_context.receiver,
            "from": raw_log.address,
            "to": take_context.want_token,
            "amountTaken": amount_taken_raw,
            "amountPaid": matched_amount_raw,
            "expectedAmountPaid": expected_amount_paid_raw,
            "paymentLogIndex": matched_meta.get("log_index") if matched_meta else None,
            "matchingMethod": matching_method,
            "priceE18": price_e18,
        }
        return PreparedEvent(
            raw_log=raw_log,
            domain_event=DomainEventRecord(
                chain_id=chain.config.chain_id,
                block_number=raw_log.block_number,
                block_hash=raw_log.block_hash,
                tx_hash=raw_log.tx_hash,
                tx_index=raw_log.tx_index,
                log_index=raw_log.log_index,
                event_name="Take",
                address=raw_log.address,
                auction_address=auction_address,
                version=take_context.version,
                capability_family=take_context.capability_family,
                payload=payload,
                timestamp=raw_log.timestamp,
            ),
            token_metadata=tuple(token_metadata),
        )

    def _resolve_round_context(
        self, conn, *, chain_id: int, auction_address: str, from_token: str,
        raw_log: RawLogRecord, native_events: list[PreparedEvent] = (),
    ) -> Optional[_TakeContext]:
        # Event order, not timestamp alone, disambiguates multiple kicks in a block.
        position = (raw_log.block_number, raw_log.tx_index, raw_log.log_index)
        rows = conn.execute(
            """
            SELECT s.*, e.tx_index, e.timestamp, e.capability_family
              FROM round_param_snapshot s JOIN domain_events e
                ON e.chain_id = s.chain_id AND e.tx_hash = s.snapshot_tx_hash
               AND e.log_index = s.snapshot_log_index AND e.event_name = 'AuctionKicked'
             WHERE s.chain_id = ? AND s.auction_address = ?
            """, (chain_id, auction_address),
        ).fetchall()
        kicks = {
            (str(row["snapshot_tx_hash"]), int(row["snapshot_log_index"])): {
                "position": (int(row["snapshot_block"]), int(row["tx_index"]), int(row["snapshot_log_index"])),
                "from": row["from_token"], "want": row["want_token"], "receiver": row["receiver"],
                "version": row["version"], "family": row["capability_family"],
                "timestamp": int(row["timestamp"]), "length": row["auction_length_raw"],
            }
            for row in rows
        }
        for prepared in native_events:
            event = prepared.domain_event
            if event.auction_address != auction_address or event.event_name != "AuctionKicked":
                continue
            snapshot = prepared.snapshot
            if snapshot is None:
                raise ValueError("Kick context requires a captured snapshot")
            token = event.payload.get("from")
            if token is None and event.payload.get("auctionId"):
                enabled = [item.domain_event for item in native_events
                           if item.domain_event.auction_address == auction_address
                           and item.domain_event.event_name == "AuctionEnabled"
                           and item.domain_event.payload.get("auctionId") == event.payload["auctionId"]
                           and (item.domain_event.block_number, item.domain_event.tx_index, item.domain_event.log_index)
                           < (event.block_number, event.tx_index, event.log_index)]
                if enabled:
                    token = max(enabled, key=lambda item: (item.block_number, item.tx_index, item.log_index)).payload["from"]
                else:
                    from .projections import _resolve_event_from_token
                    token = _resolve_event_from_token(conn, event)
            kicks[(event.tx_hash, event.log_index)] = {
                "position": (event.block_number, event.tx_index, event.log_index),
                "from": token, "want": snapshot.want_token, "receiver": snapshot.receiver,
                "version": event.version, "family": event.capability_family,
                "timestamp": event.timestamp, "length": snapshot.auction_length_raw,
            }
        selected = None
        for round_id, kick in enumerate(sorted(kicks.values(), key=lambda item: item["position"]), start=1):
            if kick["position"] > position or kick["from"] != from_token:
                continue
            if kick["length"] is not None and raw_log.timestamp > kick["timestamp"] + int(kick["length"]):
                continue
            selected = _TakeContext(
                auction_address=auction_address, round_id=round_id,
                version=kick["version"], capability_family=kick["family"], from_token=from_token,
                want_token=kick["want"], receiver=kick["receiver"],
            )
        return selected

    def _read_token_metadata(
        self,
        chain: ChainState,
        conn,
        token_address: str,
        *,
        block_number: int | None,
    ) -> TokenMetadata:
        cache_key = (chain.config.chain_id, token_address, block_number)
        cached = self._token_metadata_cache.get(cache_key)
        if cached is not None:
            return cached

        metadata = self.hydrator.read_token_metadata(chain, token_address, block_number=block_number)
        if metadata.decimals is None:
            raise ValueError(f"Missing token decimals for {token_address} at {block_number}")
        self._token_metadata_cache[cache_key] = metadata
        return metadata

    def _tx_has_native_event(
        self,
        conn,
        *,
        chain_id: int,
        tx_hash: str,
        event_name: str,
    ) -> bool:
        row = conn.execute(
            """
            SELECT 1
              FROM domain_events
             WHERE chain_id = ?
               AND tx_hash = ?
               AND event_name = ?
             LIMIT 1
            """,
            (chain_id, tx_hash, event_name),
        ).fetchone()
        return row is not None

    def _should_derive_take(self, tx_selector: str | None) -> bool:
        if tx_selector == SWEEP_SELECTOR:
            return False
        # Keep broader transfer-based inference enabled because legitimate auction
        # executions can arrive through non-direct call paths (for example solver
        # settlements) and would be missed by a strict selector allowlist.
        return True

    def _estimate_amount_paid_raw(
        self,
        chain: ChainState,
        *,
        take_context: _TakeContext,
        amount_taken_raw: int,
        block_number: int,
        timestamp: int,
    ) -> Optional[int]:
        contract = self.abi_registry.auction_contract(
            chain.w3, take_context.auction_address, take_context.version,
        )
        if uses_legacy_auction_id(take_context.version) and take_context.want_token is None:
            return None
        token_key = auction_token_key(
            chain.w3, version=take_context.version, auction_address=take_context.auction_address,
            from_token=take_context.from_token, want_token=take_context.want_token,
        )
        return chain.reader.call(
            contract.functions.getAmountNeeded(token_key, amount_taken_raw, timestamp),
            block_number, optional=True,
        )
