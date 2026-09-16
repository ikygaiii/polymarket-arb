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
