from __future__ import annotations

from backend.indexer.polling import fetch_logs


class _FakeEth:
    def __init__(self) -> None:
        self.params = None

    def get_logs(self, params):
        self.params = params
        return []


class _FakeWeb3:
    def __init__(self) -> None:
        self.eth = _FakeEth()

    @staticmethod
    def to_checksum_address(address: str) -> str:
        return f"checksum:{address}"


def test_fetch_logs_checksums_address_lists():
    w3 = _FakeWeb3()

    fetch_logs(
        w3,
        from_block=1,
        to_block=2,
        address=[
            "0x00000000000000000000000000000000000000aa",
            "0x00000000000000000000000000000000000000bb",
        ],
        topics=["0xtopic"],
    )

    assert w3.eth.params == {
        "fromBlock": 1,
        "toBlock": 2,
        "address": [
            "checksum:0x00000000000000000000000000000000000000aa",
            "checksum:0x00000000000000000000000000000000000000bb",
        ],
        "topics": ["0xtopic"],
    }


def test_fetch_logs_adaptively_splits_large_ranges_and_preserves_order():
    class _SplittingEth:
        def __init__(self) -> None:
            self.calls = []

        def get_logs(self, params):
            self.calls.append(dict(params))
            if params["fromBlock"] != params["toBlock"]:
                raise RuntimeError("query returned more than provider limit")
            block_number = params["fromBlock"]
            return [{"blockNumber": block_number}]

    w3 = _FakeWeb3()
    w3.eth = _SplittingEth()

    logs = fetch_logs(
        w3,
        from_block=1,
        to_block=4,
        address="0x00000000000000000000000000000000000000aa",
        topics=[["0x01", "0x02"]],
        min_split_span=0,
    )

    assert [item["blockNumber"] for item in logs] == [1, 2, 3, 4]
    assert len(w3.eth.calls) == 7
    assert all(call["address"] == "checksum:0x00000000000000000000000000000000000000aa" for call in w3.eth.calls)
    assert all(call["topics"] == [["0x01", "0x02"]] for call in w3.eth.calls)
