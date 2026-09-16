from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class SignalType(str, Enum):
    STATIC = "Static"      # Σq stably < 1 over K seconds (typical margin 2-6%)
    DYNAMIC = "Dynamic"    # Sudden price jump on platform A while B hasn't updated yet (margin 10%+)


class Outcome(BaseModel):
    name: str
    price: float  # For Polymarket: decimal price 0-1 (cents / 100). For BK: decimal odds (e.g. 1.85)


class StandardizedEvent(BaseModel):
    event_id: str
    platform: str  # e.g., "Polymarket", "Pinnacle", "1xBet", "MockBK"
    game: str      # e.g., "CS2", "Dota 2", "LoL"
    tournament: str
    team1: str
    team2: str
    start_time: Optional[datetime] = None
    market_type: str = "winner"  # Match winner / Moneyline
    outcomes: List[Outcome]
    timestamp: float = Field(default_factory=lambda: datetime.now().timestamp())
    market_url: Optional[str] = None
    clob_token_ids: Optional[List[str]] = None  # Polymarket token IDs for CLOB depth lookup


class OrderbookLevel(BaseModel):
    price: float
    size: float


class Orderbook(BaseModel):
    token_id: str
    bids: List[OrderbookLevel] = Field(default_factory=list)  # Highest price first
    asks: List[OrderbookLevel] = Field(default_factory=list)  # Lowest price first
    timestamp: float = Field(default_factory=lambda: datetime.now().timestamp())

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None

    @property
    def mid_price(self) -> Optional[float]:
        if self.best_bid is not None and self.best_ask is not None:
            return (self.best_bid + self.best_ask) / 2.0
        return self.best_ask or self.best_bid


class PriceSnapshot(BaseModel):
    platform: str
    event_id: str
    token_id: Optional[str] = None
    outcome: str
    price: float
    timestamp: float = Field(default_factory=lambda: datetime.now().timestamp())


class MatchedPair(BaseModel):
    bk_event_id: str
    polymarket_event_id: str
    confidence: float
    match_type: str  # "exact" or "partial"
    rules_compatible: bool
    rules_note: str = ""
    updated_at: float = Field(default_factory=lambda: datetime.now().timestamp())


class ArbitrageOpportunity(BaseModel):
    signal_id: Optional[str] = None
    signal_type: SignalType = SignalType.STATIC
    event_title: str
    game: str
    tournament: str
    team1: str
    team2: str
    start_time: Optional[datetime] = None
    
    # Bookmaker leg
    bk_platform: str
    bk_event_id: str
    bk_market_url: Optional[str] = None
    bk_team1_odds: float
    bk_team2_odds: float
    bk_implied_prob1: float
    bk_implied_prob2: float
    
    # Polymarket leg
    poly_event_id: str
    poly_market_url: Optional[str] = None
    poly_team1_vwap: float
    poly_team2_vwap: float
    poly_team1_top_price: float
    poly_team2_top_price: float
    poly_implied_prob1: float
    poly_implied_prob2: float
    
    # Selected leg distribution
    poly_outcome_selected: str  # Which outcome to buy on Polymarket (e.g. "team1" or "team2")
    poly_stake: float
    bk_stake: float
    total_stake: float
    
    # Probability sum & profitability metrics
    sum_implied_prob: float
    profit_pct: float            # Guaranteed ROI
    net_profit_usd: float
    leg1_profit_usd: float       # Profit if Outcome 1 wins
    leg2_profit_usd: float       # Profit if Outcome 2 wins
    
    # Liquidity & Execution
    max_executable_stake_usd: float = 0.0
    slippage_pct: float = 0.0
    
    # Dynamic desync tracking
    price_change_delta_pct: float = 0.0  # e.g., 8.5% price jump
    
    # Timestamps & staleness
    poly_timestamp: float
    bk_timestamp: float
    data_freshness_sec: float
    detected_at: float = Field(default_factory=lambda: datetime.now().timestamp())
    ttl_sec: int = 60            # Dynamic signal expiration in seconds
    
    status: str = "new"          # "new", "accepted", "skipped", "expired"


class ExecutedTrade(BaseModel):
    trade_id: Optional[str] = None
    signal_id: str
    user_action: str             # "accepted" or "skipped"
    actual_winner: Optional[str] = None
    actual_profit_usd: Optional[float] = None
    timestamp: float = Field(default_factory=lambda: datetime.now().timestamp())


class SourceHealth(BaseModel):
    source_name: str
    last_updated: float
    is_healthy: bool
    message: str = ""

