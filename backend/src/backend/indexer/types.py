from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


def normalize_hex(value: Any, *, expected_size: int | None = None) -> str:
    if value is None:
        raise ValueError("hex value cannot be None")
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value).hex()
    else:
        raw = str(value).lower()
        raw = raw[2:] if raw.startswith("0x") else raw
    if expected_size is not None:
        raw = raw.rjust(expected_size * 2, "0")
    return f"0x{raw.lower()}"


def normalize_address(value: Any) -> str:
    if value is None:
        raise ValueError("address cannot be None")
    normalized = normalize_hex(value, expected_size=20)
    if len(normalized) != 42:
        raise ValueError(f"invalid address: {value!r}")
    return normalized


def decimal_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    return str(value)


def jsonable(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return normalize_hex(value)
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class ProjectPaths:
    repo_root: Path
    db_path: Path
    root_config_path: Path
    artifact_index_path: Path
    registry_abi_path: Path


@dataclass(frozen=True)
class RegistryConfig:
    address: str
    start_block: int


@dataclass(frozen=True)
class FactorySeed:
    address: str
    version: str
    capability_family: str
    start_block: int
    deploy_block: Optional[int]
    deploy_block_source: Optional[str]
    discovery_source: str
    enabled: bool = True


@dataclass(frozen=True)
class ChainConfig:
    name: str
    chain_id: int
    rpc_url: str
    finality_depth: int
    block_batch_size: int
    poll_interval_seconds: float
    poa: bool = False
    registry: Optional[RegistryConfig] = None
    factories: tuple[FactorySeed, ...] = ()


@dataclass(frozen=True)
class VersionDefinition:
    version: str
    capability_family: str
    auction_abi_path: Path
    factory_abi_path: Path
    supported_events: tuple[str, ...]
    getter_bundle: tuple[str, ...]


@dataclass(frozen=True)
class IndexerSettings:
    paths: ProjectPaths
    chains: dict[str, ChainConfig]
    versions: dict[str, VersionDefinition]


@dataclass(frozen=True)
class RawLogRecord:
    chain_id: int
    block_number: int
    block_hash: str
    tx_hash: str
    tx_index: int
    log_index: int
    address: str
    topic0: Optional[str]
    topic1: Optional[str]
    topic2: Optional[str]
    topic3: Optional[str]
    data: str
    timestamp: int


@dataclass(frozen=True)
class IndexedBlockRecord:
    chain_id: int
    block_number: int
    block_hash: str
    parent_hash: str
    timestamp: int


@dataclass(frozen=True)
class DomainEventRecord:
    chain_id: int
    block_number: int
    block_hash: str
    tx_hash: str
    tx_index: int
    log_index: int
    event_name: str
    address: str
    auction_address: str
    version: str
    capability_family: str
    payload: dict[str, Any]
    timestamp: int


@dataclass(frozen=True)
class TokenMetadata:
    chain_id: int
    token_address: str
    symbol: Optional[str]
    name: Optional[str]
    decimals: Optional[int]


@dataclass(frozen=True)
class AuctionSnapshot:
    chain_id: int
    auction_address: str
    block_number: int
    want_token: Optional[str]
    governance: Optional[str]
    receiver: Optional[str]
    starting_price_raw: Optional[str]
    minimum_price_raw: Optional[str]
    step_decay_rate_raw: Optional[str]
    step_duration_raw: Optional[str]
    auction_length_raw: Optional[str]
    extra_params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreparedEvent:
    raw_log: RawLogRecord
    domain_event: DomainEventRecord
    snapshot: Optional[AuctionSnapshot] = None
    token_metadata: tuple[TokenMetadata, ...] = ()


def prepared_event_from_domain_row(row) -> "PreparedEvent":
    payload = json.loads(row["payload_json"]) if row["payload_json"] else {}
    event = DomainEventRecord(
        chain_id=int(row["chain_id"]),
        block_number=int(row["block_number"]),
        block_hash=row["block_hash"],
        tx_hash=row["tx_hash"],
        tx_index=int(row["tx_index"]),
        log_index=int(row["log_index"]),
        event_name=str(row["event_name"]),
        address=normalize_address(row["address"]),
        auction_address=normalize_address(row["auction_address"]),
        version=str(row["version"]),
        capability_family=str(row["capability_family"]),
        payload=payload,
        timestamp=int(row["timestamp"]),
    )
    return PreparedEvent(
        raw_log=RawLogRecord(
            chain_id=event.chain_id,
            block_number=event.block_number,
            block_hash=event.block_hash,
            tx_hash=event.tx_hash,
            tx_index=event.tx_index,
            log_index=event.log_index,
            address=event.address,
            topic0=None,
            topic1=None,
            topic2=None,
            topic3=None,
            data="0x",
            timestamp=event.timestamp,
        ),
        domain_event=event,
    )
