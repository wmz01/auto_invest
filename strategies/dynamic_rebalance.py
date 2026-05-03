from .base_strategy import BaseStrategy


class DynamicRebalanceEDCA(BaseStrategy):
    """
    Combines Flow-Based DCA with Regime-Targeted Rebalancing.
    If the portfolio exceeds 25% leverage DURING an overbought market (euphoria),
    it liquidates the excess leverage to lock in profits. The cash proceeds
    are caught by the war chest and naturally reinvested into the base asset.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_asset = self.config.get("base_asset", "QQQ")
        self.leveraged_asset = self.config.get("leveraged_asset", "TQQQ")
        self.daily_budget = self.config.get("daily_budget", 100.0)
        self.target_ratio = self.config.get("target_ratio", 0.80)

        # Risk Management Thresholds
        self.max_lev_weight = self.config.get("max_lev_weight", 0.25)  # Max 25% TQQQ
        self.euphoria_rsi = self.config.get("euphoria_rsi", 75.0)  # Overbought signal

    def calculate_order_amount(self, market_data: dict, account_state: dict) -> dict:
        drawdown = market_data.get("drawdown", 0.0)
        rsi = market_data.get("rsi", 50.0)
        vix = market_data.get("vix", 15.0)

        live_war_chest = account_state.get("war_chest", 0.0)
        net_worth = account_state.get("net_worth", 0.0)

        # Calculate current Leverage Weight
        current_holdings = account_state.get("current_holdings", {})
        lev_shares = current_holdings.get(self.leveraged_asset, 0.0)
        lev_price = market_data.get("lev_Close", 0.0)

        current_lev_value = lev_shares * lev_price
        current_lev_weight = (current_lev_value / net_worth) if net_worth > 0 else 0.0

        # ========================================================
        # 1. OVERRIDE: THE EUPHORIA REBALANCE (TAKE PROFIT)
        # ========================================================
        # If we are near All Time Highs (drawdown >= -0.02), highly overbought (RSI > 75),
        # AND our leverage exceeds the 25% threshold, trigger a SELL.
        if drawdown >= -0.02 and rsi > self.euphoria_rsi:
            # Calculate exactly how many dollars of TQQQ we need to sell
            # to get back down to the target risk threshold.
            target_lev_value = net_worth * self.max_lev_weight
            excess_lev_dollars = current_lev_value - target_lev_value

            return {
                "regime_detected": "TAKE_PROFIT_REBALANCE",
                "target_orders": {
                    self.base_asset: 0.0,
                    self.leveraged_asset: -round(excess_lev_dollars, 2)  # Negative = SELL
                }
            }

        # ========================================================
        # 2. NORMAL EDCA LOGIC (BUY & ACCUMULATE)
        # ========================================================
        base_buy = self.daily_budget * self.target_ratio

        # Require BOTH a deep price drop AND extreme market panic (VIX spike)
        if drawdown <= -0.20 and vix >= 30.0:
            multiplier = self.config.get("edca_severe_mult", 3.0)
            regime = "EDCA_SEVERE_CRASH"
        elif drawdown <= -0.15:
            multiplier = self.config.get("edca_heavy_mult", 2.0)
            regime = "EDCA_HEAVY_CORRECTION"
        elif drawdown <= -0.05:
            multiplier = self.config.get("edca_mild_mult", 1.5)
            regime = "EDCA_MILD_DIP"
        elif drawdown >= -0.01 and rsi > 70.0:
            multiplier = 0.5  # Hoard cash aggressively at the top
            regime = "EDCA_GREEDY"
        else:
            multiplier = 1.0
            regime = "EDCA_BASELINE"

        target_total_spend = base_buy * multiplier

        # Pacing: Never spend more than 5% of war chest in a single day
        max_allowable_spend = base_buy + (live_war_chest * 0.05)
        # max_allowable_spend = live_war_chest
        actual_total_spend = min(target_total_spend, max_allowable_spend, live_war_chest + base_buy)

        if actual_total_spend < 1.00:
            actual_total_spend = 0.0

        # Overflow Split
        if actual_total_spend <= base_buy:
            qqq_dollars = actual_total_spend
            tqqq_dollars = 0.0
        else:
            qqq_dollars = base_buy
            tqqq_dollars = actual_total_spend - base_buy

        return {
            "regime_detected": regime,
            "target_orders": {
                self.base_asset: round(qqq_dollars, 2),
                self.leveraged_asset: round(tqqq_dollars, 2)
            }
        }