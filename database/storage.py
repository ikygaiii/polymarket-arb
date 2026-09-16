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
