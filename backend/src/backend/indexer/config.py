from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from .types import (
    ChainConfig,
    FactorySeed,
    IndexerSettings,
    ProjectPaths,
    RegistryConfig,
    VersionDefinition,
    normalize_address,
)
from .versioning import VERSION_METADATA, require_version_metadata


ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::([^}]*))?\}")

DEFAULT_FINALITY_DEPTHS: dict[int, int] = {
    1: 64,
    10: 128,
    137: 256,
    8453: 128,
    42161: 128,
    80094: 128,
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_db_path(repo_root: Path) -> Path:
    return repo_root / "backend" / "data" / "auctionscan.sqlite3"


def _interpolate_env(raw_text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        env_name = match.group(1)
        fallback = match.group(2)
        return os.environ.get(env_name, fallback or "")

    return ENV_PATTERN.sub(replace, raw_text)


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    rendered = _interpolate_env(text)
    payload = yaml.safe_load(rendered)
    if not isinstance(payload, dict):
        raise ValueError(f"expected mapping at {path}")
    return payload


def _load_artifact_index(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError(f"expected JSON list at {path}")
    return payload


def _resolve_artifact_abi_path(paths: ProjectPaths, version: str, auction_address: str) -> Path:
    version_dir = paths.repo_root / "artifacts" / "auction_source" / version
    normalized_address = normalize_address(auction_address)
    if version_dir.exists():
        for entry in version_dir.iterdir():
            if not entry.is_dir():
                continue
            if normalize_address(entry.name) == normalized_address:
                candidate = entry / "abi.json"
                if candidate.exists():
                    return candidate

    exact_path = version_dir / str(auction_address) / "abi.json"
    if exact_path.exists():
        return exact_path

    normalized_path = version_dir / normalized_address / "abi.json"
    if normalized_path.exists():
        return normalized_path

    return exact_path


def _build_paths(db_path: str | None = None) -> ProjectPaths:
    repo_root = _repo_root()
    if db_path:
        candidate = Path(db_path)
        resolved_db_path = candidate if candidate.is_absolute() else repo_root / candidate
    else:
        resolved_db_path = _default_db_path(repo_root)
    return ProjectPaths(
        repo_root=repo_root,
        db_path=resolved_db_path,
        root_config_path=repo_root / "config.yaml",
        artifact_index_path=repo_root / "artifacts" / "auction_source" / "index.json",
        registry_abi_path=repo_root / "backend" / "abis" / "AuctionRegistry.json",
    )


def _artifact_factory_metadata(paths: ProjectPaths) -> tuple[dict[str, dict[str, Any]], dict[str, Path]]:
    rows = _load_artifact_index(paths.artifact_index_path)
    by_factory: dict[str, dict[str, Any]] = {}
    by_version: dict[str, Path] = {}
    for row in rows:
        factory_address = normalize_address(row["factory_address"])
        version = str(row["version"])
        metadata = require_version_metadata(version)
        by_factory[factory_address] = {
            "version": version,
            "capability_family": row.get("capability_family") or metadata.capability_family,
            "factory_source": row.get("factory_source") or "registry",
        }
        abi_path = _resolve_artifact_abi_path(paths, version, str(row["auction_address"]))
        by_version[version] = abi_path
    return by_factory, by_version


def _factory_abi_path(paths: ProjectPaths, version: str) -> Path:
    return paths.repo_root / "backend" / "abis" / require_version_metadata(version).factory_abi_filename


def _build_versions(paths: ProjectPaths) -> dict[str, VersionDefinition]:
    _, abi_by_version = _artifact_factory_metadata(paths)
    versions: dict[str, VersionDefinition] = {}
    for version, metadata in VERSION_METADATA.items():
        auction_abi_path = abi_by_version.get(version)
        if auction_abi_path is None:
            raise ValueError(f"missing artifact ABI for version {version}")
        versions[version] = VersionDefinition(
            version=version,
            capability_family=metadata.capability_family,
            auction_abi_path=auction_abi_path,
            factory_abi_path=_factory_abi_path(paths, version),
            supported_events=metadata.supported_events,
            getter_bundle=metadata.getter_bundle,
        )
    return versions


def _canonicalize_factory(
    raw_entry: dict[str, Any],
    *,
    artifact_factories: dict[str, dict[str, Any]],
) -> FactorySeed:
    address = normalize_address(raw_entry["address"])
    known = artifact_factories.get(address)
    raw_version = str(raw_entry.get("version") or "").strip()
    if known:
        version = known["version"]
        capability_family = known["capability_family"]
        default_source = "override" if known.get("factory_source") == "override" else "config"
    elif raw_version in VERSION_METADATA:
        version = raw_version
        capability_family = VERSION_METADATA[version].capability_family
        default_source = "config"
    else:
        raise ValueError(
            f"cannot canonicalize factory {address}: unknown version {raw_version!r}"
        )

    start_block = int(raw_entry.get("start_block") or 0)
    deploy_block = start_block if start_block > 0 else None
    deploy_block_source = "config" if deploy_block is not None else None
    return FactorySeed(
        address=address,
        version=version,
        capability_family=capability_family,
        start_block=start_block,
        deploy_block=deploy_block,
        deploy_block_source=deploy_block_source,
        discovery_source=str(raw_entry.get("discovery_source") or default_source),
        enabled=bool(raw_entry.get("enabled", True)),
    )


def load_settings(
    *,
    db_path: str | None = None,
    target_network: str,
) -> IndexerSettings:
    paths = _build_paths(db_path=db_path)
    root_payload = _load_yaml(paths.root_config_path)
    artifact_factories, _ = _artifact_factory_metadata(paths)
    versions = _build_versions(paths)

    configured_networks = root_payload.get("networks") or {}
    if not isinstance(configured_networks, dict):
        raise ValueError("config.yaml networks must be a mapping")

    global_poll_interval = float((root_payload.get("indexer") or {}).get("poll_interval", 30))
    raw_network = configured_networks.get(target_network)
    if raw_network is None:
        raise ValueError(f"unknown network {target_network!r}")
    if raw_network.get("disabled", False):
        raise ValueError(f"network {target_network!r} is disabled")
    rpc_url = str(raw_network.get("rpc_url") or "").strip()
    if not rpc_url:
        raise ValueError(f"network {target_network!r} has no configured RPC URL")

    chain_id = int(raw_network["chain_id"])
    registry_cfg = raw_network.get("registry")
    registry = None
    if isinstance(registry_cfg, dict) and registry_cfg.get("address"):
        registry = RegistryConfig(
            address=normalize_address(registry_cfg["address"]),
            start_block=int(registry_cfg.get("start_block") or 0),
        )

    factories = tuple(
        _canonicalize_factory(entry, artifact_factories=artifact_factories)
        for entry in (raw_network.get("factories") or [])
    )
    chain = ChainConfig(
        name=target_network,
        chain_id=chain_id,
        rpc_url=rpc_url,
        finality_depth=int(
            raw_network.get("finality_depth")
            or DEFAULT_FINALITY_DEPTHS.get(chain_id, 64)
        ),
        block_batch_size=int(raw_network.get("block_batch_size") or 5_000),
        poll_interval_seconds=float(raw_network.get("poll_interval") or global_poll_interval),
        poa=bool(raw_network.get("poa", False)),
        registry=registry,
        factories=factories,
    )

    paths.db_path.parent.mkdir(parents=True, exist_ok=True)
    return IndexerSettings(paths=paths, chains={target_network: chain}, versions=versions)
