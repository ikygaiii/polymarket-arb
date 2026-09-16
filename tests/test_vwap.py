import pytest
from data_models import OrderbookLevel
from calculator.vwap import calculate_buy_vwap


def test_calculate_buy_vwap_single_level_exact_fill():
    asks = [OrderbookLevel(price=0.50, size=1000)]  # total value = 500 USD
    vwap = calculate_buy_vwap(asks, 500.0)
    assert vwap is not None
    assert abs(vwap - 0.50) < 1e-6


def test_calculate_buy_vwap_multi_level_fill():
    # Ask 1: price 0.50, size 500 (value $250)
    # Ask 2: price 0.52, size 1000 (value $520)
    asks = [
        OrderbookLevel(price=0.50, size=500),
        OrderbookLevel(price=0.52, size=1000),
    ]
    # For $500 stake: $250 at 0.50 (500 shares) + $250 at 0.52 (480.7692 shares) = 980.7692 shares
    # VWAP = 500 / 980.7692 = ~0.5098039
    vwap = calculate_buy_vwap(asks, 500.0)
    assert vwap is not None
    assert abs(vwap - 0.5098039) < 1e-5


def test_calculate_buy_vwap_insufficient_liquidity():
    asks = [OrderbookLevel(price=0.50, size=100)]  # total value = 50 USD
    vwap = calculate_buy_vwap(asks, 500.0)
    assert vwap is None


def test_calculate_buy_vwap_empty_asks():
    assert calculate_buy_vwap([], 100.0) is None
