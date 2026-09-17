from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from hexbytes import HexBytes

try:
    from requests import exceptions as requests_exceptions
except ImportError:  # pragma: no cover
    requests_exceptions = None

from .chains import ChainState
from .polling import chunked
from .types import PreparedEvent, normalize_address


logger = logging.getLogger(__name__)

ADDRESS_ALIAS_RETRY_SECONDS = 7 * 24 * 60 * 60
ADDRESS_ALIAS_MAX_LENGTH = 255
ADDRESS_ALIAS_MULTICALL_BATCH_SIZE = 100
MULTICALL3_ADDRESS = normalize_address("0xcA11bde05977b3631167028862bE2a173976CA11")
NAME_CALL_DATA = HexBytes("0x06fdde03")

NAME_ABI = [
    {
        "type": "function",
        "name": "name",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "string"}],
    }
]

MULTICALL3_ABI = [
    {
        "type": "function",
        "name": "aggregate3",
        "stateMutability": "payable",
        "inputs": [
            {
                "name": "calls",
                "type": "tuple[]",
                "components": [
                    {"name": "target", "type": "address"},
                    {"name": "allowFailure", "type": "bool"},
                    {"name": "callData", "type": "bytes"},
                ],
            }
        ],
        "outputs": [
            {
                "name": "returnData",
                "type": "tuple[]",
                "components": [
                    {"name": "success", "type": "bool"},
                    {"name": "returnData", "type": "bytes"},
                ],
            }
        ],
    }
]


@dataclass(frozen=True)
class AddressAliasBackfillCandidate:
    chain_id: int
    address: str


@dataclass(frozen=True)
class AddressAliasUpdate:
    chain_id: int
    address: str
    alias_text: str | None
    checked_at: int


@dataclass(frozen=True)
class AddressAliasBackfillSummary:
    checked: int
    updated: int


def collect_receiver_alias_addresses(prepared_events: list[PreparedEvent]) -> list[str]:
    seen: set[str] = set()
    collected: list[str] = []
    for prepared in prepared_events:
        candidates = [
            prepared.snapshot.receiver if prepared.snapshot else None,
            prepared.domain_event.payload.get("receiver"),
        ]
        for value in candidates:
            if not value:
                continue
            try:
                address = normalize_address(value)
            except ValueError:
                continue
            if address in seen:
                continue
            seen.add(address)
            collected.append(address)
    return collected


def load_existing_address_aliases(conn, *, chain_id: int, addresses: list[str]) -> set[str]:
    if not addresses:
        return set()
    placeholders = ", ".join("?" for _ in addresses)
    rows = conn.execute(
        f"""
        SELECT address
          FROM address_aliases
         WHERE chain_id = ?
           AND address IN ({placeholders})
        """,
        (chain_id, *addresses),
    ).fetchall()
    return {str(row["address"]) for row in rows}


def load_address_alias_backfill_candidates(
    conn,
    *,
    chain_id: int,
    force: bool,
    now: int | None = None,
    retry_after_seconds: int = ADDRESS_ALIAS_RETRY_SECONDS,
) -> list[AddressAliasBackfillCandidate]:
    params: list[object] = [chain_id, chain_id, chain_id, chain_id, chain_id, chain_id, chain_id]
    sql = """
        WITH receiver_candidates AS (
            SELECT receiver AS address
              FROM auction_snapshot_facts
             WHERE chain_id = ?
               AND receiver IS NOT NULL
               AND TRIM(receiver) != ''
            UNION
            SELECT receiver AS address
              FROM round_param_snapshot
             WHERE chain_id = ?
               AND receiver IS NOT NULL
               AND TRIM(receiver) != ''
            UNION
            SELECT receiver AS address
              FROM auction_current_params
             WHERE chain_id = ?
               AND receiver IS NOT NULL
               AND TRIM(receiver) != ''
            UNION
            SELECT receiver AS address
              FROM auctions
             WHERE chain_id = ?
               AND receiver IS NOT NULL
               AND TRIM(receiver) != ''
            UNION
            SELECT receiver AS address
              FROM rounds
             WHERE chain_id = ?
               AND receiver IS NOT NULL
               AND TRIM(receiver) != ''
            UNION
            SELECT receiver AS address
              FROM takes
             WHERE chain_id = ?
               AND receiver IS NOT NULL
               AND TRIM(receiver) != ''
        )
        SELECT ? AS chain_id,
               rc.address
          FROM receiver_candidates rc
          LEFT JOIN address_aliases aa
            ON aa.chain_id = ?
           AND aa.address = rc.address
         WHERE 1 = 1
    """
    params.append(chain_id)
    if force:
        pass
    else:
        sql += """
           AND aa.alias_text IS NULL
           AND (aa.checked_at IS NULL OR aa.checked_at < ?)
        """
        params.append((now or int(time.time())) - retry_after_seconds)
    sql += " ORDER BY COALESCE(aa.checked_at, 0) ASC, rc.address ASC"
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        AddressAliasBackfillCandidate(
            chain_id=int(row["chain_id"]),
            address=str(row["address"]),
        )
        for row in rows
    ]


def apply_address_alias_updates(conn, updates: list[AddressAliasUpdate]) -> int:
    updated = 0
    for item in updates:
        cursor = conn.execute(
            """
            INSERT INTO address_aliases (chain_id, address, alias_text, checked_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chain_id, address) DO UPDATE SET
                alias_text = excluded.alias_text,
                checked_at = excluded.checked_at
            """,
            (
                item.chain_id,
                item.address,
                item.alias_text,
                item.checked_at,
            ),
        )
        updated += cursor.rowcount
    return updated


def resolve_address_alias_updates(
    chain: ChainState,
    addresses: list[str],
    *,
    checked_at: int | None = None,
) -> list[AddressAliasUpdate]:
    if not addresses:
        return []
    timestamp = checked_at or int(time.time())
    updates: list[AddressAliasUpdate] = []
    for address in addresses:
        try:
            alias_text = lookup_address_alias(chain, address=address)
        except Exception as exc:
            logger.warning(
                "receiver alias lookup failed network=%s chain_id=%d address=%s error=%s",
                chain.config.name,
                chain.config.chain_id,
                address,
                exc,
            )
            continue
        updates.append(
            AddressAliasUpdate(
                chain_id=chain.config.chain_id,
                address=address,
                alias_text=alias_text,
                checked_at=timestamp,
            )
        )
    return updates


def resolve_address_alias_updates_multicall(
    chain: ChainState,
    addresses: list[str],
    *,
    checked_at: int | None = None,
    batch_size: int = ADDRESS_ALIAS_MULTICALL_BATCH_SIZE,
) -> list[AddressAliasUpdate]:
    if not addresses:
        return []
    timestamp = checked_at or int(time.time())
    multicall = chain.w3.eth.contract(
        address=chain.w3.to_checksum_address(MULTICALL3_ADDRESS),
        abi=MULTICALL3_ABI,
    )
    updates: list[AddressAliasUpdate] = []
    for batch in chunked(addresses, batch_size):
        calls = [
            (
                chain.w3.to_checksum_address(address),
                True,
                NAME_CALL_DATA,
            )
            for address in batch
        ]
        try:
            results = multicall.functions.aggregate3(calls).call(block_identifier="latest")
        except Exception as exc:
            if _is_transport_error(exc):
                raise
            logger.warning(
                "receiver alias multicall failed network=%s chain_id=%d batch_size=%d error=%s",
                chain.config.name,
                chain.config.chain_id,
                len(batch),
                exc,
            )
            updates.extend(resolve_address_alias_updates(chain, batch, checked_at=timestamp))
            continue
        for address, result in zip(batch, results):
            success, return_data = _parse_multicall_result(result)
            alias_text = _decode_name_return_data(chain, return_data) if success else None
            updates.append(
                AddressAliasUpdate(
                    chain_id=chain.config.chain_id,
                    address=address,
                    alias_text=alias_text,
                    checked_at=timestamp,
                )
            )
    return updates


def lookup_address_alias(chain: ChainState, *, address: str) -> str | None:
    contract = chain.w3.eth.contract(
        address=chain.w3.to_checksum_address(address),
        abi=NAME_ABI,
    )
    try:
        value = contract.functions.name().call(block_identifier="latest")
    except Exception as exc:
        if _is_transport_error(exc):
            raise
        return None
    return _normalize_alias_text(value)


def _parse_multicall_result(result: Any) -> tuple[bool, bytes]:
    if isinstance(result, dict):
        return bool(result.get("success")), _as_bytes(result.get("returnData"))
    if isinstance(result, (list, tuple)) and len(result) >= 2:
        return bool(result[0]), _as_bytes(result[1])
    return False, b""


def _decode_name_return_data(chain: ChainState, return_data: Any) -> str | None:
    raw = _as_bytes(return_data)
    if not raw:
        return None
    try:
        decoded = chain.w3.codec.decode(["string"], raw)
    except Exception:
        return None
    if not decoded:
        return None
    return _normalize_alias_text(decoded[0])


def _normalize_alias_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    alias_text = value.strip()
    if not alias_text:
        return None
    if len(alias_text) > ADDRESS_ALIAS_MAX_LENGTH:
        alias_text = alias_text[:ADDRESS_ALIAS_MAX_LENGTH].strip()
    return alias_text or None


def _as_bytes(value: Any) -> bytes:
    if value is None:
        return b""
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    try:
        return bytes(HexBytes(value))
    except Exception:
        return b""


def _is_transport_error(exc: BaseException) -> bool:
    transport_types: tuple[type[BaseException], ...] = (OSError, TimeoutError)
    if requests_exceptions is not None:
        transport_types += (requests_exceptions.RequestException,)
    return any(isinstance(item, transport_types) for item in _exception_chain(exc))


def _exception_chain(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        yield current
        seen.add(id(current))
        current = current.__cause__ or current.__context__
