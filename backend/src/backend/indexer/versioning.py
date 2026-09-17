from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContractVersionMetadata:
    version: str
    capability_family: str
    param_schema: str
    supported_events: tuple[str, ...]
    getter_bundle: tuple[str, ...]
    factory_abi_filename: str
    historical: bool


def normalize_version(value: str | None) -> str:
    normalized = (value or "").strip()
    if normalized.lower().startswith("v"):
        normalized = normalized[1:]
    return normalized.lower()


VERSION_ORDER: tuple[str, ...] = (
    "1.0.5",
    "1.0.4",
    "1.0.3cc",
    "1.0.3",
    "1.0.2",
    "1.0.1",
    "0.0.1",
)


VERSION_METADATA: dict[str, ContractVersionMetadata] = {
    "0.0.1": ContractVersionMetadata(
        version="0.0.1",
        capability_family="0.0.1",
        param_schema="v1_fixed_decay",
        supported_events=(
            "AuctionEnabled",
            "AuctionDisabled",
            "AuctionKicked",
            "GovernanceTransferred",
        ),
        getter_bundle=("want", "governance", "startingPrice", "auctionLength"),
        factory_abi_filename="LegacyAuctionFactory.json",
        historical=True,
    ),
    "1.0.1": ContractVersionMetadata(
        version="1.0.1",
        capability_family="1.0.x",
        param_schema="v1_fixed_decay",
        supported_events=(
            "AuctionEnabled",
            "AuctionDisabled",
            "AuctionKicked",
            "GovernanceTransferred",
            "UpdatedStartingPrice",
        ),
        getter_bundle=("want", "governance", "receiver", "startingPrice", "auctionLength"),
        factory_abi_filename="AuctionFactory.json",
        historical=True,
    ),
    "1.0.2": ContractVersionMetadata(
        version="1.0.2",
        capability_family="1.0.x",
        param_schema="v1_fixed_decay",
        supported_events=(
            "AuctionEnabled",
            "AuctionDisabled",
            "AuctionKicked",
            "GovernanceTransferred",
            "UpdatedStartingPrice",
        ),
        getter_bundle=("want", "governance", "receiver", "startingPrice", "auctionLength"),
        factory_abi_filename="AuctionFactory.json",
        historical=True,
    ),
    "1.0.3": ContractVersionMetadata(
        version="1.0.3",
        capability_family="1.0.3",
        param_schema="v1_bps_decay",
        supported_events=(
            "AuctionEnabled",
            "AuctionDisabled",
            "AuctionKicked",
            "GovernanceTransferred",
            "UpdatedStartingPrice",
            "UpdatedStepDecayRate",
            "UpdatedStepDuration",
            "AuctionSettled",
            "AuctionSwept",
        ),
        getter_bundle=(
            "want",
            "governance",
            "receiver",
            "startingPrice",
            "stepDecayRate",
            "stepDuration",
            "auctionLength",
        ),
        factory_abi_filename="AuctionFactory1_0_3.json",
        historical=False,
    ),
    "1.0.3cc": ContractVersionMetadata(
        version="1.0.3cc",
        capability_family="1.0.3",
        param_schema="v1_bps_decay",
        supported_events=(
            "AuctionEnabled",
            "AuctionDisabled",
            "AuctionKicked",
            "GovernanceTransferred",
            "UpdatedStartingPrice",
            "UpdatedStepDecayRate",
            "UpdatedStepDuration",
            "UpdatedLetCowPeek",
            "AuctionSettled",
            "AuctionSwept",
        ),
        getter_bundle=(
            "want",
            "governance",
            "receiver",
            "startingPrice",
            "stepDecayRate",
            "stepDuration",
            "auctionLength",
            "letCowPeek",
        ),
        factory_abi_filename="AuctionFactory1_0_3.json",
        historical=False,
    ),
    "1.0.4": ContractVersionMetadata(
        version="1.0.4",
        capability_family="1.0.4",
        param_schema="v1_wad_bps",
        supported_events=(
            "AuctionEnabled",
            "AuctionDisabled",
            "AuctionKicked",
            "GovernanceTransferred",
            "UpdatedReceiver",
            "UpdatedMinimumPrice",
            "UpdatedStartingPrice",
            "UpdatedStepDecayRate",
            "UpdatedStepDuration",
            "AuctionSettled",
            "AuctionSwept",
        ),
        getter_bundle=(
            "want",
            "governance",
            "receiver",
            "minimumPrice",
            "startingPrice",
            "stepDecayRate",
            "stepDuration",
            "auctionLength",
        ),
        factory_abi_filename="AuctionFactory1_0_3.json",
        historical=False,
    ),
    "1.0.5": ContractVersionMetadata(
        version="1.0.5",
        capability_family="1.0.5",
        param_schema="v1_wad_start_wad_bps",
        supported_events=(
            "AuctionEnabled",
            "AuctionDisabled",
            "AuctionKicked",
            "GovernanceTransferred",
            "UpdatedReceiver",
            "UpdatedMinimumPrice",
            "UpdatedStartingPrice",
            "UpdatedStepDecayRate",
            "UpdatedStepDuration",
            "AuctionSettled",
            "AuctionSwept",
        ),
        getter_bundle=(
            "want",
            "governance",
            "receiver",
            "minimumPrice",
            "startingPrice",
            "stepDecayRate",
            "stepDuration",
            "auctionLength",
        ),
        factory_abi_filename="AuctionFactory1_0_3.json",
        historical=False,
    ),
}


def version_metadata(version: str | None) -> ContractVersionMetadata | None:
    return VERSION_METADATA.get(normalize_version(version))


def require_version_metadata(version: str | None) -> ContractVersionMetadata:
    metadata = version_metadata(version)
    if metadata is None:
        raise KeyError(normalize_version(version))
    return metadata


def param_schema_for_version(version: str | None) -> str | None:
    metadata = version_metadata(version)
    return metadata.param_schema if metadata else None


def uses_legacy_auction_id(version: str | None) -> bool:
    return normalize_version(version) == "0.0.1"


def normalize_version_filters(values: list[str] | tuple[str, ...] | None) -> list[str]:
    if not values:
        return []
    seen: set[str] = set()
    versions: list[str] = []
    for value in values:
        for part in str(value).split(","):
            version = normalize_version(part)
            if version and version not in seen:
                seen.add(version)
                versions.append(version)
    return versions


def version_sort_index(version: str | None) -> int:
    normalized = normalize_version(version)
    try:
        return VERSION_ORDER.index(normalized)
    except ValueError:
        return len(VERSION_ORDER)


def auction_token_key(w3, *, version: str, auction_address: str, from_token: str, want_token: str):
    """Contract lookup key shared by historical inference and live reads."""
    if uses_legacy_auction_id(version):
        return w3.solidity_keccak(
            ["address", "address", "address"],
            [w3.to_checksum_address(from_token), w3.to_checksum_address(want_token), w3.to_checksum_address(auction_address)],
        )
    return w3.to_checksum_address(from_token)
