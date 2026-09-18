import asyncio
import json
import logging
import re
import time
from typing import Dict, List, Optional, Callable, Awaitable, Set
import aiohttp
import websockets

import socket
import config
from data_models import StandardizedEvent, Outcome, Orderbook, OrderbookLevel
from parsers.base import BaseParser
from matcher.normalization import normalize_string

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

    def _extract_teams_and_tournament(self, title: str):
        """
        Extracts clean team names and optional tournament from Polymarket event title.
        Handles titles like:
          'Counter-Strike: MOUZ vs Natus Vincere (BO3) - StarLadder StarSeries Playoffs'
          'LoL: Team WE vs JD Gaming (BO5) - LPL Regional Finals Playoffs'
          'Will Navi beat FaZe?'
        """
        clean = title.replace("Will ", "").replace(" beat ", " vs ").replace("?", "").strip()
        extracted_tourney = None

        if " - " in clean:
            parts = clean.split(" - ", 1)
            clean = parts[0].strip()
            extracted_tourney = parts[1].strip()

        # Strip generic prefix before colon if remainder contains 'vs'
        if ":" in clean:
            prefix, remainder = clean.split(":", 1)
            if re.search(r'\bvs\.?\b', remainder, flags=re.IGNORECASE):
                if not extracted_tourney:
                    extracted_tourney = prefix.strip()
                clean = remainder.strip()

        # Strip sport/game prefixes: "Counter-Strike: ", "CS2: ", "LoL: ", "Dota 2: ", etc.
        clean = re.sub(
            r'^(counter-strike|cs2|cs:go|dota\s*2?|lol|league of legends|valorant|esports):\s*',
            '',
            clean,
            flags=re.IGNORECASE
        ).strip()

        parts = re.split(r'\s+vs\.?\s+', clean, flags=re.IGNORECASE)
        if len(parts) >= 2:
            t1 = re.sub(r'\(.*?\)', '', parts[0]).strip()
            t2 = re.sub(r'\(.*?\)', '', parts[1]).strip()

            if " - " in t2:
                sub = t2.split(" - ", 1)
                t2 = sub[0].strip()
                if not extracted_tourney:
                    extracted_tourney = sub[1].strip()

            return t1.strip(), t2.strip(), extracted_tourney
        return None, None, extracted_tourney

    def _extract_teams(self, title: str):
        t1, t2, _ = self._extract_teams_and_tournament(title)
        if t1 and t2:
            return t1, t2
        return None

    def _extract_market_outcomes(self, raw_ev: dict, t1: str, t2: str):
        """
        Robustly extracts match winner outcomes and corresponding clob_token_ids
        for both 3-way (Soccer) and 2-way (Esports/MMA/Tennis) events.
        Guarantees outcomes and clob_token_ids are matched 1:1 by team name.
        """
        title = raw_ev.get("title", "")
        slug = raw_ev.get("slug", "")
        if "-more-markets" in slug or "more markets" in title.lower() or "props" in title.lower():
            return None

        norm1 = normalize_string(t1)
        norm2 = normalize_string(t2)
        markets = raw_ev.get("markets", [])
        if not markets:
            return None

        def parse_json_field(val):
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except Exception:
                    return []
            return val if isinstance(val, list) else []

        # 1. Check for 3-way Soccer style binary submarkets:
        # Question 1: "Will Team 1 win?"
        # Question 2: "Will Team 2 win?"
        # Question 3: "Will it end in a draw?"
        m_t1, m_t2, m_draw = None, None, None
        for m in markets:
            q = m.get("question", "").lower()
            q_norm = normalize_string(q)
            if "draw" in q or "tie" in q:
                m_draw = m
            elif norm1 in q_norm and "win" in q and norm2 not in q_norm:
                m_t1 = m
            elif norm2 in q_norm and "win" in q and norm1 not in q_norm:
                m_t2 = m

        if m_t1 and m_t2:
            p1_prices = parse_json_field(m_t1.get("outcomePrices"))
            p2_prices = parse_json_field(m_t2.get("outcomePrices"))
            toks1 = parse_json_field(m_t1.get("clobTokenIds"))
            toks2 = parse_json_field(m_t2.get("clobTokenIds"))

            if p1_prices and p2_prices and toks1 and toks2:
                try:
                    p1 = float(p1_prices[0])
                    p2 = float(p2_prices[0])
                    outcomes = [
                        Outcome(name=t1, price=p1 if p1 > 0 else 0.5),
                        Outcome(name=t2, price=p2 if p2 > 0 else 0.5)
                    ]
                    clob_tokens = [toks1[0], toks2[0]]

                    if m_draw:
                        p_draw = parse_json_field(m_draw.get("outcomePrices"))
                        toks_draw = parse_json_field(m_draw.get("clobTokenIds"))
                        if p_draw and toks_draw:
                            outcomes.append(Outcome(name="Draw", price=float(p_draw[0])))
                            clob_tokens.append(toks_draw[0])

                    return outcomes, clob_tokens
                except Exception:
                    pass

        # 2. 2-way Head-to-Head / Esports Match Winner
        sub_market_noise = [
            "map 1", "map 2", "map 3", "map 4", "game 1", "game 2", "game 3", "game 4", "game 5",
            "set 1", "set 2", "set 3", "handicap", "spread", "total", "o/u", "over/under", "round",
            "half", "dragon", "baron", "inhibitor", "kill", "first blood", "completed match"
        ]

        candidate_markets = []
        for m in markets:
            q = m.get("question", "").lower()
            if any(noise in q for noise in sub_market_noise):
                continue
            candidate_markets.append(m)

        if not candidate_markets:
            candidate_markets = markets

        # Prefer market whose question explicitly contains "(BO" or title
        best_m = candidate_markets[0]
        for m in candidate_markets:
            q = m.get("question", "").lower()
            if "(bo" in q or "playoffs" in q or "finals" in q or title.lower() in q:
                best_m = m
                break

        raw_outs = parse_json_field(best_m.get("outcomes"))
        raw_prices = parse_json_field(best_m.get("outcomePrices"))
        raw_tokens = parse_json_field(best_m.get("clobTokenIds"))

        if len(raw_outs) >= 2 and len(raw_prices) >= 2 and len(raw_tokens) >= 2:
            o0 = normalize_string(raw_outs[0])
            o1 = normalize_string(raw_outs[1])
            try:
                pr0 = float(raw_prices[0])
                pr1 = float(raw_prices[1])
            except Exception:
                pr0, pr1 = 0.5, 0.5

            tok0 = raw_tokens[0]
            tok1 = raw_tokens[1]

            # If out[0] is team2 and out[1] is team1, align them to (t1, t2)
            if (o0 == norm2 or norm2 in o0) and (o1 == norm1 or norm1 in o1):
                p1, tok1_id = pr1, tok1
                p2, tok2_id = pr0, tok0
            else:
                p1, tok1_id = pr0, tok0
                p2, tok2_id = pr1, tok1

            outcomes = [
                Outcome(name=t1, price=p1 if p1 > 0 else 0.5),
                Outcome(name=t2, price=p2 if p2 > 0 else 0.5)
            ]
            clob_tokens = [tok1_id, tok2_id]
            return outcomes, clob_tokens

        return None

    def _match_game_and_tournament(self, title: str, description: str, tags: List[str], extracted_tourney: Optional[str] = None):
        combined_text = f"{title} {description} {' '.join(tags)}".lower()
        game_found = None
        if any(term in combined_text for term in ["cs2", "counter-strike", "cs:go"]):
            game_found = "CS2"
        elif any(term in combined_text for term in ["dota", "dota 2"]):
            game_found = "Dota 2"
        elif any(term in combined_text for term in ["lol", "league of legends"]):
            game_found = "LoL"
        elif any(term in combined_text for term in ["soccer", "football", "premier league", "epl", "la liga", "bundesliga", "champions league", "serie a", "ligue 1", "chelsea", "arsenal", "brentford", "bayern", "sevilla", "barcelona", "fc "]):
            game_found = "Soccer"
        elif any(term in combined_text for term in ["mma", "ufc", "bellator"]):
            game_found = "MMA"

        if not game_found:
            return None, None

        allowed_tournaments = self.tracked_tournaments.get(game_found, [])
        tournament_found = None
        for tourney in allowed_tournaments:
            if tourney.lower() in combined_text:
                tournament_found = tourney
                break

        track_all = getattr(config, "TRACK_ALL_TOURNAMENTS", True)
        if not track_all and allowed_tournaments and not tournament_found:
            return None, None

        final_tourney = tournament_found or extracted_tourney or "Esports Tournament"
        return game_found, final_tourney

    async def fetch_events(self) -> List[StandardizedEvent]:
        """Fetches active market list from Polymarket Gamma REST API and updates internal token mapping."""
        close_session = False
        if self._session is None:
            conn = aiohttp.TCPConnector(family=socket.AF_INET)
            self._session = aiohttp.ClientSession(connector=conn)
            close_session = True

        events: List[StandardizedEvent] = []
        try:
            params = {
                "closed": "false",
                "limit": 100,
                "order": "volume24hr",
                "ascending": "false"
            }
            async with self._session.get(self.gamma_url, params=params, timeout=15) as resp:
                if resp.status != 200:
                    logger.error(f"Polymarket Gamma REST returned status {resp.status}")
                    return list(self.active_events.values())
                raw_events = await resp.json()

            now = time.time()
            for raw_ev in raw_events:
                title = raw_ev.get("title", "")
                description = raw_ev.get("description", "")
                tags = [t.get("label", "") for t in raw_ev.get("tags", []) if isinstance(t, dict)]

                t1, t2, extracted_tourney = self._extract_teams_and_tournament(title)
                if not t1 or not t2:
                    continue

                game, tournament = self._match_game_and_tournament(title, description, tags, extracted_tourney)
                if not game:
                    continue

                parsed = self._extract_market_outcomes(raw_ev, t1, t2)
                if not parsed:
                    continue

                outcomes, clob_token_ids = parsed
                event_id = f"poly_{raw_ev.get('id')}"
                slug = raw_ev.get("slug", "")
                market_url = f"https://polymarket.com/event/{slug}" if slug else None

                event = StandardizedEvent(
                    event_id=event_id,
                    platform=self.source_name,
                    game=game,
                    tournament=tournament,
                    team1=t1,
                    team2=t2,
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

                # Seed initial orderbook with reasonable liquidity from Gamma API
                for out, tid in zip(outcomes, clob_token_ids):
                    if tid not in self.orderbooks and out.price > 0:
                        self.orderbooks[tid] = Orderbook(
                            token_id=tid,
                            bids=[OrderbookLevel(price=max(0.01, round(out.price - 0.01, 3)), size=10000.0)],
                            asks=[OrderbookLevel(price=min(0.99, round(out.price, 3)), size=10000.0)],
                            timestamp=now
                        )

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

