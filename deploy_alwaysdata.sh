#!/bin/bash
set -e
echo '🚀 Starting automatic deployment on Alwaysdata...'
mkdir -p ~/polymarket-arb
cd ~/polymarket-arb
mkdir -p parsers matcher calculator database bot

cat << 'EOF' > .env
TELEGRAM_BOT_TOKEN=8947405682:AAGcPgP0VQmwzTEb0CHDUZBfe9O6AgVESW0
TELEGRAM_CHAT_ID=1638163747
POLYMARKET_GAMMA_API_URL=https://gamma-api.polymarket.com/events
POLYMARKET_CLOB_REST_URL=https://clob.polymarket.com/book
POLYMARKET_CLOB_WS_URL=wss://ws-subscriptions-clob.polymarket.com/ws/market
ODDS_API_KEY=
ODDS_API_URL=https://api.the-odds-api.com/v4/sports
TYPICAL_STAKE_USD=1000.0
MIN_PROFIT_THRESHOLD_PCT=5.0
POLYMARKET_TAKER_FEE_PCT=2.0
MAX_SLIPPAGE_PCT=1.0
DYNAMIC_DESYNC_DELTA_PCT=5.0
DYNAMIC_DESYNC_WINDOW_SEC=5.0
DYNAMIC_SIGNAL_TTL_SEC=30
STALE_DATA_THRESHOLD_SEC=30
POLYMARKET_POLL_INTERVAL_SEC=10
BOOKMAKER_POLL_INTERVAL_SEC=2
MATCHING_INTERVAL_SEC=60
DATABASE_PATH=polymarket_arb.db
REDIS_URL=redis://localhost:6379/0
FUZZY_MATCH_THRESHOLD=80.0
MATCH_TIME_WINDOW_MINUTES=30
EOF

cat << 'EOF' > config.py
import os
from pathlib import Path
from typing import Dict, List
from dotenv import load_dotenv

# Load .env file if available
env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Polymarket Endpoints
POLYMARKET_GAMMA_API_URL = os.getenv("POLYMARKET_GAMMA_API_URL", "https://gamma-api.polymarket.com/events")
POLYMARKET_CLOB_REST_URL = os.getenv("POLYMARKET_CLOB_REST_URL", "https://clob.polymarket.com/book")
POLYMARKET_CLOB_WS_URL = os.getenv("POLYMARKET_CLOB_WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/market")

# Odds API / Bookmaker Endpoints
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ODDS_API_URL = os.getenv("ODDS_API_URL", "https://api.the-odds-api.com/v4/sports")

# Trading & Risk Parameters
TYPICAL_STAKE_USD = float(os.getenv("TYPICAL_STAKE_USD", "1000.0"))
MIN_PROFIT_THRESHOLD_PCT = float(os.getenv("MIN_PROFIT_THRESHOLD_PCT", "5.0"))
POLYMARKET_TAKER_FEE_PCT = float(os.getenv("POLYMARKET_TAKER_FEE_PCT", "2.0"))
MAX_SLIPPAGE_PCT = float(os.getenv("MAX_SLIPPAGE_PCT", "1.0"))

# Dynamic Desync Signal Thresholds
DYNAMIC_DESYNC_DELTA_PCT = float(os.getenv("DYNAMIC_DESYNC_DELTA_PCT", "5.0"))   # % move in price
DYNAMIC_DESYNC_WINDOW_SEC = float(os.getenv("DYNAMIC_DESYNC_WINDOW_SEC", "5.0"))  # within seconds
DYNAMIC_SIGNAL_TTL_SEC = int(os.getenv("DYNAMIC_SIGNAL_TTL_SEC", "30"))           # Signal TTL in Telegram

# Health & Staleness
STALE_DATA_THRESHOLD_SEC = int(os.getenv("STALE_DATA_THRESHOLD_SEC", "30"))
POLYMARKET_POLL_INTERVAL_SEC = int(os.getenv("POLYMARKET_POLL_INTERVAL_SEC", "10"))
BOOKMAKER_POLL_INTERVAL_SEC = int(os.getenv("BOOKMAKER_POLL_INTERVAL_SEC", "2"))

# Database & Redis
DATABASE_PATH = os.getenv("DATABASE_PATH", "polymarket_arb.db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Fuzzy Matching Thresholds
FUZZY_MATCH_THRESHOLD = float(os.getenv("FUZZY_MATCH_THRESHOLD", "80.0"))
MATCH_TIME_WINDOW_MINUTES = int(os.getenv("MATCH_TIME_WINDOW_MINUTES", "30"))

# Target Esports & Tournaments (Top liquidity focus)
TRACKED_ESPORTS = {
    "CS2": ["IEM", "BLAST", "Major", "ESL Pro League", "PGL"],
    "Dota 2": ["The International", "BLAST Slam", "Riyadh Masters", "DreamLeague", "ESL One"],
    "LoL": ["LPL", "LCK", "Worlds", "MSI"]
}

# Manual Matched Pairs Override (BK Event ID -> Polymarket Event ID)
MANUAL_MATCHED_PAIRS: Dict[str, str] = {
    # Example: "bk_cs2_navi_faZe": "poly_12345"
}

EOF

cat << 'EOF' > data_models.py
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

EOF

cat << 'EOF' > requirements.txt
aiohttp>=3.9.0
pydantic>=2.5.0
python-dotenv>=1.0.0
aiosqlite>=0.19.0
aiogram>=3.3.0
websockets>=12.0
rapidfuzz>=3.0.0
gradio>=4.0.0
pytest>=8.0.0
pytest-asyncio>=0.23.0

EOF

cat << 'EOF' > main.py
import asyncio
import logging
import signal
import sys
import time
from typing import Dict, List, Optional

import config
from data_models import StandardizedEvent, Orderbook, MatchedPair, ArbitrageOpportunity
from database.storage import DatabaseStorage
from matcher.fuzzy_matcher import EventMatcher
from calculator.desync_engine import DesyncDetector
from parsers.polymarket_ws import PolymarketWSParser
from parsers.mock_bookmaker import MockBookmakerParser
from parsers.odds_api import OddsApiParser
from bot.telegram_bot import TelegramNotifier

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("polymarket_desync.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("main")


class DesyncScannerApp:
    def __init__(self):
        self.storage = DatabaseStorage(config.DATABASE_PATH)
        self.matcher = EventMatcher()
        self.detector = DesyncDetector()
        self.notifier = TelegramNotifier()

        self.poly_ws = PolymarketWSParser()
        self.mock_bk = MockBookmakerParser()
        self.odds_api = OddsApiParser()

        self.matched_pairs: Dict[str, MatchedPair] = {}  # poly_event_id -> MatchedPair
        self.processed_signal_ids = set()
        self._running = False

    async def _on_poly_update(self, token_id: str, orderbook: Orderbook):
        """Low-latency callback triggered instantly when Polymarket orderbook updates."""
        if not self._running:
            return

        event_id = self.poly_ws.token_to_event.get(token_id)
        if not event_id:
            return

        poly_event = self.poly_ws.active_events.get(event_id)
        if not poly_event:
            return

        # Check matched BK events
        matched = self.matched_pairs.get(event_id)
        if not matched:
            return

        # Get BK event
        bk_event = self.mock_bk.events.get(matched.bk_event_id) or self.odds_api.events.get(matched.bk_event_id)
        if not bk_event:
            return

        # Evaluate desync
        signals = self.detector.evaluate_desync(
            poly_event=poly_event,
            bk_event=bk_event,
            poly_orderbooks=self.poly_ws.orderbooks,
            matched_pair=matched
        )

        for sig in signals:
            sig_key = f"{sig.poly_event_id}:{sig.poly_outcome_selected}:{sig.profit_pct:.1f}"
            if sig_key not in self.processed_signal_ids:
                self.processed_signal_ids.add(sig_key)
                logger.info(f"🚨 [{sig.signal_type.value.upper()}] Signal Detected: {sig.event_title} | ROI: +{sig.profit_pct}%")
                await self.storage.save_arb_signal(sig)
                await self.notifier.send_alert(sig)

    async def _on_bk_update(self, bk_event: StandardizedEvent):
        """Low-latency callback triggered instantly when Bookmaker odds update."""
        if not self._running:
            return

        # Find matching Polymarket event
        for poly_id, matched in self.matched_pairs.items():
            if matched.bk_event_id == bk_event.event_id:
                poly_event = self.poly_ws.active_events.get(poly_id)
                if not poly_event:
                    continue

                signals = self.detector.evaluate_desync(
                    poly_event=poly_event,
                    bk_event=bk_event,
                    poly_orderbooks=self.poly_ws.orderbooks,
                    matched_pair=matched
                )

                for sig in signals:
                    sig_key = f"{sig.poly_event_id}:{sig.poly_outcome_selected}:{sig.profit_pct:.1f}"
                    if sig_key not in self.processed_signal_ids:
                        self.processed_signal_ids.add(sig_key)
                        logger.info(f"🚨 [{sig.signal_type.value.upper()}] Signal Detected: {sig.event_title} | ROI: +{sig.profit_pct}%")
                        await self.storage.save_arb_signal(sig)
                        await self.notifier.send_alert(sig)

    async def _matching_loop(self):
        """Periodic loop to refresh event matching between platforms."""
        while self._running:
            try:
                poly_events = list(self.poly_ws.active_events.values())
                bk_events = list(self.mock_bk.events.values()) + list(self.odds_api.events.values())

                if poly_events and bk_events:
                    matches = self.matcher.match_events(bk_events, poly_events)
                    for m in matches:
                        self.matched_pairs[m.polymarket_event_id] = m
                        await self.storage.save_matched_pair(m)
                    logger.info(f"Refreshed event matcher: {len(self.matched_pairs)} active matched pairs")
            except Exception as e:
                logger.error(f"Error in matching loop: {e}")

            await asyncio.sleep(config.MATCHING_INTERVAL_SEC if hasattr(config, 'MATCHING_INTERVAL_SEC') else 60)

    async def start(self):
        logger.info("Initializing Polymarket Probability Desync System...")
        await self.storage.init_db()

        self._running = True

        # Register update callbacks
        self.poly_ws.register_update_callback(self._on_poly_update)
        self.mock_bk.register_update_callback(self._on_bk_update)
        self.odds_api.register_update_callback(self._on_bk_update)

        # Start components
        await self.notifier.start_bot(self.storage)
        await self.poly_ws.start()
        await self.mock_bk.start()
        await self.odds_api.start()

        # Start matching loop task
        asyncio.create_task(self._matching_loop())
        logger.info("System fully operational and actively scanning for probability desyncs!")

    async def stop(self):
        logger.info("Stopping system...")
        self._running = False
        await self.poly_ws.stop()
        await self.mock_bk.stop()
        await self.odds_api.stop()
        logger.info("System stopped gracefully.")


async def main():
    app = DesyncScannerApp()
    await app.start()

    stop_event = asyncio.Event()

    def handle_signal():
        stop_event.set()

    loop = asyncio.get_running_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, handle_signal)
        except NotImplementedError:
            pass

    try:
        await stop_event.wait()
    finally:
        await app.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

EOF

cat << 'EOF' > matcher/normalization.py
import re
import unicodedata

# Common esports team alias mappings
TEAM_ALIASES = {
    "natus vincere": "navi",
    "faze clan": "faze",
    "g2 esports": "g2",
    "team spirit": "spirit",
    "virtus.pro": "vp",
    "virtus pro": "vp",
    "team liquid": "liquid",
    "astralis": "astralis",
    "mousesports": "mouz",
    "mouz": "mouz",
    "cloud9": "c9",
    "ninjas in pyjamas": "nip",
    "fnatic": "fnatic",
    "og": "og",
    "team secret": "secret",
    "evil geniuses": "eg",
    "t1": "t1",
    "gen.g": "geng",
    "gen g": "geng",
    "edward gaming": "edg",
    "royale never give up": "rng",
}

CYRILLIC_TO_LATIN = {
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'zh',
    'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
    'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
    'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
}


def transliterate(text: str) -> str:
    """Translates Cyrillic text to Latin text character by character."""
    res = []
    for char in text.lower():
        res.append(CYRILLIC_TO_LATIN.get(char, char))
    return "".join(res)


def normalize_string(text: str) -> str:
    """Normalizes string for matching: transliterate, lowercase, remove punctuation."""
    if not text:
        return ""
    text = transliterate(text.strip().lower())
    # Remove accents/diacritics
    text = "".join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )
    # Strip common prefix/suffix noise
    text = re.sub(r'\b(esports|gaming|team|club)\b', '', text)
    # Remove non-alphanumeric chars
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    # Normalize multiple spaces
    text = " ".join(text.split())
    
    # Apply alias mapping if exact match
    return TEAM_ALIASES.get(text, text)

EOF

cat << 'EOF' > matcher/fuzzy_matcher.py
import logging
from typing import List, Optional, Tuple, Dict
from datetime import datetime, timedelta

try:
    from rapidfuzz import fuzz
except ImportError:
    # Basic fallback if rapidfuzz is missing
    from difflib import SequenceMatcher
    class fuzz:
        @staticmethod
        def token_sort_ratio(s1: str, s2: str) -> float:
            return SequenceMatcher(None, s1, s2).ratio() * 100.0

import config
from data_models import StandardizedEvent, MatchedPair
from matcher.normalization import normalize_string

logger = logging.getLogger(__name__)


class EventMatcher:
    def __init__(
        self,
        similarity_threshold: float = config.FUZZY_MATCH_THRESHOLD,
        time_window_minutes: int = config.MATCH_TIME_WINDOW_MINUTES,
        manual_pairs: Optional[Dict[str, str]] = None
    ):
        self.similarity_threshold = similarity_threshold
        self.time_window = timedelta(minutes=time_window_minutes)
        self.manual_pairs = manual_pairs or config.MANUAL_MATCHED_PAIRS

    def _compare_teams(self, t1_a: str, t2_a: str, t1_b: str, t2_b: str) -> Tuple[float, bool]:
        """
        Calculates similarity score between two team pairs.
        Returns (confidence_score_0_to_1, is_reversed).
        """
        norm_t1_a = normalize_string(t1_a)
        norm_t2_a = normalize_string(t2_a)
        norm_t1_b = normalize_string(t1_b)
        norm_t2_b = normalize_string(t2_b)

        # Direct match score
        score_direct1 = fuzz.token_sort_ratio(norm_t1_a, norm_t1_b)
        score_direct2 = fuzz.token_sort_ratio(norm_t2_a, norm_t2_b)
        avg_direct = (score_direct1 + score_direct2) / 2.0

        # Reversed match score (Team A vs Team B vs Team B vs Team A)
        score_rev1 = fuzz.token_sort_ratio(norm_t1_a, norm_t2_b)
        score_rev2 = fuzz.token_sort_ratio(norm_t2_a, norm_t1_b)
        avg_reversed = (score_rev1 + score_rev2) / 2.0

        if avg_reversed > avg_direct:
            return avg_reversed / 100.0, True
        return avg_direct / 100.0, False

    def is_time_compatible(self, time1: Optional[datetime], time2: Optional[datetime]) -> bool:
        """Verifies if event start times are within the configured time window."""
        if not time1 or not time2:
            return True  # If start time is missing on one side, pass check
        return abs(time1 - time2) <= self.time_window

    def is_game_compatible(self, game1: str, game2: str) -> bool:
        """Verifies games/disciplines match."""
        g1 = game1.lower().replace(" ", "")
        g2 = game2.lower().replace(" ", "")
        return g1 == g2 or g1 in g2 or g2 in g1

    def match_events(
        self,
        bk_events: List[StandardizedEvent],
        poly_events: List[StandardizedEvent]
    ) -> List[MatchedPair]:
        """
        Matches bookmaker events against Polymarket events using normalization,
        fuzzy matching, time windows, and manual overrides.
        """
        matched_pairs: List[MatchedPair] = []

        # Index polymarket events by id for quick lookup
        poly_dict = {ev.event_id: ev for ev in poly_events}

        for bk_ev in bk_events:
            # 1. Manual override check
            if bk_ev.event_id in self.manual_pairs:
                poly_id = self.manual_pairs[bk_ev.event_id]
                if poly_id in poly_dict:
                    matched_pairs.append(MatchedPair(
                        bk_event_id=bk_ev.event_id,
                        polymarket_event_id=poly_id,
                        confidence=1.0,
                        match_type="exact",
                        rules_compatible=True,
                        rules_note="Manual override from config"
                    ))
                    continue

            best_match: Optional[StandardizedEvent] = None
            best_confidence: float = 0.0
            best_is_reversed: bool = False

            for poly_ev in poly_events:
                # 2. Sport / Game check
                if not self.is_game_compatible(bk_ev.game, poly_ev.game):
                    continue

                # 3. Start time window check
                if not self.is_time_compatible(bk_ev.start_time, poly_ev.start_time):
                    continue

                # 4. Fuzzy string match on teams
                confidence, is_reversed = self._compare_teams(
                    bk_ev.team1, bk_ev.team2,
                    poly_ev.team1, poly_ev.team2
                )

                if confidence > best_confidence and (confidence * 100.0) >= self.similarity_threshold:
                    best_confidence = confidence
                    best_match = poly_ev
                    best_is_reversed = is_reversed

            if best_match and best_confidence > 0:
                match_type = "exact" if best_confidence >= 0.95 else "partial"
                note = "Teams reversed" if best_is_reversed else "Match OK"
                matched_pairs.append(MatchedPair(
                    bk_event_id=bk_ev.event_id,
                    polymarket_event_id=best_match.event_id,
                    confidence=best_confidence,
                    match_type=match_type,
                    rules_compatible=True,
                    rules_note=note
                ))
                logger.info(f"Matched {bk_ev.team1} vs {bk_ev.team2} ({bk_ev.platform}) <-> {best_match.team1} vs {best_match.team2} (Polymarket) [Conf: {best_confidence:.2f}]")

        return matched_pairs

EOF

cat << 'EOF' > matcher/__init__.py
from matcher.fuzzy_matcher import EventMatcher
from matcher.normalization import normalize_string, transliterate

__all__ = ["EventMatcher", "normalize_string", "transliterate"]

EOF

cat << 'EOF' > calculator/vwap.py
from typing import List, Optional
import logging
from data_models import OrderbookLevel

logger = logging.getLogger(__name__)


def calculate_buy_vwap(asks: List[OrderbookLevel], target_stake_usd: float) -> Optional[float]:
    """
    Calculates the Volume-Weighted Average Price (VWAP) for buying an outcome
    on Polymarket orderbook for a given target stake in USD.
    
    :param asks: List of OrderbookLevel sorted by price ascending (lowest ask first).
    :param target_stake_usd: Total USD amount intended to spend.
    :return: Effective VWAP price (float between 0 and 1) or None if depth is insufficient.
    """
    if not asks or target_stake_usd <= 0:
        return None

    # Sort asks by price ascending (lowest price first) just in case
    sorted_asks = sorted(asks, key=lambda lvl: lvl.price)
    
    remaining_usd = target_stake_usd
    total_shares = 0.0

    for level in sorted_asks:
        if level.price <= 0 or level.size <= 0:
            continue
            
        level_value_usd = level.price * level.size
        
        if level_value_usd >= remaining_usd:
            shares_bought = remaining_usd / level.price
            total_shares += shares_bought
            remaining_usd = 0.0
            break
        else:
            total_shares += level.size
            remaining_usd -= level_value_usd

    if remaining_usd > 1e-6:
        # Insufficient depth in orderbook to fill the target stake
        return None

    vwap_price = target_stake_usd / total_shares
    return vwap_price

EOF

cat << 'EOF' > calculator/liquidity.py
import logging
from typing import List, Tuple, Optional
from data_models import Orderbook, OrderbookLevel
import config

logger = logging.getLogger(__name__)


def calculate_max_executable_liquidity(
    asks: List[OrderbookLevel],
    max_slippage_pct: float = config.MAX_SLIPPAGE_PCT
) -> Tuple[float, float]:
    """
    Calculates the maximum USD stake that can be executed on Polymarket asks
    without exceeding max_slippage_pct from the top ask price.

    Returns:
        (max_executable_usd, effective_vwap)
    """
    if not asks:
        return 0.0, 0.0

    sorted_asks = sorted(asks, key=lambda x: x.price)
    top_price = sorted_asks[0].price

    if top_price <= 0:
        return 0.0, 0.0

    max_allowed_price = top_price * (1.0 + (max_slippage_pct / 100.0))

    cum_usd = 0.0
    cum_shares = 0.0

    for level in sorted_asks:
        if level.price > max_allowed_price:
            break
        
        level_usd = level.price * level.size
        cum_usd += level_usd
        cum_shares += level.size

    effective_vwap = (cum_usd / cum_shares) if cum_shares > 0 else top_price
    return round(cum_usd, 2), round(effective_vwap, 4)

EOF

cat << 'EOF' > calculator/desync_engine.py
import uuid
import logging
import time
from typing import Optional, List, Dict
from datetime import datetime

import config
from data_models import (
    StandardizedEvent,
    Orderbook,
    MatchedPair,
    ArbitrageOpportunity,
    SignalType,
    PriceSnapshot,
)
from calculator.vwap import calculate_buy_vwap
from calculator.liquidity import calculate_max_executable_liquidity

logger = logging.getLogger(__name__)


class DesyncDetector:
    """
    Realtime Probability Engine & Desync Detector.
    Converts BK odds & Polymarket prices to implied probabilities,
    detects Static Arb and Dynamic Desync signals on EVERY price update.
    """
    def __init__(
        self,
        typical_stake_usd: float = config.TYPICAL_STAKE_USD,
        min_profit_pct: float = config.MIN_PROFIT_THRESHOLD_PCT,
        polymarket_fee_pct: float = config.POLYMARKET_TAKER_FEE_PCT,
        stale_threshold_sec: float = config.STALE_DATA_THRESHOLD_SEC,
        desync_delta_pct: float = config.DYNAMIC_DESYNC_DELTA_PCT,
        desync_window_sec: float = config.DYNAMIC_DESYNC_WINDOW_SEC,
        signal_ttl_sec: int = config.DYNAMIC_SIGNAL_TTL_SEC,
        max_slippage_pct: float = config.MAX_SLIPPAGE_PCT,
    ):
        self.typical_stake_usd = typical_stake_usd
        self.min_profit_pct = min_profit_pct
        self.fee_factor = 1.0 - (polymarket_fee_pct / 100.0)
        self.stale_threshold_sec = stale_threshold_sec
        self.desync_delta_pct = desync_delta_pct
        self.desync_window_sec = desync_window_sec
        self.signal_ttl_sec = signal_ttl_sec
        self.max_slippage_pct = max_slippage_pct

        # Price history buffer: key -> List[PriceSnapshot]
        self.price_history: Dict[str, List[PriceSnapshot]] = {}

    def is_fresh(self, timestamp: float, current_time: Optional[float] = None) -> bool:
        now = current_time or time.time()
        return (now - timestamp) <= self.stale_threshold_sec

    def record_price(self, platform: str, event_id: str, outcome: str, price: float, current_time: Optional[float] = None):
        """Records a price snapshot into rolling buffer for price jump detection."""
        now = current_time or time.time()
        key = f"{platform}:{event_id}:{outcome}"
        if key not in self.price_history:
            self.price_history[key] = []

        history = self.price_history[key]
        history.append(PriceSnapshot(
            platform=platform,
            event_id=event_id,
            outcome=outcome,
            price=price,
            timestamp=now
        ))

        # Prune snapshots older than 60 seconds
        cutoff = now - 60.0
        self.price_history[key] = [p for p in history if p.timestamp >= cutoff]

    def _detect_recent_price_jump(
        self,
        platform: str,
        event_id: str,
        outcome: str,
        current_price: float,
        now: float
    ) -> Tuple[bool, float]:
        """
        Checks if the price moved by >= desync_delta_pct within desync_window_sec.
        Returns (is_jump, delta_pct).
        """
        key = f"{platform}:{event_id}:{outcome}"
        history = self.price_history.get(key, [])
        if not history:
            return False, 0.0

        cutoff = now - self.desync_window_sec
        recent_snapshots = [p for p in history if p.timestamp >= cutoff and p.timestamp < now]
        if not recent_snapshots:
            return False, 0.0

        oldest_recent = recent_snapshots[0].price
        if oldest_recent <= 0:
            return False, 0.0

        delta_pct = abs((current_price - oldest_recent) / oldest_recent) * 100.0
        if delta_pct >= self.desync_delta_pct:
            return True, round(delta_pct, 2)
        return False, round(delta_pct, 2)

    def evaluate_desync(
        self,
        poly_event: StandardizedEvent,
        bk_event: StandardizedEvent,
        poly_orderbooks: Dict[str, Orderbook],
        matched_pair: MatchedPair,
        current_time: Optional[float] = None,
    ) -> List[ArbitrageOpportunity]:
        """
        Evaluates matched event pair on EVERY update for Static Arb and Dynamic Desync.
        """
        now = current_time or time.time()
        opportunities: List[ArbitrageOpportunity] = []

        # 1. Staleness filter
        if not self.is_fresh(poly_event.timestamp, now) or not self.is_fresh(bk_event.timestamp, now):
            return []

        # 2. Extract BK odds & implied probabilities
        if len(bk_event.outcomes) < 2:
            return []

        bk_odds1 = bk_event.outcomes[0].price
        bk_odds2 = bk_event.outcomes[1].price
        if bk_odds1 <= 1.0 or bk_odds2 <= 1.0:
            return []

        bk_prob1 = 1.0 / bk_odds1
        bk_prob2 = 1.0 / bk_odds2

        self.record_price(bk_event.platform, bk_event.event_id, bk_event.team1, bk_odds1, now)
        self.record_price(bk_event.platform, bk_event.event_id, bk_event.team2, bk_odds2, now)

        # 3. Polymarket token & orderbook lookup
        if not poly_event.clob_token_ids or len(poly_event.clob_token_ids) < 2:
            return []

        token1_id = poly_event.clob_token_ids[0]
        token2_id = poly_event.clob_token_ids[1]

        ob1 = poly_orderbooks.get(token1_id)
        ob2 = poly_orderbooks.get(token2_id)

        if not ob1 or not ob2 or not ob1.asks or not ob2.asks:
            return []

        if not self.is_fresh(ob1.timestamp, now) or not self.is_fresh(ob2.timestamp, now):
            return []

        top_poly_price1 = ob1.best_ask
        top_poly_price2 = ob2.best_ask

        if top_poly_price1 is None or top_poly_price2 is None:
            return []

        self.record_price("Polymarket", poly_event.event_id, poly_event.team1, top_poly_price1, now)
        self.record_price("Polymarket", poly_event.event_id, poly_event.team2, top_poly_price2, now)

        estimated_leg_stake = self.typical_stake_usd / 2.0
        vwap1 = calculate_buy_vwap(ob1.asks, estimated_leg_stake)
        vwap2 = calculate_buy_vwap(ob2.asks, estimated_leg_stake)

        if vwap1 is None or vwap2 is None:
            return []

        # Check recent price jump for Dynamic Desync classification
        jump_poly1, delta_p1 = self._detect_recent_price_jump("Polymarket", poly_event.event_id, poly_event.team1, top_poly_price1, now)
        jump_poly2, delta_p2 = self._detect_recent_price_jump("Polymarket", poly_event.event_id, poly_event.team2, top_poly_price2, now)
        jump_bk1, delta_b1 = self._detect_recent_price_jump(bk_event.platform, bk_event.event_id, bk_event.team1, bk_odds1, now)
        jump_bk2, delta_b2 = self._detect_recent_price_jump(bk_event.platform, bk_event.event_id, bk_event.team2, bk_odds2, now)

        is_dynamic = jump_poly1 or jump_poly2 or jump_bk1 or jump_bk2
        max_delta = max(delta_p1, delta_p2, delta_b1, delta_b2)
        signal_type = SignalType.DYNAMIC if is_dynamic else SignalType.STATIC

        # Option A: Buy Team 1 on Polymarket, Bet Team 2 on BK
        cost_poly1 = vwap1 / self.fee_factor
        cost_bk2 = bk_prob2
        sum_cost_a = cost_poly1 + cost_bk2

        if sum_cost_a < 1.0:
            profit_pct_a = ((1.0 / sum_cost_a) - 1.0) * 100.0
            if profit_pct_a >= self.min_profit_pct:
                poly_stake = self.typical_stake_usd * (cost_poly1 / sum_cost_a)
                bk_stake = self.typical_stake_usd * (cost_bk2 / sum_cost_a)

                exact_vwap1 = calculate_buy_vwap(ob1.asks, poly_stake)
                if exact_vwap1 is not None:
                    cost_poly1_exact = exact_vwap1 / self.fee_factor
                    sum_cost_exact = cost_poly1_exact + cost_bk2
                    final_profit_pct = ((1.0 / sum_cost_exact) - 1.0) * 100.0

                    if final_profit_pct >= self.min_profit_pct:
                        target_payout = self.typical_stake_usd / sum_cost_exact
                        net_profit_usd = target_payout - self.typical_stake_usd

                        # Per-leg profit verification
                        leg1_profit = (poly_stake * (1.0 / exact_vwap1) * self.fee_factor) - (poly_stake + bk_stake)
                        leg2_profit = (bk_stake * bk_odds2) - (poly_stake + bk_stake)

                        # Liquidity check
                        max_exec_usd, _ = calculate_max_executable_liquidity(ob1.asks, self.max_slippage_pct)

                        data_freshness = max(
                            now - poly_event.timestamp,
                            now - bk_event.timestamp,
                            now - ob1.timestamp
                        )

                        opportunities.append(ArbitrageOpportunity(
                            signal_id=str(uuid.uuid4()),
                            signal_type=signal_type,
                            event_title=f"{poly_event.team1} vs {poly_event.team2}",
                            game=poly_event.game,
                            tournament=poly_event.tournament,
                            team1=poly_event.team1,
                            team2=poly_event.team2,
                            start_time=poly_event.start_time,
                            bk_platform=bk_event.platform,
                            bk_event_id=bk_event.event_id,
                            bk_market_url=bk_event.market_url,
                            bk_team1_odds=bk_odds1,
                            bk_team2_odds=bk_odds2,
                            bk_implied_prob1=round(bk_prob1, 4),
                            bk_implied_prob2=round(bk_prob2, 4),
                            poly_event_id=poly_event.event_id,
                            poly_market_url=poly_event.market_url,
                            poly_team1_vwap=exact_vwap1,
                            poly_team2_vwap=vwap2,
                            poly_team1_top_price=top_poly_price1,
                            poly_team2_top_price=top_poly_price2,
                            poly_implied_prob1=round(exact_vwap1, 4),
                            poly_implied_prob2=round(vwap2, 4),
                            poly_outcome_selected=poly_event.team1,
                            poly_stake=round(poly_stake, 2),
                            bk_stake=round(bk_stake, 2),
                            total_stake=round(self.typical_stake_usd, 2),
                            sum_implied_prob=round(sum_cost_exact, 4),
                            profit_pct=round(final_profit_pct, 2),
                            net_profit_usd=round(net_profit_usd, 2),
                            leg1_profit_usd=round(leg1_profit, 2),
                            leg2_profit_usd=round(leg2_profit, 2),
                            max_executable_stake_usd=max_exec_usd,
                            slippage_pct=self.max_slippage_pct,
                            price_change_delta_pct=max_delta,
                            poly_timestamp=poly_event.timestamp,
                            bk_timestamp=bk_event.timestamp,
                            data_freshness_sec=round(data_freshness, 1),
                            detected_at=now,
                            ttl_sec=self.signal_ttl_sec if signal_type == SignalType.DYNAMIC else 120,
                            status="new"
                        ))

        # Option B: Buy Team 2 on Polymarket, Bet Team 1 on BK
        cost_poly2 = vwap2 / self.fee_factor
        cost_bk1 = bk_prob1
        sum_cost_b = cost_poly2 + cost_bk1

        if sum_cost_b < 1.0:
            profit_pct_b = ((1.0 / sum_cost_b) - 1.0) * 100.0
            if profit_pct_b >= self.min_profit_pct:
                poly_stake = self.typical_stake_usd * (cost_poly2 / sum_cost_b)
                bk_stake = self.typical_stake_usd * (cost_bk1 / sum_cost_b)

                exact_vwap2 = calculate_buy_vwap(ob2.asks, poly_stake)
                if exact_vwap2 is not None:
                    cost_poly2_exact = exact_vwap2 / self.fee_factor
                    sum_cost_exact = cost_poly2_exact + cost_bk1
                    final_profit_pct = ((1.0 / sum_cost_exact) - 1.0) * 100.0

                    if final_profit_pct >= self.min_profit_pct:
                        target_payout = self.typical_stake_usd / sum_cost_exact
                        net_profit_usd = target_payout - self.typical_stake_usd

                        leg1_profit = (bk_stake * bk_odds1) - (poly_stake + bk_stake)
                        leg2_profit = (poly_stake * (1.0 / exact_vwap2) * self.fee_factor) - (poly_stake + bk_stake)

                        max_exec_usd, _ = calculate_max_executable_liquidity(ob2.asks, self.max_slippage_pct)

                        data_freshness = max(
                            now - poly_event.timestamp,
                            now - bk_event.timestamp,
                            now - ob2.timestamp
                        )

                        opportunities.append(ArbitrageOpportunity(
                            signal_id=str(uuid.uuid4()),
                            signal_type=signal_type,
                            event_title=f"{poly_event.team1} vs {poly_event.team2}",
                            game=poly_event.game,
                            tournament=poly_event.tournament,
                            team1=poly_event.team1,
                            team2=poly_event.team2,
                            start_time=poly_event.start_time,
                            bk_platform=bk_event.platform,
                            bk_event_id=bk_event.event_id,
                            bk_market_url=bk_event.market_url,
                            bk_team1_odds=bk_odds1,
                            bk_team2_odds=bk_odds2,
                            bk_implied_prob1=round(bk_prob1, 4),
                            bk_implied_prob2=round(bk_prob2, 4),
                            poly_event_id=poly_event.event_id,
                            poly_market_url=poly_event.market_url,
                            poly_team1_vwap=vwap1,
                            poly_team2_vwap=exact_vwap2,
                            poly_team1_top_price=top_poly_price1,
                            poly_team2_top_price=top_poly_price2,
                            poly_implied_prob1=round(vwap1, 4),
                            poly_implied_prob2=round(exact_vwap2, 4),
                            poly_outcome_selected=poly_event.team2,
                            poly_stake=round(poly_stake, 2),
                            bk_stake=round(bk_stake, 2),
                            total_stake=round(self.typical_stake_usd, 2),
                            sum_implied_prob=round(sum_cost_exact, 4),
                            profit_pct=round(final_profit_pct, 2),
                            net_profit_usd=round(net_profit_usd, 2),
                            leg1_profit_usd=round(leg1_profit, 2),
                            leg2_profit_usd=round(leg2_profit, 2),
                            max_executable_stake_usd=max_exec_usd,
                            slippage_pct=self.max_slippage_pct,
                            price_change_delta_pct=max_delta,
                            poly_timestamp=poly_event.timestamp,
                            bk_timestamp=bk_event.timestamp,
                            data_freshness_sec=round(data_freshness, 1),
                            detected_at=now,
                            ttl_sec=self.signal_ttl_sec if signal_type == SignalType.DYNAMIC else 120,
                            status="new"
                        ))

        return opportunities

EOF

cat << 'EOF' > calculator/arb_calc.py
import uuid
import logging
from typing import Optional, List, Dict
from datetime import datetime

import config
from data_models import (
    StandardizedEvent,
    Orderbook,
    MatchedPair,
    ArbitrageOpportunity,
)
from calculator.vwap import calculate_buy_vwap
from calculator.liquidity import calculate_max_executable_liquidity

logger = logging.getLogger(__name__)


class ArbitrageCalculator:
    def __init__(
        self,
        typical_stake_usd: float = config.TYPICAL_STAKE_USD,
        min_profit_pct: float = config.MIN_PROFIT_THRESHOLD_PCT,
        polymarket_fee_pct: float = config.POLYMARKET_TAKER_FEE_PCT,
        stale_threshold_sec: float = config.STALE_DATA_THRESHOLD_SEC,
    ):
        self.typical_stake_usd = typical_stake_usd
        self.min_profit_pct = min_profit_pct
        self.fee_factor = 1.0 - (polymarket_fee_pct / 100.0)
        self.stale_threshold_sec = stale_threshold_sec

    def is_fresh(self, timestamp: float, current_time: Optional[float] = None) -> bool:
        now = current_time or datetime.now().timestamp()
        return (now - timestamp) <= self.stale_threshold_sec

    def calculate_opportunity(
        self,
        poly_event: StandardizedEvent,
        bk_event: StandardizedEvent,
        poly_orderbooks: Dict[str, Orderbook],
        matched_pair: MatchedPair,
        current_time: Optional[float] = None,
    ) -> List[ArbitrageOpportunity]:
        now = current_time or datetime.now().timestamp()
        
        if not self.is_fresh(poly_event.timestamp, now) or not self.is_fresh(bk_event.timestamp, now):
            return []

        if len(bk_event.outcomes) < 2:
            return []
            
        bk_odds1 = bk_event.outcomes[0].price
        bk_odds2 = bk_event.outcomes[1].price
        
        if bk_odds1 <= 1.0 or bk_odds2 <= 1.0:
            return []

        bk_prob1 = 1.0 / bk_odds1
        bk_prob2 = 1.0 / bk_odds2

        if not poly_event.clob_token_ids or len(poly_event.clob_token_ids) < 2:
            return []
            
        token1_id = poly_event.clob_token_ids[0]
        token2_id = poly_event.clob_token_ids[1]

        ob1 = poly_orderbooks.get(token1_id)
        ob2 = poly_orderbooks.get(token2_id)

        if not ob1 or not ob2 or not ob1.asks or not ob2.asks:
            return []

        if not self.is_fresh(ob1.timestamp, now) or not self.is_fresh(ob2.timestamp, now):
            return []

        top_poly_price1 = ob1.best_ask
        top_poly_price2 = ob2.best_ask

        if top_poly_price1 is None or top_poly_price2 is None:
            return []

        estimated_leg_stake = self.typical_stake_usd / 2.0

        vwap1 = calculate_buy_vwap(ob1.asks, estimated_leg_stake)
        vwap2 = calculate_buy_vwap(ob2.asks, estimated_leg_stake)

        if vwap1 is None or vwap2 is None:
            return []

        opportunities: List[ArbitrageOpportunity] = []

        # Option A: Buy Team 1 on Polymarket, Bet Team 2 on BK
        cost_poly1 = vwap1 / self.fee_factor
        cost_bk2 = bk_prob2
        sum_cost_a = cost_poly1 + cost_bk2

        if sum_cost_a < 1.0:
            profit_pct_a = ((1.0 / sum_cost_a) - 1.0) * 100.0
            if profit_pct_a >= self.min_profit_pct:
                poly_stake = self.typical_stake_usd * (cost_poly1 / sum_cost_a)
                bk_stake = self.typical_stake_usd * (cost_bk2 / sum_cost_a)
                
                exact_vwap1 = calculate_buy_vwap(ob1.asks, poly_stake)
                if exact_vwap1 is not None:
                    cost_poly1_exact = exact_vwap1 / self.fee_factor
                    sum_cost_exact = cost_poly1_exact + cost_bk2
                    final_profit_pct = ((1.0 / sum_cost_exact) - 1.0) * 100.0
                    
                    if final_profit_pct >= self.min_profit_pct:
                        target_payout = self.typical_stake_usd / sum_cost_exact
                        net_profit_usd = target_payout - self.typical_stake_usd
                        
                        leg1_profit = (poly_stake * (1.0 / exact_vwap1) * self.fee_factor) - (poly_stake + bk_stake)
                        leg2_profit = (bk_stake * bk_odds2) - (poly_stake + bk_stake)

                        max_exec_usd, _ = calculate_max_executable_liquidity(ob1.asks, config.MAX_SLIPPAGE_PCT)

                        data_freshness = max(
                            now - poly_event.timestamp,
                            now - bk_event.timestamp,
                            now - ob1.timestamp
                        )
                        
                        opportunities.append(ArbitrageOpportunity(
                            signal_id=str(uuid.uuid4()),
                            event_title=f"{poly_event.team1} vs {poly_event.team2}",
                            game=poly_event.game,
                            tournament=poly_event.tournament,
                            team1=poly_event.team1,
                            team2=poly_event.team2,
                            start_time=poly_event.start_time,
                            bk_platform=bk_event.platform,
                            bk_event_id=bk_event.event_id,
                            bk_market_url=bk_event.market_url,
                            bk_team1_odds=bk_odds1,
                            bk_team2_odds=bk_odds2,
                            bk_implied_prob1=round(bk_prob1, 4),
                            bk_implied_prob2=round(bk_prob2, 4),
                            poly_event_id=poly_event.event_id,
                            poly_market_url=poly_event.market_url,
                            poly_team1_vwap=exact_vwap1,
                            poly_team2_vwap=vwap2,
                            poly_team1_top_price=top_poly_price1,
                            poly_team2_top_price=top_poly_price2,
                            poly_implied_prob1=round(exact_vwap1, 4),
                            poly_implied_prob2=round(vwap2, 4),
                            poly_outcome_selected=poly_event.team1,
                            poly_stake=round(poly_stake, 2),
                            bk_stake=round(bk_stake, 2),
                            total_stake=round(self.typical_stake_usd, 2),
                            sum_implied_prob=round(sum_cost_exact, 4),
                            profit_pct=round(final_profit_pct, 2),
                            net_profit_usd=round(net_profit_usd, 2),
                            leg1_profit_usd=round(leg1_profit, 2),
                            leg2_profit_usd=round(leg2_profit, 2),
                            max_executable_stake_usd=max_exec_usd,
                            poly_timestamp=poly_event.timestamp,
                            bk_timestamp=bk_event.timestamp,
                            data_freshness_sec=round(data_freshness, 1),
                            status="new"
                        ))

        # Option B: Buy Team 2 on Polymarket, Bet Team 1 on BK
        cost_poly2 = vwap2 / self.fee_factor
        cost_bk1 = bk_prob1
        sum_cost_b = cost_poly2 + cost_bk1

        if sum_cost_b < 1.0:
            profit_pct_b = ((1.0 / sum_cost_b) - 1.0) * 100.0
            if profit_pct_b >= self.min_profit_pct:
                poly_stake = self.typical_stake_usd * (cost_poly2 / sum_cost_b)
                bk_stake = self.typical_stake_usd * (cost_bk1 / sum_cost_b)
                
                exact_vwap2 = calculate_buy_vwap(ob2.asks, poly_stake)
                if exact_vwap2 is not None:
                    cost_poly2_exact = exact_vwap2 / self.fee_factor
                    sum_cost_exact = cost_poly2_exact + cost_bk1
                    final_profit_pct = ((1.0 / sum_cost_exact) - 1.0) * 100.0
                    
                    if final_profit_pct >= self.min_profit_pct:
                        target_payout = self.typical_stake_usd / sum_cost_exact
                        net_profit_usd = target_payout - self.typical_stake_usd
                        
                        leg1_profit = (bk_stake * bk_odds1) - (poly_stake + bk_stake)
                        leg2_profit = (poly_stake * (1.0 / exact_vwap2) * self.fee_factor) - (poly_stake + bk_stake)

                        max_exec_usd, _ = calculate_max_executable_liquidity(ob2.asks, config.MAX_SLIPPAGE_PCT)

                        data_freshness = max(
                            now - poly_event.timestamp,
                            now - bk_event.timestamp,
                            now - ob2.timestamp
                        )
                        
                        opportunities.append(ArbitrageOpportunity(
                            signal_id=str(uuid.uuid4()),
                            event_title=f"{poly_event.team1} vs {poly_event.team2}",
                            game=poly_event.game,
                            tournament=poly_event.tournament,
                            team1=poly_event.team1,
                            team2=poly_event.team2,
                            start_time=poly_event.start_time,
                            bk_platform=bk_event.platform,
                            bk_event_id=bk_event.event_id,
                            bk_market_url=bk_event.market_url,
                            bk_team1_odds=bk_odds1,
                            bk_team2_odds=bk_odds2,
                            bk_implied_prob1=round(bk_prob1, 4),
                            bk_implied_prob2=round(bk_prob2, 4),
                            poly_event_id=poly_event.event_id,
                            poly_market_url=poly_event.market_url,
                            poly_team1_vwap=vwap1,
                            poly_team2_vwap=exact_vwap2,
                            poly_team1_top_price=top_poly_price1,
                            poly_team2_top_price=top_poly_price2,
                            poly_implied_prob1=round(vwap1, 4),
                            poly_implied_prob2=round(exact_vwap2, 4),
                            poly_outcome_selected=poly_event.team2,
                            poly_stake=round(poly_stake, 2),
                            bk_stake=round(bk_stake, 2),
                            total_stake=round(self.typical_stake_usd, 2),
                            sum_implied_prob=round(sum_cost_exact, 4),
                            profit_pct=round(final_profit_pct, 2),
                            net_profit_usd=round(net_profit_usd, 2),
                            leg1_profit_usd=round(leg1_profit, 2),
                            leg2_profit_usd=round(leg2_profit, 2),
                            max_executable_stake_usd=max_exec_usd,
                            poly_timestamp=poly_event.timestamp,
                            bk_timestamp=bk_event.timestamp,
                            data_freshness_sec=round(data_freshness, 1),
                            status="new"
                        ))

        return opportunities

EOF

cat << 'EOF' > calculator/__init__.py
from calculator.vwap import calculate_buy_vwap
from calculator.liquidity import calculate_max_executable_liquidity
from calculator.desync_engine import DesyncDetector
from calculator.arb_calc import ArbitrageCalculator

__all__ = [
    "calculate_buy_vwap",
    "calculate_max_executable_liquidity",
    "DesyncDetector",
    "ArbitrageCalculator",
]

EOF

cat << 'EOF' > parsers/base.py
from abc import ABC, abstractmethod
from typing import List
from data_models import StandardizedEvent


class BaseParser(ABC):
    @property
    @abstractmethod
    def source_name(self) -> str:
        """Name of the data source (e.g. Polymarket, Pinnacle, etc.)"""
        pass

    @abstractmethod
    async def fetch_events(self) -> List[StandardizedEvent]:
        """Fetch active prematch events in standardized format"""
        pass

EOF

cat << 'EOF' > parsers/bookmaker_base.py
from abc import ABC, abstractmethod
from typing import List, Callable, Awaitable, Optional
from data_models import StandardizedEvent


class BaseBookmakerParser(ABC):
    @property
    @abstractmethod
    def source_name(self) -> str:
        """Name of the Bookmaker or Odds Aggregator source (e.g. Pinnacle, OddsAPI, MockBK)"""
        pass

    @abstractmethod
    async def fetch_events(self) -> List[StandardizedEvent]:
        """Fetch active prematch esports events with odds in standardized format"""
        pass

    @abstractmethod
    def subscribe(self, match_id: str):
        """Subscribes to live updates for a specific match_id."""
        pass

    @abstractmethod
    def register_update_callback(self, callback: Callable[[StandardizedEvent], Awaitable[None]]):
        """Registers async callback to be called on live odds updates."""
        pass

EOF

cat << 'EOF' > parsers/polymarket.py
import aiohttp
import asyncio
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone
import time

import config
from data_models import StandardizedEvent, Outcome, Orderbook, OrderbookLevel
from parsers.base import BaseParser

logger = logging.getLogger(__name__)

GAMMA_API_URL = "https://gamma-api.polymarket.com/events"
CLOB_API_URL = "https://clob.polymarket.com/book"


class PolymarketParser(BaseParser):
    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        tracked_tournaments: Optional[Dict[str, List[str]]] = None
    ):
        self._session = session
        self.tracked_tournaments = tracked_tournaments or config.TRACKED_ESPORTS

    @property
    def source_name(self) -> str:
        return "Polymarket"

    def _match_game_and_tournament(self, title: str, description: str, tags: List[str]) -> Tuple[Optional[str], Optional[str]]:
        combined_text = f"{title} {description} {' '.join(tags)}".lower()
        
        # Determine Game
        game_found = None
        if any(term in combined_text for term in ["cs2", "counter-strike", "cs:go"]):
            game_found = "CS2"
        elif any(term in combined_text for term in ["dota", "dota 2"]):
            game_found = "Dota 2"
        elif any(term in combined_text for term in ["lol", "league of legends"]):
            game_found = "LoL"
            
        if not game_found:
            return None, None

        # Check tournament keyword filter
        allowed_tournaments = self.tracked_tournaments.get(game_found, [])
        tournament_found = None
        for tourney in allowed_tournaments:
            if tourney.lower() in combined_text:
                tournament_found = tourney
                break

        # If tournament filter specified and match is outside, ignore (focus liquidity)
        if allowed_tournaments and not tournament_found:
            return None, None

        return game_found, tournament_found or "Esports Tournament"

    def _extract_teams(self, title: str) -> Optional[Tuple[str, str]]:
        # Typical format: "Team A vs. Team B" or "Will Team A beat Team B?"
        clean_title = title.replace("Will ", "").replace(" beat ", " vs ").replace("?", "")
        if " vs " in clean_title:
            parts = clean_title.split(" vs ")
            if len(parts) >= 2:
                return parts[0].strip(), parts[1].strip()
        elif " vs. " in clean_title:
            parts = clean_title.split(" vs. ")
            if len(parts) >= 2:
                return parts[0].strip(), parts[1].strip()
        return None

    async def fetch_events(self) -> List[StandardizedEvent]:
        close_session = False
        if self._session is None:
            self._session = aiohttp.ClientSession()
            close_session = True

        events: List[StandardizedEvent] = []
        try:
            params = {
                "closed": "false",
                "limit": 100,
                "order": "volume24hr",
                "ascending": "false"
            }
            async with self._session.get(GAMMA_API_URL, params=params, timeout=10) as resp:
                if resp.status != 200:
                    logger.error(f"Polymarket Gamma API returned HTTP {resp.status}")
                    return events
                raw_events = await resp.json()

            now = time.time()
            for raw_ev in raw_events:
                title = raw_ev.get("title", "")
                description = raw_ev.get("description", "")
                tags = [t.get("label", "") for t in raw_ev.get("tags", []) if isinstance(t, dict)]
                
                game, tournament = self._match_game_and_tournament(title, description, tags)
                if not game:
                    continue

                teams = self._extract_teams(title)
                if not teams:
                    continue

                markets = raw_ev.get("markets", [])
                if not markets:
                    continue

                # Take main match winner market
                winner_market = markets[0]
                clob_token_ids = winner_market.get("clobTokenIds", [])
                outcomes_raw = winner_market.get("outcomes", "[]")
                prices_raw = winner_market.get("outcomePrices", "[]")

                if isinstance(clob_token_ids, str):
                    import json
                    try:
                        clob_token_ids = json.loads(clob_token_ids)
                    except Exception:
                        clob_token_ids = []

                if len(clob_token_ids) < 2:
                    continue

                outcomes = [
                    Outcome(name=teams[0], price=0.5),
                    Outcome(name=teams[1], price=0.5)
                ]

                start_time = None
                start_date_str = raw_ev.get("startDate") or winner_market.get("startDate")
                if start_date_str:
                    try:
                        start_time = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
                    except Exception:
                        pass

                event_id = str(raw_ev.get("id"))
                slug = raw_ev.get("slug", "")
                market_url = f"https://polymarket.com/event/{slug}" if slug else None

                events.append(StandardizedEvent(
                    event_id=f"poly_{event_id}",
                    platform=self.source_name,
                    game=game,
                    tournament=tournament,
                    team1=teams[0],
                    team2=teams[1],
                    start_time=start_time,
                    outcomes=outcomes,
                    timestamp=now,
                    market_url=market_url,
                    clob_token_ids=clob_token_ids
                ))

        except Exception as e:
            logger.error(f"Error fetching Polymarket events: {e}")
        finally:
            if close_session and self._session:
                await self._session.close()
                self._session = None

        return events

    async def fetch_orderbook(self, token_id: str) -> Optional[Orderbook]:
        close_session = False
        if self._session is None:
            self._session = aiohttp.ClientSession()
            close_session = True

        try:
            url = f"{CLOB_API_URL}?token_id={token_id}"
            async with self._session.get(url, timeout=5) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()

            bids = [
                OrderbookLevel(price=float(b["price"]), size=float(b["size"]))
                for b in data.get("bids", [])
            ]
            asks = [
                OrderbookLevel(price=float(a["price"]), size=float(a["size"]))
                for a in data.get("asks", [])
            ]

            return Orderbook(
                token_id=token_id,
                bids=sorted(bids, key=lambda x: x.price, reverse=True),
                asks=sorted(asks, key=lambda x: x.price),
                timestamp=time.time()
            )
        except Exception as e:
            logger.error(f"Error fetching orderbook for {token_id}: {e}")
            return None
        finally:
            if close_session and self._session:
                await self._session.close()
                self._session = None

EOF

cat << 'EOF' > parsers/polymarket_ws.py
import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Callable, Awaitable, Set
import aiohttp
import websockets

import config
from data_models import StandardizedEvent, Outcome, Orderbook, OrderbookLevel
from parsers.base import BaseParser

logger = logging.getLogger(__name__)


class PolymarketWSParser(BaseParser):
    def __init__(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        tracked_tournaments: Optional[Dict[str, List[str]]] = None
    ):
        self._session = session
        self.tracked_tournaments = tracked_tournaments or config.TRACKED_ESPORTS
        self.ws_url = config.POLYMARKET_CLOB_WS_URL
        self.gamma_url = config.POLYMARKET_GAMMA_API_URL
        
        # State stores
        self.active_events: Dict[str, StandardizedEvent] = {}  # event_id -> StandardizedEvent
        self.token_to_event: Dict[str, str] = {}              # token_id -> event_id
        self.orderbooks: Dict[str, Orderbook] = {}            # token_id -> Orderbook
        self.subscribed_token_ids: Set[str] = set()
        
        self._running = False
        self._update_callbacks: List[Callable[[str, Orderbook], Awaitable[None]]] = []
        self._ws_task: Optional[asyncio.Task] = None

    @property
    def source_name(self) -> str:
        return "Polymarket"

    def register_update_callback(self, callback: Callable[[str, Orderbook], Awaitable[None]]):
        """Registers async callback to be called whenever an orderbook updates."""
        self._update_callbacks.append(callback)

    def _match_game_and_tournament(self, title: str, description: str, tags: List[str]):
        combined_text = f"{title} {description} {' '.join(tags)}".lower()
        game_found = None
        if any(term in combined_text for term in ["cs2", "counter-strike", "cs:go"]):
            game_found = "CS2"
        elif any(term in combined_text for term in ["dota", "dota 2"]):
            game_found = "Dota 2"
        elif any(term in combined_text for term in ["lol", "league of legends"]):
            game_found = "LoL"

        if not game_found:
            return None, None

        allowed_tournaments = self.tracked_tournaments.get(game_found, [])
        tournament_found = None
        for tourney in allowed_tournaments:
            if tourney.lower() in combined_text:
                tournament_found = tourney
                break

        if allowed_tournaments and not tournament_found:
            return None, None

        return game_found, tournament_found or "Esports Tournament"

    def _extract_teams(self, title: str):
        clean_title = title.replace("Will ", "").replace(" beat ", " vs ").replace("?", "")
        if " vs " in clean_title:
            parts = clean_title.split(" vs ")
            if len(parts) >= 2:
                return parts[0].strip(), parts[1].strip()
        elif " vs. " in clean_title:
            parts = clean_title.split(" vs. ")
            if len(parts) >= 2:
                return parts[0].strip(), parts[1].strip()
        return None

    async def fetch_events(self) -> List[StandardizedEvent]:
        """Fetches active market list from Polymarket Gamma REST API and updates internal token mapping."""
        close_session = False
        if self._session is None:
            self._session = aiohttp.ClientSession()
            close_session = True

        events: List[StandardizedEvent] = []
        try:
            params = {
                "closed": "false",
                "limit": 100,
                "order": "volume24hr",
                "ascending": "false"
            }
            async with self._session.get(self.gamma_url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    logger.error(f"Polymarket Gamma REST returned status {resp.status}")
                    return list(self.active_events.values())
                raw_events = await resp.json()

            now = time.time()
            for raw_ev in raw_events:
                title = raw_ev.get("title", "")
                description = raw_ev.get("description", "")
                tags = [t.get("label", "") for t in raw_ev.get("tags", []) if isinstance(t, dict)]

                game, tournament = self._match_game_and_tournament(title, description, tags)
                if not game:
                    continue

                teams = self._extract_teams(title)
                if not teams:
                    continue

                markets = raw_ev.get("markets", [])
                if not markets:
                    continue

                winner_market = markets[0]
                clob_token_ids = winner_market.get("clobTokenIds", [])

                if isinstance(clob_token_ids, str):
                    try:
                        clob_token_ids = json.loads(clob_token_ids)
                    except Exception:
                        clob_token_ids = []

                if len(clob_token_ids) < 2:
                    continue

                outcomes = [
                    Outcome(name=teams[0], price=0.5),
                    Outcome(name=teams[1], price=0.5)
                ]

                event_id = f"poly_{raw_ev.get('id')}"
                slug = raw_ev.get("slug", "")
                market_url = f"https://polymarket.com/event/{slug}" if slug else None

                event = StandardizedEvent(
                    event_id=event_id,
                    platform=self.source_name,
                    game=game,
                    tournament=tournament,
                    team1=teams[0],
                    team2=teams[1],
                    outcomes=outcomes,
                    timestamp=now,
                    market_url=market_url,
                    clob_token_ids=clob_token_ids
                )

                events.append(event)
                self.active_events[event_id] = event

                # Map token IDs to event ID for WS routing
                for tid in clob_token_ids:
                    self.token_to_event[tid] = event_id
                    self.subscribed_token_ids.add(tid)

        except Exception as e:
            logger.error(f"Error fetching Polymarket Gamma REST: {e}")
        finally:
            if close_session and self._session:
                await self._session.close()
                self._session = None

        return events

    def _parse_orderbook_event(self, data: dict):
        """Parses a WS market / orderbook update payload."""
        event_type = data.get("event_type") or data.get("type")
        asset_id = data.get("asset_id") or data.get("market")
        
        if not asset_id:
            return

        bids_raw = data.get("bids", [])
        asks_raw = data.get("asks", [])
        
        bids = [
            OrderbookLevel(price=float(b.get("price", 0)), size=float(b.get("size", 0)))
            for b in bids_raw if isinstance(b, dict)
        ]
        asks = [
            OrderbookLevel(price=float(a.get("price", 0)), size=float(a.get("size", 0)))
            for a in asks_raw if isinstance(a, dict)
        ]

        # Order bids descending, asks ascending
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)

        ob = Orderbook(
            token_id=asset_id,
            bids=bids,
            asks=asks,
            timestamp=time.time()
        )

        self.orderbooks[asset_id] = ob

        # Update event outcomes mid-price if token is mapped
        if asset_id in self.token_to_event:
            event_id = self.token_to_event[asset_id]
            ev = self.active_events.get(event_id)
            if ev and ev.clob_token_ids:
                try:
                    idx = ev.clob_token_ids.index(asset_id)
                    if ob.best_ask is not None:
                        ev.outcomes[idx].price = ob.best_ask
                        ev.timestamp = time.time()
                except (ValueError, IndexError):
                    pass

        # Trigger registered callbacks
        for cb in self._update_callbacks:
            asyncio.create_task(cb(asset_id, ob))

    async def _ws_loop(self):
        """Main WebSocket loop with exponential backoff reconnects."""
        backoff_sec = 1
        max_backoff_sec = 30

        while self._running:
            try:
                logger.info(f"Connecting to Polymarket CLOB WS at {self.ws_url}...")
                async with websockets.connect(self.ws_url, ping_interval=20, ping_timeout=10) as ws:
                    logger.info("Polymarket WS connected successfully!")
                    backoff_sec = 1  # Reset backoff on successful connect

                    # Send subscription message
                    if self.subscribed_token_ids:
                        sub_msg = {
                            "type": "market",
                            "assets_ids": list(self.subscribed_token_ids)
                        }
                        await ws.send(json.dumps(sub_msg))
                        logger.info(f"Subscribed to {len(self.subscribed_token_ids)} Polymarket assets")

                    async for message in ws:
                        if not self._running:
                            break
                        try:
                            data = json.loads(message)
                            if isinstance(data, list):
                                for item in data:
                                    if isinstance(item, dict):
                                        self._parse_orderbook_event(item)
                            elif isinstance(data, dict):
                                self._parse_orderbook_event(data)
                        except Exception as parse_err:
                            logger.error(f"Error parsing Polymarket WS message: {parse_err}")

            except asyncio.CancelledError:
                logger.info("Polymarket WS task cancelled.")
                break
            except Exception as e:
                logger.warning(f"Polymarket WS connection error: {e}. Reconnecting in {backoff_sec}s...")
                await asyncio.sleep(backoff_sec)
                backoff_sec = min(backoff_sec * 2, max_backoff_sec)

    async def start(self):
        """Starts background WS listener."""
        self._running = True
        await self.fetch_events()
        self._ws_task = asyncio.create_task(self._ws_loop())

    async def stop(self):
        """Stops background WS listener."""
        self._running = False
        if self._ws_task:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass

EOF

cat << 'EOF' > parsers/mock_bookmaker.py
import asyncio
import logging
import time
from typing import List, Dict, Optional, Callable, Awaitable, Set
from datetime import datetime

import config
from data_models import StandardizedEvent, Outcome
from parsers.bookmaker_base import BaseBookmakerParser

logger = logging.getLogger(__name__)


class MockBookmakerParser(BaseBookmakerParser):
    """
    Mock Bookmaker adapter for testing static arbitrage and dynamic desync detection.
    Simulates high-frequency live odds updates and abrupt price jumps.
    """
    def __init__(self, platform_name: str = "Pinnacle"):
        self._platform_name = platform_name
        self.events: Dict[str, StandardizedEvent] = {}
        self.subscribed_matches: Set[str] = set()
        self._callbacks: List[Callable[[StandardizedEvent], Awaitable[None]]] = []
        self._running = False
        self._loop_task: Optional[asyncio.Task] = None
        self._init_sample_events()

    @property
    def source_name(self) -> str:
        return self._platform_name

    def _init_sample_events(self):
        now = time.time()
        start_time = datetime.now()

        sample1 = StandardizedEvent(
            event_id="bk_navi_faze_1",
            platform=self._platform_name,
            game="CS2",
            tournament="IEM Katowice",
            team1="Natus Vincere",
            team2="FaZe Clan",
            start_time=start_time,
            outcomes=[
                Outcome(name="Natus Vincere", price=1.90),
                Outcome(name="FaZe Clan", price=1.90)
            ],
            timestamp=now,
            market_url="https://pinnacle.com/esports/cs2/navi-vs-faze"
        )

        sample2 = StandardizedEvent(
            event_id="bk_spirit_g2_1",
            platform=self._platform_name,
            game="CS2",
            tournament="BLAST Premier",
            team1="Team Spirit",
            team2="G2 Esports",
            start_time=start_time,
            outcomes=[
                Outcome(name="Team Spirit", price=1.45),
                Outcome(name="G2 Esports", price=2.65)
            ],
            timestamp=now,
            market_url="https://pinnacle.com/esports/cs2/spirit-vs-g2"
        )

        self.events[sample1.event_id] = sample1
        self.events[sample2.event_id] = sample2

    def subscribe(self, match_id: str):
        self.subscribed_matches.add(match_id)

    def register_update_callback(self, callback: Callable[[StandardizedEvent], Awaitable[None]]):
        self._callbacks.append(callback)

    async def fetch_events(self) -> List[StandardizedEvent]:
        return list(self.events.values())

    async def trigger_price_jump(self, event_id: str, new_odds1: float, new_odds2: float):
        """
        Simulates an instant live odds movement (e.g. after a round win or kill in live match).
        Triggers update callbacks to test Dynamic Desync detection.
        """
        if event_id not in self.events:
            logger.warning(f"Event {event_id} not found in Mock BK")
            return

        ev = self.events[event_id]
        old_odds1 = ev.outcomes[0].price
        old_odds2 = ev.outcomes[1].price

        ev.outcomes[0].price = new_odds1
        ev.outcomes[1].price = new_odds2
        ev.timestamp = time.time()

        logger.info(
            f"⚡ [MOCK BK PRICE JUMP] {ev.team1} vs {ev.team2}: "
            f"({old_odds1:.2f} -> {new_odds1:.2f}, {old_odds2:.2f} -> {new_odds2:.2f})"
        )

        for cb in self._callbacks:
            await cb(ev)

    async def _update_loop(self):
        while self._running:
            await asyncio.sleep(config.BOOKMAKER_POLL_INTERVAL_SEC)
            now = time.time()
            for ev in self.events.values():
                ev.timestamp = now
                for cb in self._callbacks:
                    try:
                        await cb(ev)
                    except Exception as e:
                        logger.error(f"Error in BK update callback: {e}")

    async def start(self):
        self._running = True
        self._loop_task = asyncio.create_task(self._update_loop())

    async def stop(self):
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass

EOF

cat << 'EOF' > parsers/odds_api.py
import asyncio
import logging
import time
from typing import List, Dict, Optional, Callable, Awaitable, Set
from datetime import datetime
import aiohttp

import config
from data_models import StandardizedEvent, Outcome
from parsers.bookmaker_base import BaseBookmakerParser

logger = logging.getLogger(__name__)


class OddsApiParser(BaseBookmakerParser):
    """
    Adapter for The-Odds-API / Bookmaker aggregator.
    Performs fast polling over active esports matches.
    """
    def __init__(
        self,
        api_key: str = config.ODDS_API_KEY,
        session: Optional[aiohttp.ClientSession] = None
    ):
        self.api_key = api_key
        self._session = session
        self.base_url = config.ODDS_API_URL
        self.events: Dict[str, StandardizedEvent] = {}
        self.subscribed_matches: Set[str] = set()
        self._callbacks: List[Callable[[StandardizedEvent], Awaitable[None]]] = []
        self._running = False
        self._poll_task: Optional[asyncio.Task] = None

    @property
    def source_name(self) -> str:
        return "OddsAPI"

    def subscribe(self, match_id: str):
        self.subscribed_matches.add(match_id)

    def register_update_callback(self, callback: Callable[[StandardizedEvent], Awaitable[None]]):
        self._callbacks.append(callback)

    async def fetch_events(self) -> List[StandardizedEvent]:
        if not self.api_key:
            logger.debug("OddsAPI key not set, skipping API call.")
            return list(self.events.values())

        close_session = False
        if self._session is None:
            self._session = aiohttp.ClientSession()
            close_session = True

        result: List[StandardizedEvent] = []
        try:
            url = f"{self.base_url}/csgo_events/odds"
            params = {
                "apiKey": self.api_key,
                "regions": "eu",
                "markets": "h2h",
                "oddsFormat": "decimal"
            }
            async with self._session.get(url, params=params, timeout=10) as resp:
                if resp.status != 200:
                    logger.warning(f"OddsAPI returned status {resp.status}")
                    return result

                data = await resp.json()
                now = time.time()

                for item in data:
                    match_id = item.get("id")
                    team1 = item.get("home_team", "")
                    team2 = item.get("away_team", "")
                    sport_key = item.get("sport_title", "CS2")
                    commence_time_str = item.get("commence_time")

                    start_time = None
                    if commence_time_str:
                        try:
                            start_time = datetime.fromisoformat(commence_time_str.replace("Z", "+00:00"))
                        except Exception:
                            pass

                    bookmakers = item.get("bookmakers", [])
                    if not bookmakers:
                        continue

                    # Grab Pinnacle or first bookmaker
                    bm = next((b for b in bookmakers if b.get("key") == "pinnacle"), bookmakers[0])
                    bm_title = bm.get("title", self.source_name)

                    h2h_market = next((m for m in bm.get("markets", []) if m.get("key") == "h2h"), None)
                    if not h2h_market or len(h2h_market.get("outcomes", [])) < 2:
                        continue

                    outs = h2h_market["outcomes"]
                    odds1 = float(outs[0].get("price", 1.0))
                    odds2 = float(outs[1].get("price", 1.0))

                    ev = StandardizedEvent(
                        event_id=f"oddsapi_{match_id}",
                        platform=bm_title,
                        game=sport_key,
                        tournament="Esports Match",
                        team1=team1,
                        team2=team2,
                        start_time=start_time,
                        outcomes=[
                            Outcome(name=team1, price=odds1),
                            Outcome(name=team2, price=odds2)
                        ],
                        timestamp=now
                    )
                    self.events[ev.event_id] = ev
                    result.append(ev)

        except Exception as e:
            logger.error(f"Error fetching OddsAPI events: {e}")
        finally:
            if close_session and self._session:
                await self._session.close()
                self._session = None

        return result

    async def _polling_loop(self):
        while self._running:
            try:
                events = await self.fetch_events()
                for ev in events:
                    for cb in self._callbacks:
                        await cb(ev)
            except Exception as e:
                logger.error(f"Error in OddsAPI polling loop: {e}")
            await asyncio.sleep(config.BOOKMAKER_POLL_INTERVAL_SEC)

    async def start(self):
        self._running = True
        self._poll_task = asyncio.create_task(self._polling_loop())

    async def stop(self):
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

EOF

cat << 'EOF' > parsers/__init__.py
from parsers.base import BaseParser
from parsers.bookmaker_base import BaseBookmakerParser
from parsers.polymarket import PolymarketParser
from parsers.polymarket_ws import PolymarketWSParser
from parsers.mock_bookmaker import MockBookmakerParser
from parsers.odds_api import OddsApiParser

__all__ = [
    "BaseParser",
    "BaseBookmakerParser",
    "PolymarketParser",
    "PolymarketWSParser",
    "MockBookmakerParser",
    "OddsApiParser"
]

EOF

cat << 'EOF' > database/storage.py
import aiosqlite
import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from data_models import MatchedPair, ArbitrageOpportunity, SourceHealth, ExecutedTrade, SignalType

logger = logging.getLogger(__name__)


class DatabaseStorage:
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS matched_events (
                    bk_event_id TEXT PRIMARY KEY,
                    polymarket_event_id TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    match_type TEXT NOT NULL,
                    rules_compatible INTEGER NOT NULL,
                    rules_note TEXT,
                    updated_at REAL NOT NULL
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS arb_signals (
                    signal_id TEXT PRIMARY KEY,
                    signal_type TEXT NOT NULL,
                    event_title TEXT NOT NULL,
                    game TEXT NOT NULL,
                    tournament TEXT NOT NULL,
                    team1 TEXT NOT NULL,
                    team2 TEXT NOT NULL,
                    start_time TEXT,
                    bk_platform TEXT NOT NULL,
                    bk_event_id TEXT NOT NULL,
                    bk_market_url TEXT,
                    bk_team1_odds REAL NOT NULL,
                    bk_team2_odds REAL NOT NULL,
                    bk_implied_prob1 REAL NOT NULL,
                    bk_implied_prob2 REAL NOT NULL,
                    poly_event_id TEXT NOT NULL,
                    poly_market_url TEXT,
                    poly_team1_vwap REAL NOT NULL,
                    poly_team2_vwap REAL NOT NULL,
                    poly_implied_prob1 REAL NOT NULL,
                    poly_implied_prob2 REAL NOT NULL,
                    poly_outcome_selected TEXT NOT NULL,
                    poly_stake REAL NOT NULL,
                    bk_stake REAL NOT NULL,
                    total_stake REAL NOT NULL,
                    sum_implied_prob REAL NOT NULL,
                    profit_pct REAL NOT NULL,
                    net_profit_usd REAL NOT NULL,
                    leg1_profit_usd REAL NOT NULL,
                    leg2_profit_usd REAL NOT NULL,
                    max_executable_stake_usd REAL NOT NULL,
                    price_change_delta_pct REAL NOT NULL,
                    data_freshness_sec REAL NOT NULL,
                    status TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS executed_trades (
                    trade_id TEXT PRIMARY KEY,
                    signal_id TEXT NOT NULL,
                    user_action TEXT NOT NULL,
                    actual_winner TEXT,
                    actual_profit_usd REAL,
                    timestamp REAL NOT NULL,
                    FOREIGN KEY(signal_id) REFERENCES arb_signals(signal_id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS source_health (
                    source_name TEXT PRIMARY KEY,
                    last_updated REAL NOT NULL,
                    is_healthy INTEGER NOT NULL,
                    message TEXT
                )
            """)
            await db.commit()

    async def save_matched_pair(self, pair: MatchedPair):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO matched_events 
                (bk_event_id, polymarket_event_id, confidence, match_type, rules_compatible, rules_note, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(bk_event_id) DO UPDATE SET
                    polymarket_event_id=excluded.polymarket_event_id,
                    confidence=excluded.confidence,
                    match_type=excluded.match_type,
                    rules_compatible=excluded.rules_compatible,
                    rules_note=excluded.rules_note,
                    updated_at=excluded.updated_at
            """, (
                pair.bk_event_id,
                pair.polymarket_event_id,
                pair.confidence,
                pair.match_type,
                1 if pair.rules_compatible else 0,
                pair.rules_note,
                pair.updated_at
            ))
            await db.commit()

    async def get_valid_matched_pairs(self, min_confidence: float = 0.8) -> List[MatchedPair]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("""
                SELECT bk_event_id, polymarket_event_id, confidence, match_type, rules_compatible, rules_note, updated_at
                FROM matched_events
                WHERE confidence >= ? AND rules_compatible = 1
            """, (min_confidence,)) as cursor:
                rows = await cursor.fetchall()
                return [
                    MatchedPair(
                        bk_event_id=r[0],
                        polymarket_event_id=r[1],
                        confidence=r[2],
                        match_type=r[3],
                        rules_compatible=bool(r[4]),
                        rules_note=r[5] or "",
                        updated_at=r[6]
                    )
                    for r in rows
                ]

    async def save_arb_signal(self, arb: ArbitrageOpportunity):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO arb_signals (
                    signal_id, signal_type, event_title, game, tournament, team1, team2, start_time,
                    bk_platform, bk_event_id, bk_market_url, bk_team1_odds, bk_team2_odds,
                    bk_implied_prob1, bk_implied_prob2,
                    poly_event_id, poly_market_url, poly_team1_vwap, poly_team2_vwap,
                    poly_implied_prob1, poly_implied_prob2,
                    poly_outcome_selected, poly_stake, bk_stake, total_stake, sum_implied_prob,
                    profit_pct, net_profit_usd, leg1_profit_usd, leg2_profit_usd,
                    max_executable_stake_usd, price_change_delta_pct, data_freshness_sec, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                arb.signal_id,
                arb.signal_type.value,
                arb.event_title,
                arb.game,
                arb.tournament,
                arb.team1,
                arb.team2,
                arb.start_time.isoformat() if arb.start_time else None,
                arb.bk_platform,
                arb.bk_event_id,
                arb.bk_market_url,
                arb.bk_team1_odds,
                arb.bk_team2_odds,
                arb.bk_implied_prob1,
                arb.bk_implied_prob2,
                arb.poly_event_id,
                arb.poly_market_url,
                arb.poly_team1_vwap,
                arb.poly_team2_vwap,
                arb.poly_implied_prob1,
                arb.poly_implied_prob2,
                arb.poly_outcome_selected,
                arb.poly_stake,
                arb.bk_stake,
                arb.total_stake,
                arb.sum_implied_prob,
                arb.profit_pct,
                arb.net_profit_usd,
                arb.leg1_profit_usd,
                arb.leg2_profit_usd,
                arb.max_executable_stake_usd,
                arb.price_change_delta_pct,
                arb.data_freshness_sec,
                arb.status,
                arb.detected_at
            ))
            await db.commit()

    async def update_signal_status(self, signal_id: str, status: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE arb_signals SET status = ? WHERE signal_id = ?
            """, (status, signal_id))
            
            import uuid
            # Log executed trade decision
            await db.execute("""
                INSERT OR REPLACE INTO executed_trades (trade_id, signal_id, user_action, timestamp)
                VALUES (?, ?, ?, ?)
            """, (str(uuid.uuid4()), signal_id, status, datetime.now().timestamp()))
            
            await db.commit()

    async def get_analytics_summary(self) -> Dict[str, Any]:
        """Calculates basic performance analytics from historical signal logs."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*), AVG(profit_pct) FROM arb_signals") as c1:
                total_signals, avg_profit = await c1.fetchone()

            async with db.execute("SELECT COUNT(*) FROM arb_signals WHERE status = 'accepted'") as c2:
                accepted_count = (await c2.fetchone())[0]

            async with db.execute("SELECT COUNT(*) FROM arb_signals WHERE status = 'skipped'") as c3:
                skipped_count = (await c3.fetchone())[0]

            async with db.execute("SELECT COUNT(*) FROM arb_signals WHERE signal_type = 'Dynamic'") as c4:
                dynamic_count = (await c4.fetchone())[0]

            return {
                "total_signals": total_signals or 0,
                "avg_profit_pct": round(avg_profit or 0.0, 2),
                "accepted_count": accepted_count or 0,
                "skipped_count": skipped_count or 0,
                "dynamic_count": dynamic_count or 0,
                "acceptance_rate": round((accepted_count / total_signals * 100.0) if total_signals else 0.0, 1)
            }

    async def update_source_health(self, health: SourceHealth):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO source_health (source_name, last_updated, is_healthy, message)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_name) DO UPDATE SET
                    last_updated=excluded.last_updated,
                    is_healthy=excluded.is_healthy,
                    message=excluded.message
            """, (
                health.source_name,
                health.last_updated,
                1 if health.is_healthy else 0,
                health.message
            ))
            await db.commit()

EOF

cat << 'EOF' > bot/telegram_bot.py
import asyncio
import logging
import time
from typing import Optional
from datetime import datetime

from aiogram import Bot, Dispatcher, types, Router, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

import config
from data_models import ArbitrageOpportunity, SignalType
from database.storage import DatabaseStorage

logger = logging.getLogger(__name__)

router = Router()
db_storage: Optional[DatabaseStorage] = None


def format_signal_message(signal: ArbitrageOpportunity) -> str:
    """Formats an ArbitrageOpportunity into a rich Markdown notification."""
    now = time.time()
    signal_age = max(0, int(now - signal.detected_at))

    if signal.signal_type == SignalType.DYNAMIC:
        header = f"⚡ **[DYNAMIC DESYNC DETECTED]** ⚡\n"
        if signal.price_change_delta_pct > 0:
            header += f"🔥 *Резкий скачок цены:* `+{signal.price_change_delta_pct}%`\n"
        header += f"⏰ *Дедлайн актуальности:* `{signal.ttl_sec} сек` (прошло {signal_age}s)\n"
    else:
        header = f"📊 **[STATIC ARBITRAGE SIGNAL]**\n"

    time_str = signal.start_time.strftime("%d.%m %H:%M") if signal.start_time else "Скоро"
    
    # Selected leg description
    poly_leg_team = signal.poly_outcome_selected
    bk_leg_team = signal.team2 if poly_leg_team == signal.team1 else signal.team1
    bk_leg_odds = signal.bk_team2_odds if poly_leg_team == signal.team1 else signal.bk_team1_odds

    poly_url = f"[Polymarket]({signal.poly_market_url})" if signal.poly_market_url else "Polymarket"
    bk_url = f"[{signal.bk_platform}]({signal.bk_market_url})" if signal.bk_market_url else signal.bk_platform

    msg = (
        f"{header}\n"
        f"🎮 *Дисциплина:* {signal.game} | *Турнир:* {signal.tournament}\n"
        f"⚔️ *Матч:* `{signal.event_title}` ({time_str})\n\n"

        f"🟢 *Плечо 1 ({poly_url}):*\n"
        f"   • Исход: BUY `{poly_leg_team}`\n"
        f"   • Цена VWAP: `{signal.poly_team1_vwap if poly_leg_team == signal.team1 else signal.poly_team2_vwap:.3f}` (P_{{implied}} = `{signal.poly_implied_prob1 if poly_leg_team == signal.team1 else signal.poly_implied_prob2:.1%}`)\n"
        f"   • Рекомендуемый взнос: `${signal.poly_stake:.2f}`\n\n"

        f"🔵 *Плечо 2 ({bk_url}):*\n"
        f"   • Исход: BET `{bk_leg_team}`\n"
        f"   • Коэффициент: `{bk_leg_odds:.2f}` (P_{{implied}} = `{1.0/bk_leg_odds:.1%}`)\n"
        f"   • Рекомендуемый взнос: `${signal.bk_stake:.2f}`\n\n"

        f"💰 *ФИНАНСОВЫЙ ИТОГ:*\n"
        f"   • Общий банк: `${signal.total_stake:.2f}`\n"
        f"   • Сумма вероятностей Σq: `{signal.sum_implied_prob:.4f}`\n"
        f"   • Гарантированный ROI: `+{signal.profit_pct:.2f}%` (+${signal.net_profit_usd:.2f})\n"
        f"   • Профит при победе {signal.team1}: `${signal.leg1_profit_usd:.2f}`\n"
        f"   • Профит при победе {signal.team2}: `${signal.leg2_profit_usd:.2f}`\n\n"

        f"💧 *ЛИКВИДНОСТЬ И ИСПОЛНЕНИЕ:*\n"
        f"   • Макс. исполняемый объем (проскальзывание <{signal.slippage_pct}%): `${signal.max_executable_stake_usd:.2f}`\n"
        f"   • Свежесть данных: `{signal.data_freshness_sec:.1f}s`"
    )

    return msg


def get_signal_keyboard(signal_id: str) -> InlineKeyboardMarkup:
    """Builds inline keyboard with Accepted / Skipped buttons."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принял", callback_data=f"accept:{signal_id}"),
            InlineKeyboardButton(text="❌ Пропустил", callback_data=f"skip:{signal_id}")
        ]
    ])
    return keyboard


@router.message(Command("start", "help"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 **Система детекции рассинхрона вероятностей (БК ↔ Polymarket)**\n\n"
        "Команды бота:\n"
        "/stats — Аналитика по сигналам\n"
        "/health — Состояние источников данных\n"
        "/status — Текущие настройки",
        parse_mode=ParseMode.MARKDOWN
    )


@router.message(Command("stats"))
async def cmd_stats(message: types.Message):
    if not db_storage:
        await message.answer("Ошибка: База данных не подключена")
        return
    stats = await db_storage.get_analytics_summary()
    await message.answer(
        f"📊 *АНАЛИТИКА СИГНАЛОВ*\n\n"
        f"• Всего обнаружено сигналов: `{stats['total_signals']}`\n"
        f"• Динамических desync: `{stats['dynamic_count']}`\n"
        f"• Средний ROI: `+{stats['avg_profit_pct']}%`\n"
        f"• Принято сделок: `{stats['accepted_count']}`\n"
        f"• Пропущено: `{stats['skipped_count']}`\n"
        f"• Исполнение (% accepted): `{stats['acceptance_rate']}%`",
        parse_mode=ParseMode.MARKDOWN
    )


@router.callback_query(F.data.startswith("accept:") | F.data.startswith("skip:"))
async def handle_signal_callback(query: types.CallbackQuery):
    if not query.data:
        return

    action, signal_id = query.data.split(":", 1)
    status_text = "accepted" if action == "accept" else "skipped"
    status_display = "✅ **СДЕЛКА ПРИНЯТА В УЧЕТ**" if action == "accept" else "❌ **СДЕЛКА ПРОПУЩЕНА**"

    if db_storage:
        await db_storage.update_signal_status(signal_id, status_text)

    await query.answer(f"Статус обновлен: {status_text}")
    if query.message and isinstance(query.message, types.Message):
        updated_text = query.message.text + f"\n\nСтатус: {status_display}"
        await query.message.edit_text(updated_text, reply_markup=None)


class TelegramNotifier:
    def __init__(self, token: str = config.TELEGRAM_BOT_TOKEN, chat_id: str = config.TELEGRAM_CHAT_ID):
        self.token = token
        self.chat_id = chat_id
        self.bot: Optional[Bot] = Bot(token=self.token) if self.token else None
        self.dp: Optional[Dispatcher] = Dispatcher() if self.bot else None

    async def start_bot(self, storage: DatabaseStorage):
        global db_storage
        db_storage = storage

        if not self.bot or not self.dp:
            logger.warning("Telegram Bot token not set. Bot will not send alerts.")
            return

        self.dp.include_router(router)
        logger.info("Starting Telegram Bot polling router...")
        asyncio.create_task(self.dp.start_polling(self.bot))

    async def send_alert(self, signal: ArbitrageOpportunity):
        """Sends alert message to Telegram channel/chat."""
        if not self.bot or not self.chat_id:
            logger.info(f"[ALERT CONSOLE ONLY] {signal.signal_type.value} Arb: {signal.event_title} | ROI: +{signal.profit_pct}%")
            return

        text = format_signal_message(signal)
        keyboard = get_signal_keyboard(signal.signal_id or "")

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            logger.info(f"Telegram alert sent for signal {signal.signal_id}")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

EOF

cat << 'EOF' > bot/__init__.py
from bot.telegram_bot import TelegramNotifier, format_signal_message

__all__ = ["TelegramNotifier", "format_signal_message"]

EOF

echo '📦 Creating Virtual Environment & installing dependencies...'
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools
pip install -r requirements.txt

echo '⚙️ Starting Bot 24/7 background process...'
pkill -f main.py || true
nohup venv/bin/python main.py > bot.log 2>&1 &

sleep 2
if ps aux | grep -v grep | grep main.py > /dev/null; then
    echo '🟢 [SUCCESS] Bot successfully started and running 24/7!'
    echo '📋 View live logs with: tail -f ~/polymarket-arb/bot.log'
else
    echo '❌ [ERROR] Bot failed to start. Check bot.log:'
    cat bot.log
fi