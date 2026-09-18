import pytest

from backend.indexer.config import _resolve_artifact_abi_path
from backend.indexer.types import ProjectPaths

from backend.indexer.config import load_settings


def test_load_settings_canonicalizes_known_factory_versions(monkeypatch, tmp_path):
    monkeypatch.setenv("ETHEREUM_RPC_URL", "http://localhost:8545")

    settings = load_settings(
        db_path=str(tmp_path / "auctionscan.sqlite3"),
        target_network="ethereum",
    )

    ethereum = settings.chains["ethereum"]
    factories = {factory.address: factory for factory in ethereum.factories}

    assert set(factories) == {
        "0xd8e03d6d24d43c46c0f7f61327e391316e4f3c15",
        "0xe87af17acba165686e5aa7de2cec523864c25712",
    }
    assert factories["0xd8e03d6d24d43c46c0f7f61327e391316e4f3c15"].version == "1.0.3"
    assert factories["0xe87af17acba165686e5aa7de2cec523864c25712"].version == "1.0.3cc"
    assert factories["0xe87af17acba165686e5aa7de2cec523864c25712"].discovery_source == "override"
    assert ethereum.registry is not None
    assert ethereum.registry.address == "0x94f44706a61845a4f9e59c4bc08cea4503e48d12"

    version = settings.versions["1.0.5"]
    assert version.capability_family == "1.0.5"
    assert version.factory_abi_path.name == "AuctionFactory1_0_3.json"
    assert version.auction_abi_path.name == "abi.json"
    assert "minimumPrice" in version.getter_bundle


def test_load_settings_requires_known_network(monkeypatch, tmp_path):
    monkeypatch.setenv("ETHEREUM_RPC_URL", "http://localhost:8545")

    with pytest.raises(ValueError, match="unknown network"):
        load_settings(db_path=str(tmp_path / "auctionscan.sqlite3"), target_network="unknown")


def test_load_settings_rejects_disabled_network(monkeypatch, tmp_path):
    monkeypatch.setenv("BERACHAIN_RPC_URL", "http://localhost:8545")

    with pytest.raises(ValueError, match="disabled"):
        load_settings(
            db_path=str(tmp_path / "auctionscan.sqlite3"),
            target_network="berachain",
        )


def test_resolve_artifact_abi_path_preserves_indexed_address_case(tmp_path):
    repo_root = tmp_path / "repo"
    abi_path = (
        repo_root
        / "artifacts"
        / "auction_source"
        / "0.0.1"
        / "0x27A4D71DBF3537caa8247BE7FE33a52C40A3920A"
        / "abi.json"
    )
    abi_path.parent.mkdir(parents=True)
    abi_path.write_text("[]", encoding="utf-8")

    paths = ProjectPaths(
        repo_root=repo_root,
        db_path=repo_root / "backend" / "data" / "auctionscan.sqlite3",
        root_config_path=repo_root / "config.yaml",
        artifact_index_path=repo_root / "artifacts" / "auction_source" / "index.json",
        registry_abi_path=repo_root / "backend" / "abis" / "AuctionRegistry.json",
    )

    resolved = _resolve_artifact_abi_path(
        paths,
        "0.0.1",
        "0x27A4D71DBF3537caa8247BE7FE33a52C40A3920A",
    )

    assert resolved == abi_path


def test_resolve_artifact_abi_path_matches_case_insensitively(tmp_path):
    repo_root = tmp_path / "repo"
    abi_path = (
        repo_root
        / "artifacts"
        / "auction_source"
        / "0.0.1"
        / "0x27A4D71DBF3537caa8247BE7FE33a52C40A3920A"
        / "abi.json"
    )
    abi_path.parent.mkdir(parents=True)
    abi_path.write_text("[]", encoding="utf-8")

    paths = ProjectPaths(
        repo_root=repo_root,
        db_path=repo_root / "backend" / "data" / "auctionscan.sqlite3",
        root_config_path=repo_root / "config.yaml",
        artifact_index_path=repo_root / "artifacts" / "auction_source" / "index.json",
        registry_abi_path=repo_root / "backend" / "abis" / "AuctionRegistry.json",
    )

    resolved = _resolve_artifact_abi_path(
        paths,
        "0.0.1",
        "0x27a4d71dbf3537caa8247be7fe33a52c40a3920a",
    )

    assert resolved == abi_path
