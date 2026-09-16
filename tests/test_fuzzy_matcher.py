from datetime import datetime, timedelta
from data_models import StandardizedEvent, Outcome
from matcher.fuzzy_matcher import EventMatcher
from matcher.normalization import normalize_string, transliterate


def test_normalization_and_transliteration():
    assert transliterate("Нави") == "navi"
    assert normalize_string("Natus Vincere Esports") == "navi"
    assert normalize_string("FaZe Clan Gaming") == "faze"
    assert normalize_string("Virtus.Pro") == "vp"


def test_fuzzy_matcher_team_matching():
    now = datetime.now()

    poly_events = [
        StandardizedEvent(
            event_id="poly_100",
            platform="Polymarket",
            game="CS2",
            tournament="IEM Katowice",
            team1="Navi",
            team2="FaZe",
            start_time=now,
            outcomes=[Outcome(name="Navi", price=0.5), Outcome(name="FaZe", price=0.5)]
        )
    ]

    bk_events = [
        StandardizedEvent(
            event_id="bk_200",
            platform="Pinnacle",
            game="CS2",
            tournament="IEM Katowice 2026",
            team1="Natus Vincere",
            team2="FaZe Clan",
            start_time=now + timedelta(minutes=10),
            outcomes=[Outcome(name="Natus Vincere", price=1.9), Outcome(name="FaZe Clan", price=1.9)]
        )
    ]

    matcher = EventMatcher(similarity_threshold=70.0)
    matches = matcher.match_events(bk_events, poly_events)

    assert len(matches) == 1
    match = matches[0]
    assert match.bk_event_id == "bk_200"
    assert match.polymarket_event_id == "poly_100"
    assert match.confidence >= 0.8
