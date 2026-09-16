import time
from data_models import (
    StandardizedEvent,
    Outcome,
    Orderbook,
    OrderbookLevel,
    MatchedPair,
    SignalType,
)
from calculator.desync_engine import DesyncDetector


def test_desync_detector_static_and_dynamic():
    now = time.time()

    poly_event = StandardizedEvent(
        event_id="poly_1",
        platform="Polymarket",
        game="CS2",
        tournament="IEM Katowice",
        team1="Navi",
        team2="FaZe",
        outcomes=[Outcome(name="Navi", price=0.35), Outcome(name="FaZe", price=0.65)],
        timestamp=now - 2,
        clob_token_ids=["tok_1", "tok_2"]
    )

    bk_event = StandardizedEvent(
        event_id="bk_1",
        platform="Pinnacle",
        game="CS2",
        tournament="IEM Katowice",
        team1="Navi",
        team2="FaZe",
        outcomes=[Outcome(name="Navi", price=2.50), Outcome(name="FaZe", price=1.80)],
        timestamp=now - 2,
    )

    poly_orderbooks = {
        "tok_1": Orderbook(
            token_id="tok_1",
            asks=[OrderbookLevel(price=0.35, size=2000)],
            timestamp=now - 1
        ),
        "tok_2": Orderbook(
            token_id="tok_2",
            asks=[OrderbookLevel(price=0.65, size=2000)],
            timestamp=now - 1
        )
    }

    matched_pair = MatchedPair(
        bk_event_id="bk_1",
        polymarket_event_id="poly_1",
        confidence=0.95,
        match_type="exact",
        rules_compatible=True
    )

    detector = DesyncDetector(min_profit_pct=1.0)

    # 1. Static evaluation
    opps = detector.evaluate_desync(poly_event, bk_event, poly_orderbooks, matched_pair, current_time=now)
    assert len(opps) > 0
    opp = opps[0]
    assert opp.signal_type == SignalType.STATIC
    assert opp.profit_pct > 1.0
    assert opp.leg1_profit_usd > 0
    assert opp.leg2_profit_usd > 0

    # 2. Simulate rapid live odds jump on BK (e.g. FaZe odds jump from 1.80 to 2.20 in 1 second)
    now_jump = now + 1.0
    bk_event.outcomes[1].price = 2.20
    bk_event.timestamp = now_jump

    dynamic_opps = detector.evaluate_desync(poly_event, bk_event, poly_orderbooks, matched_pair, current_time=now_jump)
    assert len(dynamic_opps) > 0
    dyn_opp = dynamic_opps[0]
    assert dyn_opp.signal_type == SignalType.DYNAMIC
    assert dyn_opp.price_change_delta_pct > 5.0
