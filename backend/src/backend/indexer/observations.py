"""Block-bound RPC facts used by both collection and offline derivation."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from eth_utils.abi import get_abi_output_types
from eth_abi.exceptions import DecodingError
from hexbytes import HexBytes
from web3 import Web3
from web3.exceptions import ContractLogicError

from .types import IndexedBlockRecord, RawLogRecord, normalize_address, normalize_hex


OBSERVATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS rpc_observations (
    chain_id INTEGER NOT NULL,
    block_number INTEGER NOT NULL,
    block_hash TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('call', 'transaction', 'receipt')),
    subject TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'reverted')),
    result_json TEXT NOT NULL,
    PRIMARY KEY (chain_id, block_hash, kind, subject)
);
CREATE INDEX IF NOT EXISTS idx_rpc_observations_block
    ON rpc_observations (chain_id, block_number);
"""


class MissingObservation(ValueError):
    """An offline repair needs an explicit backfill before it can proceed."""


class BranchChanged(ValueError):
    """Discard the prepared batch and retry against the current canonical head."""


class BlockReader:
    def __init__(
        self, conn, *, chain_id: int, w3, header_reader: Callable[[int], IndexedBlockRecord] | None,
        headers: list[IndexedBlockRecord] = (), offline: bool = False,
    ) -> None:
        self.conn = conn
        self.chain_id = chain_id
        self.w3 = w3
        self.header_reader = header_reader
        self.headers = {header.block_number: header for header in headers}
        self.offline = offline
        self.pending: dict[tuple[str, str, str], tuple[IndexedBlockRecord, str, str]] = {}

    def header(self, number: int, *, expected_hash: str | None = None) -> IndexedBlockRecord:
        header = self.headers.get(number)
        if header is None:
            if self.offline:
                row = self.conn.execute(
                    "SELECT * FROM indexed_blocks WHERE chain_id = ? AND block_number = ?",
                    (self.chain_id, number),
                ).fetchone()
                if row is None:
                    raise MissingObservation(f"Missing block header {number}; run observation backfill")
                header = IndexedBlockRecord(**dict(row))
            else:
                if self.header_reader is None:
                    raise RuntimeError("Online collection requires a header reader")
                header = self.header_reader(number)
            self.headers[number] = header
        if expected_hash is not None and header.block_hash != expected_hash:
            raise BranchChanged(f"Observation belongs to another branch at block {number}")
        return header

    def _read(self, header: IndexedBlockRecord, kind: str, subject: str, fetch) -> tuple[str, Any]:
        key = (header.block_hash, kind, subject)
        if key in self.pending:
            _, status, payload = self.pending[key]
            return status, json.loads(payload)
        row = self.conn.execute(
            """SELECT status, result_json FROM rpc_observations
               WHERE chain_id = ? AND block_hash = ? AND kind = ? AND subject = ?""",
            (self.chain_id, *key),
        ).fetchone()
        if row is not None:
            return str(row["status"]), json.loads(row["result_json"])
        if self.offline:
            raise MissingObservation(f"Missing {kind} observation at block {header.block_number}: {subject}; run observation backfill")
        status, result = fetch()
        payload = Web3.to_json(result)
        self.pending[key] = (header, status, payload)
        return status, json.loads(payload)

    def call(self, fn, block_number: int, *, optional: bool = False) -> Any:
        return self.call_encoded(fn.address, normalize_hex(fn._encode_transaction_data()),
                                 get_abi_output_types(fn.abi), block_number, optional=optional)

    def call_encoded(self, address: str, data: str, output_types, block_number: int, *, optional: bool = False) -> Any:
        header = self.header(block_number)
        address = normalize_address(address)
        subject = f"{address}:{data}"

        def fetch():
            try:
                # ContractFunction.call resolves hash identifiers back to heights
                # in some Web3 versions. Send the EIP-1898 object explicitly.
                result = self.w3.eth.call(
                    {"to": Web3.to_checksum_address(address), "data": data},
                    block_identifier={"blockHash": header.block_hash, "requireCanonical": True},
                    ccip_read_enabled=False,
                )
                return "ok", normalize_hex(result)
            except ContractLogicError as exc:
                return "reverted", str(exc)

        status, result = self._read(header, "call", subject, fetch)
        if status == "reverted":
            if optional:
                return None
            raise ValueError(f"Required contract call reverted at {header.block_hash}: {subject}: {result}")
        if result == "0x" and optional:
            return None
        try:
            decoded = self.w3.codec.decode(output_types, HexBytes(result))
        except DecodingError:
            if optional:
                return None
            raise
        return decoded[0] if len(decoded) == 1 else decoded

    def transaction(self, log: RawLogRecord) -> dict:
        header = self.header(log.block_number, expected_hash=log.block_hash)
        _, tx = self._read(header, "transaction", log.tx_hash, lambda: (
            "ok", self.w3.eth.get_transaction(log.tx_hash),
        ))
        self._check_transaction(tx, log)
        return tx

    def receipt(self, log: RawLogRecord) -> dict:
        header = self.header(log.block_number, expected_hash=log.block_hash)
        _, receipt = self._read(header, "receipt", log.tx_hash, lambda: (
            "ok", self.w3.eth.get_transaction_receipt(log.tx_hash),
        ))
        self._check_transaction(receipt, log)
        for receipt_log in receipt.get("logs", []):
            self._check_transaction(receipt_log, log)
        return receipt

    @staticmethod
    def _check_transaction(value: dict, log: RawLogRecord) -> None:
        if normalize_hex(value.get("blockHash")) != log.block_hash:
            raise BranchChanged(f"Transaction {log.tx_hash} changed branch")
        if normalize_hex(value.get("transactionHash", value.get("hash"))) != log.tx_hash:
            raise ValueError(f"RPC returned a different transaction for {log.tx_hash}")

    def persist(self, conn) -> None:
        from .facts import upsert_indexed_blocks

        upsert_indexed_blocks(conn, list(self.headers.values()))
        conn.executemany(
            """INSERT OR IGNORE INTO rpc_observations
               (chain_id, block_number, block_hash, kind, subject, status, result_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(self.chain_id, header.block_number, block_hash, kind, subject, status, payload)
             for (block_hash, kind, subject), (header, status, payload) in self.pending.items()],
        )
