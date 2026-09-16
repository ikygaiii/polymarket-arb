import time
from datetime import datetime
from data_models import (
    StandardizedEvent,
    Outcome,
    Orderbook,
    OrderbookLevel,
    MatchedPair,
)
from calculator.arb_calc import ArbitrageCalculator


def test_arb_calculator_valid_opportunity():
    now = time.time()
    
    # Polymarket event: Team 1 vs Team 2
    poly_event = StandardizedEvent(
        event_id="poly_1",
        platform="Polymarket",
        game="CS2",
        tournament="IEM Katowice",
        team1="Navi",
        team2="FaZe",
        outcomes=[Outcome(name="Navi", price=0.40), Outcome(name="FaZe", price=0.60)],
        timestamp=now - 5,
        clob_token_ids=["tok_1", "tok_2"]
    )

    # BK Event: Navi @ 2.20, FaZe @ 1.70
    bk_event = StandardizedEvent(
        event_id="bk_1",
        platform="Pinnacle",
        game="CS2",
        tournament="IEM Katowice 2026",
        team1="Natus Vincere",
        team2="FaZe Clan",
        outcomes=[Outcome(name="Natus Vincere", price=2.20), Outcome(name="FaZe Clan", price=1.70)],
        timestamp=now - 10,
    )

    # Orderbook: tok_1 ask price 0.40, depth $1000; tok_2 ask price 0.60, depth $1000
    poly_orderbooks = {
        "tok_1": Orderbook(
            token_id="tok_1",
            asks=[OrderbookLevel(price=0.40, size=2500)],  # 2500 * 0.40 = $1000
            timestamp=now - 2
        ),
        "tok_2": Orderbook(
            token_id="tok_2",
            asks=[OrderbookLevel(price=0.60, size=2500)],  # 2500 * 0.60 = $1500
            timestamp=now - 2
        )
    }

    matched_pair = MatchedPair(
        bk_event_id="bk_1",
        polymarket_event_id="poly_1",
        confidence=0.95,
        match_type="exact",
        rules_compatible=True
    )

    # Option A: Buy Navi on Polymarket @ VWAP 0.40 (cost ~0.40 / 0.98 = 0.40816), Bet FaZe on BK @ 1.70 (cost 1 / 1.70 = 0.58823)
    # Total cost sum = 0.40816 + 0.58823 = 0.99639 < 1.0 -> Profit ~ 0.36%
    # With min_profit_pct=0.1% to test detection:
    calc = ArbitrageCalculator(typical_stake_usd=1000.0, min_profit_pct=0.1, polymarket_fee_pct=2.0)
    opps = calc.calculate_opportunity(poly_event, bk_event, poly_orderbooks, matched_pair, current_time=now)
    
    assert len(opps) > 0
    opp = opps[0]
    assert opp.team1 == "Navi"
    assert opp.poly_outcome_selected == "Navi"
    assert opp.profit_pct > 0.1
    assert abs(opp.total_stake - 1000.0) < 1e-2


def test_arb_calculator_stale_data_rejected():
    now = time.time()
    
    poly_event = StandardizedEvent(
        event_id="poly_1",
        platform="Polymarket",
        game="CS2",
        tournament="IEM Katowice",
        team1="Navi",
        team2="FaZe",
        outcomes=[Outcome(name="Navi", price=0.40), Outcome(name="FaZe", price=0.60)],
        timestamp=now - 500,  # 500 seconds ago > stale threshold
        clob_token_ids=["tok_1", "tok_2"]
    )

    bk_event = StandardizedEvent(
        event_id="bk_1",
        platform="Pinnacle",
        game="CS2",
        tournament="IEM Katowice",
        team1="Navi",
        team2="FaZe",
        outcomes=[Outcome(name="Navi", price=2.20), Outcome(name="FaZe", price=1.70)],
        timestamp=now - 5,
    )

    poly_orderbooks = {
        "tok_1": Orderbook(token_id="tok_1", asks=[OrderbookLevel(price=0.40, size=2500)], timestamp=now - 2),
        "tok_2": Orderbook(token_id="tok_2", asks=[OrderbookLevel(price=0.60, size=2500)], timestamp=now - 2)
    }

    matched_pair = MatchedPair(
        bk_event_id="bk_1",
        polymarket_event_id="poly_1",
        confidence=0.95,
        match_type="exact",
        rules_compatible=True
    )

    calc = ArbitrageCalculator(stale_threshold_sec=180)
    opps = calc.calculate_opportunity(poly_event, bk_event, poly_orderbooks, matched_pair, current_time=now)
    assert len(opps) == 0
