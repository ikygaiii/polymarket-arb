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

