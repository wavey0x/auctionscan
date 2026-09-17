"""Collect and hydrate native events before entering a writer transaction."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .chains import ChainState
from .decode import AbiRegistry, normalize_raw_log
from .hydration import Hydrator
from .polling import chunked, fetch_logs, sort_logs
from .types import PreparedEvent, normalize_address, normalize_hex


def scan_factory_events(
    chain: ChainState,
    abi_registry: AbiRegistry,
    hydrator: Hydrator,
    tracked_factories: list[Any],
    from_block: int,
    to_block: int,
) -> list[PreparedEvent]:
    if not tracked_factories:
        return []
    by_address = {normalize_address(row["factory_address"]): row for row in tracked_factories}
    addresses = list(by_address)
    deploy_topic = abi_registry.factory_event_topic(str(tracked_factories[0]["version"]))
    prepared: list[PreparedEvent] = []
    for address_chunk in chunked(addresses, 100):
        logs = sort_logs(
            fetch_logs(
                chain.w3,
                block_hashes=getattr(getattr(chain, "reader", None), "log_hashes", None),
                from_block=from_block,
                to_block=to_block,
                address=address_chunk,
                topics=[deploy_topic],
            )
        )
        for log in logs:
            normalized_address = normalize_address(log["address"])
            row = by_address[normalized_address]
            if getattr(chain, "reader", None) is not None:
                chain.reader.header(int(log["blockNumber"]), expected_hash=normalize_hex(log["blockHash"]))
            timestamp = chain.block_timestamp(int(log["blockNumber"]))
            raw_log = normalize_raw_log(chain.config.chain_id, log, timestamp)
            domain_event = abi_registry.decode_factory_log(
                chain.w3,
                str(row["version"]),
                log,
                chain_id=chain.config.chain_id,
                timestamp=timestamp,
            )
            prepared.append(
                hydrate_native_event(
                    chain, hydrator, PreparedEvent(raw_log=raw_log, domain_event=domain_event)
                )
            )
    return prepared


def scan_auction_events(
    chain: ChainState,
    abi_registry: AbiRegistry,
    hydrator: Hydrator,
    tracked_auctions: list[Any],
    from_block: int,
    to_block: int,
) -> list[PreparedEvent]:
    if not tracked_auctions:
        return []

    address_to_version: dict[str, str] = {}
    for row in tracked_auctions:
        address = normalize_address(row["auction_address"])
        version = str(row["version"])
        address_to_version[address] = version

    topics_by_version: dict[str, set[str]] = {}
    for version in set(address_to_version.values()):
        definition = abi_registry.version_definition(version)
        topics_by_version[version] = {
            abi_registry.auction_event_topic(version, event_name)
            for event_name in definition.supported_events
        }
    all_topics = sorted({topic for version_topics in topics_by_version.values() for topic in version_topics})
    if not all_topics:
        return []

    logs: list[dict[str, Any]] = []
    for address_chunk in chunked(sorted(address_to_version), 100):
        logs.extend(
            fetch_logs(
                chain.w3,
                block_hashes=getattr(getattr(chain, "reader", None), "log_hashes", None),
                from_block=from_block,
                to_block=to_block,
                address=address_chunk,
                topics=[all_topics],
            )
        )

    prepared: list[PreparedEvent] = []
    for log in sort_logs(logs):
        normalized_address = normalize_address(log["address"])
        version = address_to_version.get(normalized_address)
        if version is None or not log.get("topics"):
            continue
        topic0 = normalize_hex(log["topics"][0])
        if topic0 not in topics_by_version[version]:
            continue

        if getattr(chain, "reader", None) is not None:
            chain.reader.header(int(log["blockNumber"]), expected_hash=normalize_hex(log["blockHash"]))
        timestamp = chain.block_timestamp(int(log["blockNumber"]))
        raw_log = normalize_raw_log(chain.config.chain_id, log, timestamp)
        domain_event = abi_registry.decode_auction_log(
            chain.w3,
            version,
            log,
            chain_id=chain.config.chain_id,
            timestamp=timestamp,
        )
        prepared.append(
            hydrate_native_event(chain, hydrator, PreparedEvent(raw_log=raw_log, domain_event=domain_event))
        )
    return prepared


def hydrate_native_event(chain: ChainState, hydrator: Hydrator, base: PreparedEvent) -> PreparedEvent:
    event = base.domain_event
    snapshot = None
    if event.event_name in {"DeployedNewAuction", "AuctionKicked"}:
        snapshot = hydrator.read_auction_snapshot(
            chain,
            event.version,
            event.auction_address,
            event.block_number,
            event_payload=event.payload,
        )
    prepared = replace(base, snapshot=snapshot)
    return replace(prepared, token_metadata=hydrator.read_event_token_metadata(chain, prepared))
