from __future__ import annotations

from dataclasses import dataclass

from web3 import HTTPProvider, Web3
from web3.middleware import ExtraDataToPOAMiddleware
from .observations import BlockReader

from .types import ChainConfig, IndexedBlockRecord, normalize_hex


@dataclass
class ChainState:
    config: ChainConfig
    w3: Web3
    reader: BlockReader | None = None

    @classmethod
    def from_config(cls, config: ChainConfig) -> "ChainState":
        provider = HTTPProvider(config.rpc_url, request_kwargs={"timeout": 60})
        w3 = Web3(provider)
        if config.poa:
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        return cls(config=config, w3=w3)

    def latest_head(self) -> int:
        return int(self.w3.eth.block_number)

    @property
    def finality_mode(self) -> str:
        return "finalized" if self.config.chain_id == 1 else "confirmations"

    def confirmed_header(self, latest_head: int) -> IndexedBlockRecord:
        if self.finality_mode == "finalized":
            return self.block_header("finalized")
        return self.block_header(max(0, latest_head - self.config.finality_depth))

    def block_header(self, block_number: int | str) -> IndexedBlockRecord:
        block = self.w3.eth.get_block(block_number)
        header = IndexedBlockRecord(
            chain_id=self.config.chain_id,
            block_number=int(block["number"]),
            block_hash=normalize_hex(block["hash"]),
            parent_hash=normalize_hex(block["parentHash"]),
            timestamp=int(block["timestamp"]),
        )
        return header

    def block_timestamp(self, block_number: int) -> int:
        if self.reader is not None:
            return self.reader.header(block_number).timestamp
        return self.block_header(block_number).timestamp
