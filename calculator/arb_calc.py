import uuid
import logging
from typing import Optional, List, Dict
from datetime import datetime

import config
from data_models import (
    StandardizedEvent,
    Orderbook,
    MatchedPair,
    ArbitrageOpportunity,
)
from calculator.vwap import calculate_buy_vwap
from calculator.liquidity import calculate_max_executable_liquidity

logger = logging.getLogger(__name__)


class ArbitrageCalculator:
    def __init__(
        self,
        typical_stake_usd: float = config.TYPICAL_STAKE_USD,
        min_profit_pct: float = config.MIN_PROFIT_THRESHOLD_PCT,
        polymarket_fee_pct: float = config.POLYMARKET_TAKER_FEE_PCT,
        stale_threshold_sec: float = config.STALE_DATA_THRESHOLD_SEC,
    ):
        self.typical_stake_usd = typical_stake_usd
        self.min_profit_pct = min_profit_pct
        self.fee_factor = 1.0 - (polymarket_fee_pct / 100.0)
        self.stale_threshold_sec = stale_threshold_sec

    def is_fresh(self, timestamp: float, current_time: Optional[float] = None) -> bool:
        now = current_time or datetime.now().timestamp()
        return (now - timestamp) <= self.stale_threshold_sec

    def calculate_opportunity(
        self,
        poly_event: StandardizedEvent,
        bk_event: StandardizedEvent,
        poly_orderbooks: Dict[str, Orderbook],
        matched_pair: MatchedPair,
        current_time: Optional[float] = None,
    ) -> List[ArbitrageOpportunity]:
        now = current_time or datetime.now().timestamp()
        
        if not self.is_fresh(poly_event.timestamp, now) or not self.is_fresh(bk_event.timestamp, now):
            return []

        if len(bk_event.outcomes) < 2:
            return []
            
        bk_odds1 = bk_event.outcomes[0].price
        bk_odds2 = bk_event.outcomes[1].price
        
        if bk_odds1 <= 1.0 or bk_odds2 <= 1.0:
            return []

        bk_prob1 = 1.0 / bk_odds1
        bk_prob2 = 1.0 / bk_odds2

        if not poly_event.clob_token_ids or len(poly_event.clob_token_ids) < 2:
            return []
            
        token1_id = poly_event.clob_token_ids[0]
        token2_id = poly_event.clob_token_ids[1]

        ob1 = poly_orderbooks.get(token1_id)
        ob2 = poly_orderbooks.get(token2_id)

        if not ob1 or not ob2 or not ob1.asks or not ob2.asks:
            return []

        if not self.is_fresh(ob1.timestamp, now) or not self.is_fresh(ob2.timestamp, now):
            return []

        top_poly_price1 = ob1.best_ask
        top_poly_price2 = ob2.best_ask

        if top_poly_price1 is None or top_poly_price2 is None:
            return []

        estimated_leg_stake = self.typical_stake_usd / 2.0

        vwap1 = calculate_buy_vwap(ob1.asks, estimated_leg_stake)
        vwap2 = calculate_buy_vwap(ob2.asks, estimated_leg_stake)

        if vwap1 is None or vwap2 is None:
            return []

        opportunities: List[ArbitrageOpportunity] = []

        # Option A: Buy Team 1 on Polymarket, Bet Team 2 on BK
        cost_poly1 = vwap1 / self.fee_factor
        cost_bk2 = bk_prob2
        sum_cost_a = cost_poly1 + cost_bk2

        if sum_cost_a < 1.0:
            profit_pct_a = ((1.0 / sum_cost_a) - 1.0) * 100.0
            if profit_pct_a >= self.min_profit_pct:
                poly_stake = self.typical_stake_usd * (cost_poly1 / sum_cost_a)
                bk_stake = self.typical_stake_usd * (cost_bk2 / sum_cost_a)
                
                exact_vwap1 = calculate_buy_vwap(ob1.asks, poly_stake)
                if exact_vwap1 is not None:
                    cost_poly1_exact = exact_vwap1 / self.fee_factor
                    sum_cost_exact = cost_poly1_exact + cost_bk2
                    final_profit_pct = ((1.0 / sum_cost_exact) - 1.0) * 100.0
                    
                    if final_profit_pct >= self.min_profit_pct:
                        target_payout = self.typical_stake_usd / sum_cost_exact
                        net_profit_usd = target_payout - self.typical_stake_usd
                        
                        leg1_profit = (poly_stake * (1.0 / exact_vwap1) * self.fee_factor) - (poly_stake + bk_stake)
                        leg2_profit = (bk_stake * bk_odds2) - (poly_stake + bk_stake)

                        max_exec_usd, _ = calculate_max_executable_liquidity(ob1.asks, config.MAX_SLIPPAGE_PCT)

                        data_freshness = max(
                            now - poly_event.timestamp,
                            now - bk_event.timestamp,
                            now - ob1.timestamp
                        )
                        
                        opportunities.append(ArbitrageOpportunity(
                            signal_id=str(uuid.uuid4()),
                            event_title=f"{poly_event.team1} vs {poly_event.team2}",
                            game=poly_event.game,
                            tournament=poly_event.tournament,
                            team1=poly_event.team1,
                            team2=poly_event.team2,
                            start_time=poly_event.start_time,
                            bk_platform=bk_event.platform,
                            bk_event_id=bk_event.event_id,
                            bk_market_url=bk_event.market_url,
                            bk_team1_odds=bk_odds1,
                            bk_team2_odds=bk_odds2,
                            bk_implied_prob1=round(bk_prob1, 4),
                            bk_implied_prob2=round(bk_prob2, 4),
                            poly_event_id=poly_event.event_id,
                            poly_market_url=poly_event.market_url,
                            poly_team1_vwap=exact_vwap1,
                            poly_team2_vwap=vwap2,
                            poly_team1_top_price=top_poly_price1,
                            poly_team2_top_price=top_poly_price2,
                            poly_implied_prob1=round(exact_vwap1, 4),
                            poly_implied_prob2=round(vwap2, 4),
                            poly_outcome_selected=poly_event.team1,
                            poly_stake=round(poly_stake, 2),
                            bk_stake=round(bk_stake, 2),
                            total_stake=round(self.typical_stake_usd, 2),
                            sum_implied_prob=round(sum_cost_exact, 4),
                            profit_pct=round(final_profit_pct, 2),
                            net_profit_usd=round(net_profit_usd, 2),
                            leg1_profit_usd=round(leg1_profit, 2),
                            leg2_profit_usd=round(leg2_profit, 2),
                            max_executable_stake_usd=max_exec_usd,
                            poly_timestamp=poly_event.timestamp,
                            bk_timestamp=bk_event.timestamp,
                            data_freshness_sec=round(data_freshness, 1),
                            status="new"
                        ))

        # Option B: Buy Team 2 on Polymarket, Bet Team 1 on BK
        cost_poly2 = vwap2 / self.fee_factor
        cost_bk1 = bk_prob1
        sum_cost_b = cost_poly2 + cost_bk1

        if sum_cost_b < 1.0:
            profit_pct_b = ((1.0 / sum_cost_b) - 1.0) * 100.0
            if profit_pct_b >= self.min_profit_pct:
                poly_stake = self.typical_stake_usd * (cost_poly2 / sum_cost_b)
                bk_stake = self.typical_stake_usd * (cost_bk1 / sum_cost_b)
                
                exact_vwap2 = calculate_buy_vwap(ob2.asks, poly_stake)
                if exact_vwap2 is not None:
                    cost_poly2_exact = exact_vwap2 / self.fee_factor
                    sum_cost_exact = cost_poly2_exact + cost_bk1
                    final_profit_pct = ((1.0 / sum_cost_exact) - 1.0) * 100.0
                    
                    if final_profit_pct >= self.min_profit_pct:
                        target_payout = self.typical_stake_usd / sum_cost_exact
                        net_profit_usd = target_payout - self.typical_stake_usd
                        
                        leg1_profit = (bk_stake * bk_odds1) - (poly_stake + bk_stake)
                        leg2_profit = (poly_stake * (1.0 / exact_vwap2) * self.fee_factor) - (poly_stake + bk_stake)

                        max_exec_usd, _ = calculate_max_executable_liquidity(ob2.asks, config.MAX_SLIPPAGE_PCT)

                        data_freshness = max(
                            now - poly_event.timestamp,
                            now - bk_event.timestamp,
                            now - ob2.timestamp
                        )
                        
                        opportunities.append(ArbitrageOpportunity(
                            signal_id=str(uuid.uuid4()),
                            event_title=f"{poly_event.team1} vs {poly_event.team2}",
                            game=poly_event.game,
                            tournament=poly_event.tournament,
                            team1=poly_event.team1,
                            team2=poly_event.team2,
                            start_time=poly_event.start_time,
                            bk_platform=bk_event.platform,
                            bk_event_id=bk_event.event_id,
                            bk_market_url=bk_event.market_url,
                            bk_team1_odds=bk_odds1,
                            bk_team2_odds=bk_odds2,
                            bk_implied_prob1=round(bk_prob1, 4),
                            bk_implied_prob2=round(bk_prob2, 4),
                            poly_event_id=poly_event.event_id,
                            poly_market_url=poly_event.market_url,
                            poly_team1_vwap=vwap1,
                            poly_team2_vwap=exact_vwap2,
                            poly_team1_top_price=top_poly_price1,
                            poly_team2_top_price=top_poly_price2,
                            poly_implied_prob1=round(vwap1, 4),
                            poly_implied_prob2=round(exact_vwap2, 4),
                            poly_outcome_selected=poly_event.team2,
                            poly_stake=round(poly_stake, 2),
                            bk_stake=round(bk_stake, 2),
                            total_stake=round(self.typical_stake_usd, 2),
                            sum_implied_prob=round(sum_cost_exact, 4),
                            profit_pct=round(final_profit_pct, 2),
                            net_profit_usd=round(net_profit_usd, 2),
                            leg1_profit_usd=round(leg1_profit, 2),
                            leg2_profit_usd=round(leg2_profit, 2),
                            max_executable_stake_usd=max_exec_usd,
                            poly_timestamp=poly_event.timestamp,
                            bk_timestamp=bk_event.timestamp,
                            data_freshness_sec=round(data_freshness, 1),
                            status="new"
                        ))

        return opportunities
