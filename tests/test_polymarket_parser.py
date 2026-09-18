import pytest
from parsers.polymarket_ws import PolymarketWSParser

def test_extract_teams_and_tournament():
    parser = PolymarketWSParser()

    # CS2 StarLadder
    t1, t2, tourney = parser._extract_teams_and_tournament("Counter-Strike: MOUZ vs Natus Vincere (BO3) - StarLadder StarSeries Playoffs")
    assert t1 == "MOUZ"
    assert t2 == "Natus Vincere"
    assert "StarLadder" in tourney

    # LoL LPL
    t1, t2, tourney = parser._extract_teams_and_tournament("LoL: Team WE vs JD Gaming (BO5) - LPL Regional Finals Playoffs")
    assert t1 == "Team WE" or t1 == "WE"
    assert t2 == "JD Gaming"
    assert "LPL" in tourney

    # Will beat format
    t1, t2, _ = parser._extract_teams_and_tournament("Will Navi beat FaZe?")
    assert t1 == "Navi"
    assert t2 == "FaZe"

def test_match_game_and_tournament():
    parser = PolymarketWSParser()
    game, tourney = parser._match_game_and_tournament("Counter-Strike: MOUZ vs Natus Vincere (BO3)", "CS2 match description", ["CS2"], "StarLadder")
    assert game == "CS2"
    assert "StarLadder" in tourney


def test_extract_market_outcomes_3way_soccer():
    parser = PolymarketWSParser()
    raw_ev = {
        "title": "Brentford FC vs. Chelsea FC",
        "slug": "epl-bre-che-2026-09-18",
        "markets": [
            {
                "question": "Will Brentford FC win on 2026-09-18?",
                "outcomePrices": ["0.365", "0.635"],
                "clobTokenIds": ["tok_brentford", "tok_not_brentford"]
            },
            {
                "question": "Will Brentford FC vs. Chelsea FC end in a draw?",
                "outcomePrices": ["0.265", "0.735"],
                "clobTokenIds": ["tok_draw", "tok_not_draw"]
            },
            {
                "question": "Will Chelsea FC win on 2026-09-18?",
                "outcomePrices": ["0.375", "0.625"],
                "clobTokenIds": ["tok_chelsea", "tok_not_chelsea"]
            }
        ]
    }
    res = parser._extract_market_outcomes(raw_ev, "Brentford FC", "Chelsea FC")
    assert res is not None
    outcomes, tokens = res
    assert len(outcomes) == 3
    assert outcomes[0].name == "Brentford FC"
    assert abs(outcomes[0].price - 0.365) < 1e-4
    assert tokens[0] == "tok_brentford"

    assert outcomes[1].name == "Chelsea FC"
    assert abs(outcomes[1].price - 0.375) < 1e-4
    assert tokens[1] == "tok_chelsea"

    assert outcomes[2].name == "Draw"
    assert abs(outcomes[2].price - 0.265) < 1e-4
    assert tokens[2] == "tok_draw"


def test_extract_market_outcomes_2way_esports():
    parser = PolymarketWSParser()
    raw_ev = {
        "title": "Counter-Strike: MOUZ vs Natus Vincere (BO3) - StarLadder StarSeries Playoffs",
        "slug": "cs2-mouz-navi-2026-09-18",
        "markets": [
            {
                "question": "Counter-Strike: MOUZ vs Natus Vincere - Map 1 Winner",
                "outcomes": ["MOUZ", "Natus Vincere"],
                "outcomePrices": ["0", "1"],
                "clobTokenIds": ["m1_tok1", "m1_tok2"]
            },
            {
                "question": "Counter-Strike: MOUZ vs Natus Vincere (BO3) - StarLadder StarSeries Playoffs",
                "outcomes": ["Natus Vincere", "MOUZ"],  # inverted order in raw data
                "outcomePrices": ["0.45", "0.55"],
                "clobTokenIds": ["navi_tok", "mouz_tok"]
            }
        ]
    }
    res = parser._extract_market_outcomes(raw_ev, "MOUZ", "Natus Vincere")
    assert res is not None
    outcomes, tokens = res
    assert len(outcomes) == 2
    # Check that MOUZ correctly got 0.55 and mouz_tok despite inverted raw order
    assert outcomes[0].name == "MOUZ"
    assert abs(outcomes[0].price - 0.55) < 1e-4
    assert tokens[0] == "mouz_tok"

    assert outcomes[1].name == "Natus Vincere"
    assert abs(outcomes[1].price - 0.45) < 1e-4
    assert tokens[1] == "navi_tok"

