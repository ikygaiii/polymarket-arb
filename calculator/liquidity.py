import logging
from typing import List, Tuple, Optional
from data_models import Orderbook, OrderbookLevel
import config

logger = logging.getLogger(__name__)


def calculate_max_executable_liquidity(
    asks: List[OrderbookLevel],
    max_slippage_pct: float = config.MAX_SLIPPAGE_PCT
) -> Tuple[float, float]:
    """
    Calculates the maximum USD stake that can be executed on Polymarket asks
    without exceeding max_slippage_pct from the top ask price.

    Returns:
        (max_executable_usd, effective_vwap)
    """
    if not asks:
        return 0.0, 0.0

    sorted_asks = sorted(asks, key=lambda x: x.price)
    top_price = sorted_asks[0].price

    if top_price <= 0:
        return 0.0, 0.0

    max_allowed_price = top_price * (1.0 + (max_slippage_pct / 100.0))

    cum_usd = 0.0
    cum_shares = 0.0

    for level in sorted_asks:
        if level.price > max_allowed_price:
            break
        
        level_usd = level.price * level.size
        cum_usd += level_usd
        cum_shares += level.size

    effective_vwap = (cum_usd / cum_shares) if cum_shares > 0 else top_price
    return round(cum_usd, 2), round(effective_vwap, 4)
