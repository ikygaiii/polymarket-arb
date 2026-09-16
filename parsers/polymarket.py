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
