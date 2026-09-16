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
