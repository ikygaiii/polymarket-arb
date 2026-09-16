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

