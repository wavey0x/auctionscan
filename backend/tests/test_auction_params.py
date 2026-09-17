from backend.indexer.auction_params import RawAuctionParams, decode_params, param_schema_for_version


def test_decode_params_scales_1_0_5_starting_and_minimum_prices_from_wad():
    assert param_schema_for_version("1.0.5") == "v1_wad_start_wad_bps"

    decoded = decode_params(
        "v1_wad_start_wad_bps",
        RawAuctionParams(
            minimum_price_raw="50000000000000000000",
            starting_price_raw="100000000000000000000",
            step_decay_rate_raw="25",
            step_duration_raw="60",
            auction_length_raw="86400",
        ),
    )

    assert decoded.starting_price == "100"
    assert decoded.minimum_price == "50"
    assert decoded.step_decay_percent == "0.25"
    assert decoded.step_duration_seconds == 60
    assert decoded.auction_length_seconds == 86400


def test_decode_params_keeps_1_0_4_starting_price_unscaled():
    decoded = decode_params(
        "v1_wad_bps",
        RawAuctionParams(
            minimum_price_raw="50000000000000000000",
            starting_price_raw="100",
            step_decay_rate_raw="25",
            step_duration_raw="60",
            auction_length_raw="86400",
        ),
    )

    assert decoded.starting_price == "100"
    assert decoded.minimum_price == "50"
