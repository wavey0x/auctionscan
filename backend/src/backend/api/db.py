from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import yaml

from backend.indexer.migrations import has_pending_migrations


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _default_db_path(repo_root: Path) -> Path:
    return repo_root / "backend" / "data" / "auctionscan.sqlite3"


def _resolve_db_path(repo_root: Path, db_path: str | None = None) -> Path:
    configured_path = db_path or os.environ.get("AUCTIONSCAN_DB_PATH")
    if configured_path:
        candidate = Path(configured_path)
        return candidate if candidate.is_absolute() else repo_root / candidate
    return _default_db_path(repo_root)


@dataclass(frozen=True)
class ChainMetadata:
    chain_id: int
    network_key: str
    name: str
    short_name: str
    explorer: str | None
    icon: str | None
    emoji: str | None
    disabled: bool
    start_block: int | None


class SchemaOutdatedError(FileNotFoundError):
    """Raised when the DB exists but has unapplied schema migrations."""


def _chain_start_block(raw: dict) -> int | None:
    starts: list[int] = []
    registry = raw.get("registry")
    if isinstance(registry, dict) and registry.get("start_block") is not None:
        starts.append(int(registry["start_block"]))
    factories = raw.get("factories")
    if isinstance(factories, list):
        for item in factories:
            if isinstance(item, dict) and item.get("start_block") is not None:
                starts.append(int(item["start_block"]))
    return min(starts) if starts else None


def load_chain_catalog() -> dict[int, ChainMetadata]:
    payload = yaml.safe_load((_repo_root() / "config.yaml").read_text(encoding="utf-8")) or {}
    networks = payload.get("networks") or {}
    catalog: dict[int, ChainMetadata] = {}
    for network_key, raw in networks.items():
        if not isinstance(raw, dict) or "chain_id" not in raw:
            continue
        chain_id = int(raw["chain_id"])
        catalog[chain_id] = ChainMetadata(
            chain_id=chain_id,
            network_key=str(network_key),
            name=str(raw.get("name") or network_key),
            short_name=str(raw.get("short_name") or raw.get("name") or network_key),
            explorer=str(raw["explorer"]) if raw.get("explorer") else None,
            icon=str(raw["icon"]) if raw.get("icon") else None,
            emoji=str(raw["emoji"]) if raw.get("emoji") else None,
            disabled=bool(raw.get("disabled", False)),
            start_block=_chain_start_block(raw),
        )
    return catalog


class Database:
    def __init__(self, db_path: str | None = None) -> None:
        repo_root = _repo_root()
        self.db_path = _resolve_db_path(repo_root, db_path)
        self.chain_catalog = load_chain_catalog()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if not self.db_path.exists():
            raise FileNotFoundError("SQLite database not found")
        if has_pending_migrations(self.db_path):
            raise SchemaOutdatedError(
                "SQLite database schema is outdated: apply pending indexer migrations"
            )
        connection = sqlite3.connect(str(self.db_path), check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        try:
            yield connection
        finally:
            connection.close()


def load_cors_origins() -> list[str]:
    raw = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    return [item.strip() for item in raw.split(",") if item.strip()]
