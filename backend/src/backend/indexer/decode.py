from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eth_utils import event_abi_to_log_topic
from web3._utils.events import get_event_data

from .types import (
    DomainEventRecord,
    IndexerSettings,
    RawLogRecord,
    VersionDefinition,
    jsonable,
    normalize_address,
    normalize_hex,
)


def _load_abi(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict) and "abi" in payload:
        return payload["abi"]
    if not isinstance(payload, list):
        raise ValueError(f"invalid ABI payload in {path}")
    return payload


def _normalize_argument(argument_type: str, value: Any) -> Any:
    if value is None:
        return None
    if argument_type == "address":
        return normalize_address(value)
    if argument_type.endswith("[]") and argument_type.startswith("address"):
        return [normalize_address(item) for item in value]
    if argument_type.startswith("bytes"):
        return normalize_hex(value)
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    return value


def _build_payload(event_abi: dict[str, Any], arguments: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for item in event_abi.get("inputs", []):
        name = item["name"]
        payload[name] = _normalize_argument(item["type"], arguments.get(name))
    return payload


class AbiRegistry:
    def __init__(self, settings: IndexerSettings) -> None:
        self.settings = settings
        self._auction_contract_abis: dict[str, list[dict[str, Any]]] = {}
        self._auction_event_abis: dict[str, dict[str, dict[str, Any]]] = {}
        self._factory_event_abis: dict[str, dict[str, dict[str, Any]]] = {}
        self._auction_topics: dict[str, dict[str, str]] = {}
        self._factory_topics: dict[str, dict[str, str]] = {}
        self._registry_abi = _load_abi(settings.paths.registry_abi_path)
        self._initialize_versions()

    def _initialize_versions(self) -> None:
        for version, definition in self.settings.versions.items():
            auction_abi = _load_abi(definition.auction_abi_path)
            factory_abi = _load_abi(definition.factory_abi_path)
            self._auction_contract_abis[version] = auction_abi

            auction_events = {
                item["name"]: item
                for item in auction_abi
                if item.get("type") == "event" and item["name"] in definition.supported_events
            }
            factory_events = {
                item["name"]: item
                for item in factory_abi
                if item.get("type") == "event" and item["name"] == "DeployedNewAuction"
            }
            self._auction_event_abis[version] = auction_events
            self._factory_event_abis[version] = factory_events
            self._auction_topics[version] = {
                normalize_hex(event_abi_to_log_topic(event_abi)): event_name
                for event_name, event_abi in auction_events.items()
            }
            self._factory_topics[version] = {
                normalize_hex(event_abi_to_log_topic(event_abi)): event_name
                for event_name, event_abi in factory_events.items()
            }

    def version_definition(self, version: str) -> VersionDefinition:
        return self.settings.versions[version]

    def auction_contract(self, w3, address: str, version: str):
        return w3.eth.contract(
            address=w3.to_checksum_address(address),
            abi=self._auction_contract_abis[version],
        )

    def registry_contract(self, w3, address: str):
        return w3.eth.contract(address=w3.to_checksum_address(address), abi=self._registry_abi)

    def auction_event_topic(self, version: str, event_name: str) -> str:
        event_abi = self._auction_event_abis[version][event_name]
        return normalize_hex(event_abi_to_log_topic(event_abi))

    def factory_event_topic(self, version: str, event_name: str = "DeployedNewAuction") -> str:
        event_abi = self._factory_event_abis[version][event_name]
        return normalize_hex(event_abi_to_log_topic(event_abi))

    def decode_factory_log(
        self,
        w3,
        version: str,
        log: dict[str, Any],
        *,
        chain_id: int,
        timestamp: int,
    ) -> DomainEventRecord:
        topic0 = normalize_hex(log["topics"][0])
        event_name = self._factory_topics[version][topic0]
        event_abi = self._factory_event_abis[version][event_name]
        decoded = get_event_data(w3.codec, event_abi, log)
        payload = _build_payload(event_abi, dict(decoded["args"]))
        auction_address = payload.get("auction")
        if not auction_address:
            raise ValueError(f"factory event {event_name} did not include auction address")
        return DomainEventRecord(
            chain_id=chain_id,
            block_number=int(log["blockNumber"]),
            block_hash=normalize_hex(log["blockHash"]),
            tx_hash=normalize_hex(log["transactionHash"]),
            tx_index=int(log.get("transactionIndex", 0)),
            log_index=int(log["logIndex"]),
            event_name=event_name,
            address=normalize_address(log["address"]),
            auction_address=normalize_address(auction_address),
            version=version,
            capability_family=self.version_definition(version).capability_family,
            payload=payload,
            timestamp=timestamp,
        )

    def decode_auction_log(
        self,
        w3,
        version: str,
        log: dict[str, Any],
        *,
        chain_id: int,
        timestamp: int,
    ) -> DomainEventRecord:
        topic0 = normalize_hex(log["topics"][0])
        event_name = self._auction_topics[version][topic0]
        event_abi = self._auction_event_abis[version][event_name]
        decoded = get_event_data(w3.codec, event_abi, log)
        payload = _build_payload(event_abi, dict(decoded["args"]))
        return DomainEventRecord(
            chain_id=chain_id,
            block_number=int(log["blockNumber"]),
            block_hash=normalize_hex(log["blockHash"]),
            tx_hash=normalize_hex(log["transactionHash"]),
            tx_index=int(log.get("transactionIndex", 0)),
            log_index=int(log["logIndex"]),
            event_name=event_name,
            address=normalize_address(log["address"]),
            auction_address=normalize_address(log["address"]),
            version=version,
            capability_family=self.version_definition(version).capability_family,
            payload=payload,
            timestamp=timestamp,
        )


def normalize_raw_log(chain_id: int, log: dict[str, Any], timestamp: int) -> RawLogRecord:
    topics = list(log.get("topics", []))
    normalized_topics = [normalize_hex(item) for item in topics[:4]]
    while len(normalized_topics) < 4:
        normalized_topics.append(None)
    return RawLogRecord(
        chain_id=chain_id,
        block_number=int(log["blockNumber"]),
        block_hash=normalize_hex(log["blockHash"]),
        tx_hash=normalize_hex(log["transactionHash"]),
        tx_index=int(log.get("transactionIndex", 0)),
        log_index=int(log["logIndex"]),
        address=normalize_address(log["address"]),
        topic0=normalized_topics[0],
        topic1=normalized_topics[1],
        topic2=normalized_topics[2],
        topic3=normalized_topics[3],
        data=normalize_hex(log.get("data", "0x")),
        timestamp=timestamp,
    )
