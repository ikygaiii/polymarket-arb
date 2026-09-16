from typing import List, Optional
import logging
from data_models import OrderbookLevel

logger = logging.getLogger(__name__)


def calculate_buy_vwap(asks: List[OrderbookLevel], target_stake_usd: float) -> Optional[float]:
    """
    Calculates the Volume-Weighted Average Price (VWAP) for buying an outcome
    on Polymarket orderbook for a given target stake in USD.
    
    :param asks: List of OrderbookLevel sorted by price ascending (lowest ask first).
    :param target_stake_usd: Total USD amount intended to spend.
    :return: Effective VWAP price (float between 0 and 1) or None if depth is insufficient.
    """
    if not asks or target_stake_usd <= 0:
        return None

    # Sort asks by price ascending (lowest price first) just in case
    sorted_asks = sorted(asks, key=lambda lvl: lvl.price)
    
    remaining_usd = target_stake_usd
    total_shares = 0.0

    for level in sorted_asks:
        if level.price <= 0 or level.size <= 0:
            continue
            
        level_value_usd = level.price * level.size
        
        if level_value_usd >= remaining_usd:
            shares_bought = remaining_usd / level.price
            total_shares += shares_bought
            remaining_usd = 0.0
            break
        else:
            total_shares += level.size
            remaining_usd -= level_value_usd

    if remaining_usd > 1e-6:
        # Insufficient depth in orderbook to fill the target stake
        return None

    vwap_price = target_stake_usd / total_shares
    return vwap_price
