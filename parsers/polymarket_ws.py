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
