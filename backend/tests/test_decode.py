from hexbytes import HexBytes
from web3 import Web3

from backend.indexer.config import load_settings
from backend.indexer.decode import AbiRegistry


def _addr(value: int) -> str:
    return f"0x{value:040x}"


def test_decode_auction_kicked(monkeypatch, tmp_path):
    monkeypatch.setenv("ETHEREUM_RPC_URL", "http://localhost:8545")
    settings = load_settings(
        db_path=str(tmp_path / "auctionscan.sqlite3"),
        target_network="ethereum",
    )
    registry = AbiRegistry(settings)
    from_address = _addr(0x123)
    available = 42

    log = {
        "address": _addr(0xAAA),
        "topics": [
            HexBytes(registry.auction_event_topic("1.0.4", "AuctionKicked")),
            HexBytes(int(from_address, 16).to_bytes(32, "big")),
        ],
        "data": HexBytes(available.to_bytes(32, "big")),
        "blockNumber": 10,
        "blockHash": HexBytes(b"\x01" * 32),
        "transactionHash": HexBytes(b"\x02" * 32),
        "transactionIndex": 3,
        "logIndex": 7,
    }

    event = registry.decode_auction_log(
        Web3(),
        "1.0.4",
        log,
        chain_id=1,
        timestamp=123,
    )

    assert event.event_name == "AuctionKicked"
    assert event.auction_address == _addr(0xAAA)
    assert event.payload["from"] == from_address
    assert event.payload["available"] == available
