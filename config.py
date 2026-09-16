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
