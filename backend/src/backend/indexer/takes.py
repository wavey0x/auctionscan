from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from .chains import ChainState
from .decode import AbiRegistry
from .hydration import Hydrator
from .polling import chunked, fetch_logs, sort_logs
from .types import DomainEventRecord, PreparedEvent, RawLogRecord, TokenMetadata, normalize_address, normalize_hex
from .versioning import auction_token_key, protocol_for_version, uses_legacy_auction_id


logger = logging.getLogger(__name__)

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
# Curve burner: Taken(token indexed, caller indexed, receiver, amount_out, payment, remaining_balance)
CURVE_TAKEN_TOPIC = "0xb3ec1b9819bd7acdc5dced75778ce2510829c094f1ab60da8dc13f1780371d09"
# Curve burner: Recovered(token indexed, amount)
CURVE_RECOVERED_TOPIC = "0x8c1256b8896378cd5044f80c202f9772b9d77dc85c8a6eb51967210b09bfaa28"
# CoW Protocol's GPv2Settlement, at this address on every chain it serves.
COW_SETTLEMENT = "0x9008d19f58aabd9ed0d60971565aa8510560ab41"
COW_TRADE_TOPIC = "0xa07a543ab8a018198e99ca0184c93fe9050a79400a0a723441f84de1d972cc17"
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


def _log_words(raw) -> list[int]:
    data = _to_hex(raw.get("data")) or "0x"
    return [int(data[2 + offset:66 + offset], 16) for offset in range(0, len(data) - 2, 64)]


def _unclaimed_logs(logs: list[Any], *, address: str, topic0: str, claimed: set[int]):
    """Logs one contract emitted with this signature, in receipt order, that no fill has claimed."""
    address = normalize_address(address)
    for raw in logs:
        topics = [_to_hex(topic) for topic in raw.get("topics", [])]
        log_index = raw.get("logIndex")
        if (normalize_address(raw["address"]) == address and topics and topics[0] == topic0
                and isinstance(log_index, int) and log_index not in claimed):
            yield raw, topics, log_index


def find_curve_taken(
    logs: list[Any], *, auction: str, token: str, amount_taken: int, transfer_log_index: int, claimed: set[int],
) -> Optional[dict[str, Any]]:
    """The burner's Taken log for a native take of this transfer.

    A native take transfers the lot, then logs Taken(token, caller, receiver,
    amount_out, payment, remaining_balance): the caller paid, and what remains
    is the lot's own availability after the fill.
    """
    token_topic = _pad_topic_address(token)
    for raw, topics, log_index in _unclaimed_logs(logs, address=auction, topic0=CURVE_TAKEN_TOPIC, claimed=claimed):
        words = _log_words(raw)
        if log_index > transfer_log_index and len(topics) >= 3 and topics[1] == token_topic \
                and len(words) >= 4 and words[1] == amount_taken:
            return {"log_index": log_index, "caller": _topic_address(topics[2]), "payment": words[2], "remaining": words[3]}
    return None


def find_cow_trade(
    logs: list[Any], *, owner: str, sell_token: str, buy_token: str | None, sell_amount: int, claimed: set[int],
) -> Optional[dict[str, Any]]:
    """The CoW settlement's Trade for an order the auction owns, selling this transfer.

    Trade(owner indexed, sellToken, buyToken, sellAmount, buyAmount, feeAmount, orderUid):
    buyAmount is what the order's receiver was paid.
    """
    owner_topic = _pad_topic_address(owner)
    for raw, topics, log_index in _unclaimed_logs(logs, address=COW_SETTLEMENT, topic0=COW_TRADE_TOPIC, claimed=claimed):
        words = _log_words(raw)
        if len(topics) < 2 or topics[1] != owner_topic or len(words) < 4:
            continue
        if normalize_address(f"0x{words[0]:040x}") != normalize_address(sell_token) or words[2] != sell_amount:
            continue
        if buy_token is not None and normalize_address(f"0x{words[1]:040x}") != normalize_address(buy_token):
            continue
        return {"log_index": log_index, "payment": words[3]}
    return None


def is_curve_recovery(logs: list[Any], *, auction: str, token: str, amount: int) -> bool:
    """Whether the owner's recovery, not a fill, moved this amount of the lot out."""
    token_topic = _pad_topic_address(token)
    return any(
        len(topics) >= 2 and topics[1] == token_topic and _log_words(raw)[:1] == [amount]
        for raw, topics, _index in _unclaimed_logs(logs, address=auction, topic0=CURVE_RECOVERED_TOPIC, claimed=set())
    )


@dataclass(frozen=True)
class _LotWindow:
    starts_at: int
    version: str
    capability_family: str
    want_token: str | None
    receiver: str | None


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
        self._auction_versions: dict[tuple[int, str], str | None] = {}
        # Receipt logs each fill has claimed as its payment, so two cannot share one.
        self._claimed_logs: dict[str, set[int]] = {}

    def _reset_caches(self) -> None:
        self._token_metadata_cache.clear()
        self._auction_versions.clear()
        self._claimed_logs.clear()

    def _auction_version(self, conn, chain_id: int, auction_address: str, native_events=()) -> str | None:
        key = (chain_id, auction_address)
        if key not in self._auction_versions:
            version = next((item.domain_event.version for item in native_events
                            if item.domain_event.auction_address == auction_address), None)
            if version is None:
                row = conn.execute(
                    """
                    SELECT version FROM round_param_snapshot WHERE chain_id = ? AND auction_address = ?
                    UNION ALL
                    SELECT version FROM tracked_auctions WHERE chain_id = ? AND auction_address = ?
                    LIMIT 1
                    """,
                    (chain_id, auction_address, chain_id, auction_address),
                ).fetchone()
                version = row["version"] if row is not None else None
            self._auction_versions[key] = version
        return self._auction_versions[key]

    def _is_curve(self, conn, chain_id: int, auction_address: str, native_events=()) -> bool:
        return protocol_for_version(self._auction_version(conn, chain_id, auction_address, native_events)) == "curve"

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
            SELECT at.auction_address, at.from_token, ta.version
              FROM auction_tokens at
              LEFT JOIN tracked_auctions ta
                ON ta.chain_id = at.chain_id AND ta.auction_address = at.auction_address
             WHERE at.chain_id = ?
               AND at.enabled_at_block <= ?
               AND (at.disabled_at_block IS NULL OR at.disabled_at_block >= ?)
             ORDER BY at.auction_address ASC, at.from_token ASC
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
        versions = {normalize_address(row["auction_address"]): row["version"] for row in effective_rows}
        for item in native_events:
            event = item.domain_event
            versions[event.auction_address] = event.version
            if event.event_name in {"AuctionEnabled", "AuctionKicked"} and event.payload.get("from"):
                effective_pairs.add((event.auction_address, normalize_address(event.payload["from"])))
        if not effective_pairs:
            return [], []
        self._reset_caches()
        # A Curve burner sells any fee token, so its token list is long and
        # grows weekly: scan its outgoing transfers by sender alone.
        curve_auctions = sorted({
            auction for auction, _token in effective_pairs if protocol_for_version(versions.get(auction)) == "curve"
        })
        auction_to_tokens: dict[str, list[str]] = {}
        token_to_auctions: dict[str, list[str]] = {}
        for auction_address, from_token in sorted(effective_pairs):
            if auction_address in curve_auctions:
                continue
            auction_to_tokens.setdefault(auction_address, []).append(from_token)
            token_to_auctions.setdefault(from_token, []).append(auction_address)

        fetched_logs: list[dict[str, Any]] = []
        for auction_chunk in chunked(curve_auctions, TOPIC_CHUNK):
            fetched_logs.extend(
                fetch_logs(
                    chain.w3,
                    block_hashes=getattr(getattr(chain, "reader", None), "log_hashes", None),
                    from_block=from_block,
                    to_block=to_block,
                    topics=[TRANSFER_TOPIC, [_pad_topic_address(auction) for auction in auction_chunk]],
                )
            )
        strategy = None
        if auction_to_tokens:
            strategy, _planned_calls = self._transfer_scan_plan(
                auction_to_tokens,
                token_to_auctions,
            )
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
        elif strategy == "auction":
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
        self._reset_caches()
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
        auction_calls = sum(max(1, -(-len(tokens) // ADDRESS_CHUNK)) for tokens in auction_to_tokens.values())
        token_calls = sum(max(1, -(-len(auctions) // TOPIC_CHUNK)) for auctions in token_to_auctions.values())
        matrix_calls = max(1, -(-len(token_to_auctions) // ADDRESS_CHUNK)) * max(
            1, -(-len(auction_to_tokens) // TOPIC_CHUNK)
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
        # Versions and claims depend on this call's native events and receipts.
        self._auction_versions.clear()
        self._claimed_logs.clear()
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
        if not self._should_derive_take(tx_selector):
            return None
        if raw_log.topic0 != TRANSFER_TOPIC or not raw_log.topic1 or not raw_log.topic2:
            return None

        auction_address = _topic_address(raw_log.topic1)
        taker = _topic_address(raw_log.topic2)
        if auction_address is None or taker is None:
            return None

        amount_taken_raw = int(raw_log.data, 16)
        if amount_taken_raw <= 0:
            return None

        if self._is_curve(conn, chain.config.chain_id, auction_address, native_events):
            return self._derive_curve_take(
                chain, conn, raw_log, auction_address=auction_address, amount_taken_raw=amount_taken_raw,
                transaction=transaction, receipt=receipt, native_events=native_events,
            )

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

    def _derive_curve_take(
        self, chain: ChainState, conn, raw_log: RawLogRecord, *, auction_address: str, amount_taken_raw: int,
        transaction, receipt, native_events: list[PreparedEvent],
    ) -> Optional[PreparedEvent]:
        """A Curve lot transfer, read from what the receipt states about it.

        The payload names the lot's window rather than a round number: the
        projection resolves the round once its kicks are projected, so round
        numbers are assigned in one place.
        """
        logs = list(receipt["logs"])
        if is_curve_recovery(logs, auction=auction_address, token=raw_log.address, amount=amount_taken_raw):
            return None
        window = self._lot_window(
            conn, chain_id=chain.config.chain_id, auction_address=auction_address,
            token=raw_log.address, timestamp=raw_log.timestamp, native_events=native_events,
        )
        if window is None:
            return None
        claimed = self._claimed_logs.setdefault(raw_log.tx_hash, set())
        taken = find_curve_taken(
            logs, auction=auction_address, token=raw_log.address, amount_taken=amount_taken_raw,
            transfer_log_index=raw_log.log_index, claimed=claimed,
        )
        if taken is not None:
            # A native take: its Taken log states who paid, how much, and what remains.
            matching_method, payment_log_index = "taken_event", taken["log_index"]
            amount_paid_raw, taker, remaining = taken["payment"], taken["caller"], taken["remaining"]
        else:
            # A settlement adapter filled a signed order. The transfer's
            # recipient is the protocol's settlement, so the fill is credited to
            # the account that submitted it. What remains is read from the lot.
            trade = find_cow_trade(
                logs, owner=auction_address, sell_token=raw_log.address, buy_token=window.want_token,
                sell_amount=amount_taken_raw, claimed=claimed,
            )
            matching_method = "cow_trade" if trade else "unmatched"
            payment_log_index = trade["log_index"] if trade else None
            amount_paid_raw = trade["payment"] if trade else None
            taker = normalize_address(transaction["from"])
            remaining = self._read_curve_available(chain, window, auction_address, raw_log)
        if payment_log_index is not None:
            claimed.add(payment_log_index)

        from_metadata = self._read_token_metadata(chain, conn, raw_log.address, block_number=raw_log.block_number)
        token_metadata = [from_metadata]
        want_metadata = None
        if window.want_token:
            want_metadata = self._read_token_metadata(chain, conn, window.want_token, block_number=raw_log.block_number)
            token_metadata.append(want_metadata)
        payload = {
            "source": "erc20_transfer",
            "auction": auction_address,
            "window": window.starts_at,
            "taker": taker,
            "receiver": window.receiver,
            "from": raw_log.address,
            "to": window.want_token,
            "amountTaken": amount_taken_raw,
            "amountPaid": amount_paid_raw,
            "expectedAmountPaid": None,
            "paymentLogIndex": payment_log_index,
            "matchingMethod": matching_method,
            "priceE18": _price_e18(
                amount_paid_raw, amount_taken_raw, from_metadata.decimals or 0,
                (want_metadata.decimals if want_metadata else 0) or 0,
            ),
            "remainingAvailable": remaining,
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
                version=window.version,
                capability_family=window.capability_family,
                payload=payload,
                timestamp=raw_log.timestamp,
            ),
            token_metadata=tuple(token_metadata),
        )

    def _read_curve_available(self, chain: ChainState, window: _LotWindow, auction_address: str, raw_log: RawLogRecord):
        """The lot's availability after the fill's block, kept as an observation for replay."""
        contract = self.abi_registry.auction_contract(chain.w3, auction_address, window.version)
        value = chain.reader.call(
            contract.functions.available(chain.w3.to_checksum_address(raw_log.address)),
            raw_log.block_number, optional=True,
        )
        return int(value) if value is not None else None

    def _lot_window(
        self, conn, *, chain_id: int, auction_address: str, token: str, timestamp: int,
        native_events: list[PreparedEvent] = (),
    ) -> Optional[_LotWindow]:
        """The staged window [startsAt, endsAt) of this token that holds the timestamp."""
        row = conn.execute(
            """
            SELECT json_extract(e.payload_json, '$.startsAt') AS starts_at,
                   s.want_token, s.receiver, s.version, e.capability_family
              FROM round_param_snapshot s
              JOIN domain_events e
                ON e.chain_id = s.chain_id AND e.tx_hash = s.snapshot_tx_hash
               AND e.log_index = s.snapshot_log_index AND e.event_name = 'AuctionKicked'
             WHERE s.chain_id = ? AND s.auction_address = ? AND s.from_token = ?
               AND json_extract(e.payload_json, '$.startsAt') <= ?
               AND json_extract(e.payload_json, '$.endsAt') > ?
             ORDER BY s.round_id DESC
             LIMIT 1
            """,
            (chain_id, auction_address, token, timestamp, timestamp),
        ).fetchone()
        if row is not None:
            return _LotWindow(
                starts_at=int(row["starts_at"]), version=row["version"], capability_family=row["capability_family"],
                want_token=row["want_token"], receiver=row["receiver"],
            )
        # A window first staged in this batch: its first stage carries the snapshot.
        for prepared in native_events:
            event = prepared.domain_event
            starts_at = event.payload.get("startsAt")
            if (event.event_name == "AuctionKicked" and event.auction_address == auction_address
                    and prepared.snapshot is not None and starts_at is not None
                    and normalize_address(event.payload["from"]) == token
                    and int(starts_at) <= timestamp < int(event.payload["endsAt"])):
                return _LotWindow(
                    starts_at=int(starts_at), version=event.version, capability_family=event.capability_family,
                    want_token=prepared.snapshot.want_token, receiver=prepared.snapshot.receiver,
                )
        return None

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
                    from .facts import _resolve_event_from_token
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
