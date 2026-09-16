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

