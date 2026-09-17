from __future__ import annotations

import logging
from typing import Any, Optional

from .chains import ChainState
from .decode import AbiRegistry
from .types import AuctionSnapshot, TokenMetadata, decimal_text, normalize_address
from .versioning import uses_legacy_auction_id


logger = logging.getLogger(__name__)


def _snapshot_call(chain, contract, function_name: str, *, block_number: int) -> Any:
    if not hasattr(contract.functions, function_name):
        return None
    fn = getattr(contract.functions, function_name)
    return chain.reader.call(fn(), block_number)


def _read_legacy_auction_state(chain, contract, auction_id: str, *, block_number: int) -> dict[str, Any]:
    value = chain.reader.call(contract.functions.auctions(auction_id), block_number)

    if isinstance(value, dict):
        from_info = value.get("fromInfo") or {}
        return {
            "from": from_info.get("tokenAddress"),
            "receiver": value.get("receiver"),
            "initialAvailable": value.get("initialAvailable"),
            "currentAvailable": value.get("currentAvailable"),
            "kicked": value.get("kicked"),
        }

    try:
        from_info, kicked, receiver, initial_available, current_available = value
        from_token = None
        if isinstance(from_info, dict):
            from_token = from_info.get("tokenAddress")
        elif isinstance(from_info, (list, tuple)) and from_info:
            from_token = from_info[0]
        return {
            "from": from_token,
            "receiver": receiver,
            "initialAvailable": initial_available,
            "currentAvailable": current_available,
            "kicked": kicked,
        }
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Malformed legacy auction snapshot at block {block_number}") from exc


class Hydrator:
    def __init__(self, abi_registry: AbiRegistry) -> None:
        self.abi_registry = abi_registry

    def read_auction_snapshot(
        self,
        chain: ChainState,
        version: str,
        auction_address: str,
        block_number: int,
        *,
        event_payload: Optional[dict[str, Any]] = None,
    ) -> AuctionSnapshot:
        contract = self.abi_registry.auction_contract(chain.w3, auction_address, version)
        definition = self.abi_registry.version_definition(version)
        values: dict[str, Any] = {
            getter: _snapshot_call(chain, contract, getter, block_number=block_number)
            for getter in definition.getter_bundle
        }
        if uses_legacy_auction_id(version) and event_payload and event_payload.get("auctionId"):
            values.update(
                _read_legacy_auction_state(
                    chain,
                    contract,
                    event_payload["auctionId"],
                    block_number=block_number,
                )
            )

        extra_params: dict[str, Any] = {}
        if values.get("letCowPeek") is not None:
            extra_params["letCowPeek"] = bool(values["letCowPeek"])
        if values.get("auctionId") is not None:
            extra_params["auctionId"] = values["auctionId"]
        if values.get("currentAvailable") is not None:
            extra_params["currentAvailable"] = decimal_text(values["currentAvailable"])
        if values.get("initialAvailable") is not None:
            extra_params["initialAvailable"] = decimal_text(values["initialAvailable"])
        if values.get("kicked") is not None:
            extra_params["kicked"] = decimal_text(values["kicked"])

        return AuctionSnapshot(
            chain_id=chain.config.chain_id,
            auction_address=auction_address,
            block_number=block_number,
            want_token=normalize_address(values["want"]) if values.get("want") else None,
            governance=normalize_address(values["governance"]) if values.get("governance") else None,
            receiver=normalize_address(values["receiver"]) if values.get("receiver") else None,
            starting_price_raw=decimal_text(values.get("startingPrice")),
            minimum_price_raw=decimal_text(values.get("minimumPrice")),
            step_decay_rate_raw=decimal_text(values.get("stepDecayRate")),
            step_duration_raw=decimal_text(values.get("stepDuration")),
            auction_length_raw=decimal_text(values.get("auctionLength")),
            extra_params=extra_params,
        )

    def read_token_metadata(
        self,
        chain: ChainState,
        token_address: str,
        *,
        block_number: Optional[int] = None,
    ) -> TokenMetadata:
        if block_number is None:
            raise ValueError("Token metadata requires an observed block")

        # These ERC-20 getters have no arguments. Their fixed calldata avoids
        # constructing and encoding a Web3 contract for every historical read.
        def read(data: str, output_type: str, *, optional: bool = False) -> Any:
            return chain.reader.call_encoded(token_address, data, (output_type,),
                                             block_number, optional=optional)

        return TokenMetadata(
            chain_id=chain.config.chain_id,
            token_address=normalize_address(token_address),
            symbol=read("0x95d89b41", "string", optional=True),
            name=read("0x06fdde03", "string", optional=True),
            decimals=read("0x313ce567", "uint8"),
        )
