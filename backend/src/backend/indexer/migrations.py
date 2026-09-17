from __future__ import annotations

import sqlite3
from pathlib import Path

from yoyo import get_backend, read_migrations


def _migration_dir() -> Path:
    return Path(__file__).resolve().parent / "db_migrations"


def _sqlite_url(path: Path) -> str:
    resolved = path.resolve()
    return f"sqlite:///{resolved.as_posix()}"


def _read_migrations():
    return read_migrations(str(_migration_dir()))


def _connect_read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def apply_pending_migrations(db_path: str | Path) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    backend = get_backend(_sqlite_url(path))
    migrations = _read_migrations()
    with backend.lock():
        backend.apply_migrations(backend.to_apply(migrations))


def has_pending_migrations(db_path: str | Path) -> bool:
    path = Path(db_path)
    migrations = list(_read_migrations())
    if not migrations:
        return False
    if not path.exists():
        raise FileNotFoundError(f"SQLite database not found: {path}")

    with _connect_read_only(path) as connection:
        table_row = connection.execute(
            """
            SELECT 1
              FROM sqlite_master
             WHERE type = 'table'
               AND name = '_yoyo_migration'
            """
        ).fetchone()
        if table_row is None:
            return True
        applied_hashes = {
            str(row["migration_hash"])
            for row in connection.execute("SELECT migration_hash FROM _yoyo_migration").fetchall()
        }
    return any(str(migration.hash) not in applied_hashes for migration in migrations)
