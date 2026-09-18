from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class IndexedCheckpoint(BaseModel):
    """Aggregate values include all indexed events; they can extend beyond finality."""
    indexed_block: int | None
    indexed_block_hash: str | None
    indexed_timestamp: int | None
    confirmed_block: int | None
    confirmed_block_hash: str | None
    finality_mode: Literal["finalized", "confirmations"] | None


class IndexedResponse(BaseModel):
    as_of: dict[int, IndexedCheckpoint]


class ChainInfo(BaseModel):
    chain_id: int
    name: str
    short_name: str
    icon: str | None = None
    explorer: str | None = None
    emoji: str | None = None


class ChainsResponse(BaseModel):
    chains: dict[int, ChainInfo]
    count: int


class DiscoveryProblem(BaseModel):
    factory_address: str
    code: Literal["unsupported_version", "lookup_failed", "deployment_unresolved"]
    version: str | None


class DiscoveryStatus(BaseModel):
    status: Literal["ok", "partial", "stale", "unavailable"]
    known_factory_count: int
    last_attempt_at: int | None
    last_success_at: int | None
    last_error: str | None
    problems: list[DiscoveryProblem]


class HealthChain(BaseModel):
    chain_id: int
    network_name: str
    name: str
    short_name: str
    start_block: int | None = None
    latest_rpc_head: int | None = None
    confirmed_head: int | None = None
    last_confirmed_processed: int | None = None
    last_live_processed: int | None = None
    block_lag: int | None = None
    last_success_at: int | None = None
    latest_rpc_head_timestamp: int | None = None
    finality_mode: Literal["finalized", "confirmations"] | None = None
    confirmed_head_hash: str | None = None
    confirmed_head_timestamp: int | None = None
    last_confirmed_hash: str | None = None
    last_finality_advance_at: int | None = None
    finality_warning: str | None = None
    health_detail: str | None = None
    reorg_count: int = 0
    last_reorg_at: int | None = None
    health: str
    last_error: str | None = None
    indexed: bool
    discovery: DiscoveryStatus


class HealthResponse(BaseModel):
    chains: list[HealthChain]
    count: int


class TokenModel(BaseModel):
    address: str
    symbol: str
    name: str
    decimals: int
    chain_id: int
    logo_url: str | None = None


class TokensResponse(BaseModel):
    tokens: list[TokenModel]
    count: int


class PriceSourceOption(BaseModel):
    id: str
    label: str
    is_default: bool
    usd_priced_take_count: int = 0
    priced_take_count: int
    total_take_count: int
    priced_volume_share: float | None = None


class TakePricingBySource(BaseModel):
    market_quote_out: str | None = None
    market_quote_out_usd: str | None = None
    pnl_usd: str | None = None
    pnl_percent: float | None = None
    pricing_status: str | None = None


class RoundPricingBySource(BaseModel):
    total_market_quote_usd: str | None = None
    total_auction_profit_usd: str | None = None
    total_auction_profit_bps: float | None = None
    usd_priced_take_count: int = 0
    priced_take_count: int
    total_take_count: int
    priced_volume_share: float | None = None


class SourceOccurrence(BaseModel):
    chain_id: int
    block_hash: str
    tx_hash: str
    log_index: int


class RoundListItem(BaseModel):
    occurrence: SourceOccurrence
    chain_id: int
    auction_address: str
    round_id: int
    status: Literal["live", "sold_out", "expired", "settled"]
    is_active: bool
    from_token: str | None = None
    from_token_symbol: str | None = None
    from_token_name: str | None = None
    from_token_decimals: int | None = None
    from_token_logo_url: str | None = None
    want_token: str | None = None
    want_token_symbol: str | None = None
    want_token_name: str | None = None
    want_token_decimals: int | None = None
    want_token_logo_url: str | None = None
    kicked_at: str
    scheduled_end_at: str | None = None
    end_at: str | None = None
    last_take_at: str | None = None
    activity_at: str
    take_count: int
    sold_amount: str
    paid_amount: str | None
    paid_take_count: int
    avg_execution_price: str | None = None
    last_take_price: str | None = None
    available_amount: str | None = None
    initial_available: str | None = None
    receiver: str | None = None
    receiver_name: str | None = None
    version: str | None = None
    update_interval: int | None = None
    decay_percent: str | None = None
    auction_length: int | None = None
    starting_price: str | None = None
    starting_price_per_unit: str | None = None
    minimum_price: str | None = None
    expected_price_per_unit: str | None = None
    kick_market_quote: str | None = None
    kick_market_quote_usd: str | None = None
    paid_usd_take_count: int = 0
    total_actual_paid_usd: str | None = None
    total_market_quote_usd: str | None = None
    total_auction_profit_usd: str | None = None
    total_auction_profit_bps: float | None = None
    usd_priced_take_count: int = 0
    priced_take_count: int | None = None
    total_take_count: int | None = None
    priced_volume_share: float | None = None
    pricing_by_source: dict[str, RoundPricingBySource] | None = None


class RoundsResponse(IndexedResponse):
    rounds: list[RoundListItem]
    total: int
    page: int
    per_page: int
    has_next: bool


class RoundLivePrice(BaseModel):
    occurrence: SourceOccurrence
    indexed_block: int
    indexed_block_hash: str
    indexed_timestamp: int
    chain_id: int
    auction_address: str
    round_id: int
    is_active: bool
    current_price_raw: str | None = None
    current_price: str | None = None


class RoundDetailResponse(IndexedResponse):
    round: RoundListItem


class AuctionParameters(BaseModel):
    update_interval: int | None = None
    decay_percent: str | None = None
    auction_length: int | None = None
    starting_price: str | None = None
    minimum_price: str | None = None


class AuctionActivity(BaseModel):
    total_participants: int
    total_volume: str | None
    paid_take_count: int
    total_rounds: int
    total_takes: int


class AuctionDetails(IndexedResponse):
    address: str
    chain_id: int
    receiver: str | None = None
    receiver_name: str | None = None
    version: str | None = None
    from_tokens: list[TokenModel]
    want_token: TokenModel
    parameters: AuctionParameters
    activity: AuctionActivity


class AuctionListItem(BaseModel):
    address: str
    chain_id: int
    receiver: str | None = None
    receiver_name: str | None = None
    version: str | None = None
    want_token: TokenModel | None = None
    total_rounds: int
    total_takes: int
    latest_activity_at: str | None = None


class AuctionsResponse(IndexedResponse):
    auctions: list[AuctionListItem]
    total: int
    page: int
    per_page: int
    has_next: bool


class AuctionVersionOption(BaseModel):
    version: str
    auction_count: int
    round_count: int


class AuctionVersionsResponse(IndexedResponse):
    versions: list[AuctionVersionOption]
    count: int


class TakeListItem(BaseModel):
    occurrence: SourceOccurrence
    round_occurrence: SourceOccurrence
    auction: str
    chain_id: int
    round_id: int
    take_seq: int
    taker: str
    amount_taken: str
    amount_paid: str | None
    expected_amount_paid: str | None = None
    price: str | None = None
    timestamp: str
    tx_hash: str
    block_number: int
    confirmed: bool
    receiver: str | None = None
    receiver_name: str | None = None
    from_token: str | None = None
    to_token: str | None = None
    from_token_symbol: str | None = None
    from_token_name: str | None = None
    from_token_decimals: int | None = None
    from_token_logo_url: str | None = None
    to_token_symbol: str | None = None
    to_token_name: str | None = None
    to_token_decimals: int | None = None
    to_token_logo_url: str | None = None
    amount_paid_usd: str | None = None
    market_quote_out: str | None = None
    market_quote_out_usd: str | None = None
    want_token_price_usd: str | None = None
    price_differential_usd: str | None = None
    price_differential_percent: float | None = None
    pricing_status: str | None = None
    provider_success_count: int | None = None
    quote_spread_bps: int | None = None
    pricing_by_source: dict[str, TakePricingBySource] | None = None


class PricingQuoteProvider(BaseModel):
    provider_id: str
    provider_position: int
    participation_status: str
    amount_in_raw: str | None = None
    amount_out_raw: str | None = None
    amount_out: str | None = None
    amount_out_min_raw: str | None = None
    amount_out_min: str | None = None
    price_impact_bps: int | None = None
    estimated_gas: int | None = None
    latency_ms: int | None = None
    as_of: str | None = None
    retrieved_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_retry_after_ms: int | None = None


class PricingQuoteFact(BaseModel):
    id: int
    capture_state: str
    context_kind: str
    captured_at: str
    capture_lag_seconds: int
    request_id: str | None = None
    canonical_amount_out: str | None = None
    low_amount_out: str | None = None
    high_amount_out: str | None = None
    spread_bps: int | None = None
    provider_success_count: int
    providers: list[PricingQuoteProvider]


class PricingPriceProvider(BaseModel):
    provider_id: str
    provider_position: int
    participation_status: str
    price_usd: str | None = None
    latency_ms: int | None = None
    as_of: str | None = None
    retrieved_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_retry_after_ms: int | None = None


class PricingPriceFact(BaseModel):
    id: int
    capture_state: str
    context_kind: str
    captured_at: str
    capture_lag_seconds: int
    request_id: str | None = None
    canonical_price_usd: str | None = None
    provider_success_count: int
    providers: list[PricingPriceProvider]


class TakeDetail(TakeListItem):
    quote_facts: list[PricingQuoteFact] | None = None
    price_facts: list[PricingPriceFact] | None = None


class AuctionTakesResponse(IndexedResponse):
    takes: list[TakeListItem]
    available_price_sources: list[PriceSourceOption]


class TakerSummary(BaseModel):
    taker: str
    total_takes: int
    unique_auctions: int
    unique_chains: int
    paid_usd_take_count: int = 0
    total_volume_usd: float | None = None
    avg_take_size_usd: float | None = None
    total_taker_profit_usd: float | None = None
    avg_taker_profit_usd: float | None = None
    priced_take_count: int | None = None
    priced_volume_share: float | None = None
    last_take: str | None = None
    first_take: str | None = None
    rank_by_takes: int
    rank_by_volume: int | None = None
    active_chains: list[int]


class TakerListResponse(IndexedResponse):
    takers: list[TakerSummary]
    total: int
    page: int
    per_page: int
    has_next: bool


class TakerAuctionBreakdown(BaseModel):
    auction_address: str
    chain_id: int
    takes_count: int
    paid_usd_take_count: int
    priced_take_count: int
    volume_usd: float | None = None
    taker_profit_usd: float | None = None
    last_take: str | None = None
    first_take: str | None = None


class TakerDetail(IndexedResponse):
    taker: str
    total_takes: int
    unique_auctions: int
    unique_chains: int
    paid_usd_take_count: int = 0
    total_volume_usd: float | None = None
    avg_take_size_usd: float | None = None
    total_taker_profit_usd: float | None = None
    avg_taker_profit_usd: float | None = None
    priced_take_count: int | None = None
    priced_volume_share: float | None = None
    last_take: str | None = None
    first_take: str | None = None
    rank_by_takes: int
    rank_by_volume: int | None = None
    active_chains: list[int]
    auction_breakdown: list[TakerAuctionBreakdown]


class TakerTake(BaseModel):
    occurrence: SourceOccurrence
    round_occurrence: SourceOccurrence
    chain_id: int
    auction_address: str
    round_id: int
    take_seq: int | None = None
    taker: str
    timestamp: str
    tx_hash: str
    amount_taken: str | None = None
    amount_paid: str | None = None
    expected_amount_paid: str | None = None
    price: str | None = None
    price_usd: float | None = None
    taker_profit_usd: float | None = None
    pricing_status: str | None = None
    pricing_by_source: dict[str, TakePricingBySource] | None = None


class TakerTakesResponse(IndexedResponse):
    takes: list[TakerTake]
    total_count: int
    page: int
    limit: int
    total_pages: int
    available_price_sources: list[PriceSourceOption] = []


class SearchResult(BaseModel):
    type: Literal["auction", "transaction", "kick_transaction", "taker", "token"]
    chain_id: int
    address_or_hash: str
    metadata: dict[str, object] | None = None


class SearchResponse(BaseModel):
    results: list[SearchResult]
    total: int
    query: str


class TxResolveDestination(BaseModel):
    occurrence: SourceOccurrence | None = None
    take_occurrence: SourceOccurrence | None = None
    kind: Literal["round", "auction"]
    chain_id: int
    auction_address: str
    round_id: int | None = None


class TxResolveResponse(BaseModel):
    normalized_tx_hash: str | None = None
    outcome: Literal["resolved", "ambiguous", "not_found", "invalid"]
    kind: Literal["take", "kick", "deployment"] | None = None
    destination: TxResolveDestination | None = None
