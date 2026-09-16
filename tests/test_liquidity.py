from data_models import OrderbookLevel
from calculator.liquidity import calculate_max_executable_liquidity


def test_calculate_max_executable_liquidity():
    asks = [
        OrderbookLevel(price=0.40, size=500),   # 500 * 0.40 = $200
        OrderbookLevel(price=0.403, size=500),  # 500 * 0.403 = $201.5 (+0.75% slippage, allowed < 1%)
        OrderbookLevel(price=0.42, size=1000),  # 1000 * 0.42 = $420 (+5.0% slippage, > 1% limit)
    ]

    max_usd, vwap = calculate_max_executable_liquidity(asks, max_slippage_pct=1.0)
    assert max_usd == 401.5
    assert vwap > 0.40 and vwap < 0.405
