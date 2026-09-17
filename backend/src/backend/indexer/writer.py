from __future__ import annotations

import sqlite3
import threading
import fcntl
from pathlib import Path
from collections.abc import Callable
from typing import Any, TypeVar

from .migrations import apply_pending_migrations
from .sqlite import connect_database


T = TypeVar("T")


class ProcessLock:
    """One live or maintenance owner for a network in this database."""

    def __init__(self, db_path: str, chain_id: int) -> None:
        path = Path(db_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.with_name(f"{path.name}.{chain_id}.lock").open("a")
        try:
            fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._file.close()
            raise RuntimeError(f"Network {chain_id} already has a writer; stop its indexer before maintenance") from exc

    def close(self) -> None:
        self._file.close()


class Writer:
    def __init__(self, db_path: str) -> None:
        apply_pending_migrations(db_path)
        self._connection = connect_database(db_path)
        self._lock = threading.RLock()

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def transaction(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        with self._lock:
            connection = self._connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                result = fn(connection)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            return result

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._connection.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._connection.execute(sql, params).fetchall())
