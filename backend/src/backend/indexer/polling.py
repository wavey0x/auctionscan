from __future__ import annotations

from collections.abc import Iterable
from typing import Any


SPLIT_KEYWORDS = (
    "too many results",
    "response size",
    "query returned more than",
    "limit",
    "timeout",
    "gateway",
    "internal error",
    "server error",
    "bad request",
)


def chunked(values: Iterable[Any], size: int) -> list[list[Any]]:
    items = list(values)
    return [items[index : index + size] for index in range(0, len(items), size)]


def _should_split(exc: Exception, span: int, min_split_span: int) -> bool:
    if span <= min_split_span:
        return False
    message = str(exc).lower()
    return any(keyword in message for keyword in SPLIT_KEYWORDS)


def fetch_logs(
    w3,
    *,
    from_block: int,
    to_block: int,
    address: str | list[str] | None = None,
    topics: list[Any] | None = None,
    min_split_span: int = 256,
    block_hashes: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    if block_hashes is not None:
        logs = []
        for number in range(from_block, to_block + 1):
            params = {"blockHash": block_hashes[number]}
            if address is not None:
                params["address"] = (w3.to_checksum_address(address) if isinstance(address, str)
                                     else [w3.to_checksum_address(item) for item in address])
            if topics is not None:
                params["topics"] = topics
            block_logs = list(w3.eth.get_logs(params))
            from .observations import BranchChanged
            from .types import normalize_hex

            if any(int(log["blockNumber"]) != number or normalize_hex(log["blockHash"]) != block_hashes[number]
                   for log in block_logs):
                raise BranchChanged(f"Log response does not match requested block {number}")
            logs.extend(block_logs)
        return logs
    try:
        params: dict[str, Any] = {"fromBlock": from_block, "toBlock": to_block}
        if address is not None:
            if isinstance(address, str):
                params["address"] = w3.to_checksum_address(address)
            else:
                params["address"] = [w3.to_checksum_address(item) for item in address]
        if topics is not None:
            params["topics"] = topics
        return list(w3.eth.get_logs(params))
    except Exception as exc:
        span = to_block - from_block
        if not _should_split(exc, span, min_split_span):
            raise
        midpoint = from_block + (span // 2)
        left = fetch_logs(
            w3,
            from_block=from_block,
            to_block=midpoint,
            address=address,
            topics=topics,
            min_split_span=min_split_span,
        )
        right = fetch_logs(
            w3,
            from_block=midpoint + 1,
            to_block=to_block,
            address=address,
            topics=topics,
            min_split_span=min_split_span,
        )
        return left + right


def sort_logs(logs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        logs,
        key=lambda entry: (
            int(entry["blockNumber"]),
            int(entry.get("transactionIndex", 0)),
            int(entry["logIndex"]),
        ),
    )
