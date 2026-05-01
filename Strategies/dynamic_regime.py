from .base_strategy import BaseStrategy

class DynamicRegimeStrategy(BaseStrategy):
    """
    The Dynamic Multi-Factor Regime Strategy.
    Expects account_state to contain 'net_worth' and 'war_chest'.
    Expects market_data to contain 'drawdown', 'rsi', 'vix', 'spread', 'fear_greed'.
    """

    def calculate_order_amount(self, market_data: dict, account_state: dict) -> dict:
        # 1. Load Parameters
        target_ratio = self.config.get("target_ratio", 0.8)
        lambda_replenish = self.config.get("lambda_replenish", 0.5)
        tau = self.config.get("tau", 0.02)
        alpha_mult = self.config.get("alpha_mult", 2.0)
        beta_mult = self.config.get("beta_mult", 4.0)
        daily_budget = self.config.get("daily_budget", 100.0)

        # Multi-factor thresholds
        crisis_vix_threshold = self.config.get("crisis_vix_threshold", 30.0)
        crisis_spread_threshold = self.config.get("crisis_spread_threshold", 5.0)
        crisis_fg_threshold = self.config.get("crisis_fg_threshold", 15.0)

        greedy_rsi_threshold = self.config.get("greedy_rsi_threshold", 75.0)
        greedy_drawdown_threshold = self.config.get("greedy_drawdown_threshold", -0.015)
        greedy_fg_threshold = self.config.get("greedy_fg_threshold", 60.0)
        greedy_preservation = self.config.get("greedy_capital_preservation", 0.5)

        # 2. Extract State
        live_net_worth = account_state.get("net_worth", 0.0)
        live_war_chest = account_state.get("war_chest", 0.0)

        # 3. Extract Features
        drawdown = market_data.get("drawdown", 0.0)
        rsi = market_data.get("rsi", 50.0)
        vix = market_data.get("vix", 20.0)
        spread = market_data.get("spread", 4.0)
        fg = market_data.get("fear_greed", 50.0)

        # 4. War Chest Health & Baseline Target Calculation
        target_cash = live_net_worth * (1.0 - target_ratio)
        h = (live_war_chest / target_cash) if target_cash > 0 else 1.0
        theta = max(0.1, min(1.5, 1.0 - (lambda_replenish * (1.0 - h))))

        b_daily = (daily_budget * target_ratio) * theta

        # 5. Multi-Factor Regime Logic
        if (vix > crisis_vix_threshold or spread > crisis_spread_threshold or fg < crisis_fg_threshold):
            regime = "CRISIS"
        elif (rsi > greedy_rsi_threshold and fg > greedy_fg_threshold and drawdown > greedy_drawdown_threshold):
            regime = "GREEDY"
        else:
            regime = "REGULAR"

        # 6. Apply Multipliers based on Regime
        d_t = abs(drawdown)
        if regime == "GREEDY":
            calculated_buy = b_daily * greedy_preservation
        elif regime == "REGULAR":
            calculated_buy = b_daily * (1.0 + (alpha_mult * max(0.0, d_t - tau)))
        elif regime == "CRISIS":
            calculated_buy = b_daily * 4.0 * (1.0 + (beta_mult * max(0.0, d_t)))

        # 7. Final Liquidity Constraint (You cannot spend money you do not have)
        actual_buy = min(calculated_buy, live_war_chest)

        # 8. Minimum Order Guardrail (Most brokers reject MOO orders under $1.00)
        if actual_buy < 1.00:
            actual_buy = 0.0

        return {
            "regime": regime,
            "target_buy_amount": round(actual_buy, 2)
        }