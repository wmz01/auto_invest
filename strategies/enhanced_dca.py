from .base_strategy import BaseStrategy


class EnhancedDCAStrategy(BaseStrategy):
    """
    Enhanced DCA (Drawdown Multiplier):
    Increases the daily buy amount dynamically based on how far the asset
    has fallen from its All-Time High. Protects cash during bull runs.
    """

    def calculate_order_amount(self, market_data: dict, account_state: dict) -> dict:
        daily_budget = self.config.get("daily_budget", 100.0)

        # You can define target_ratio if you want a baseline cash hoard (e.g., 0.85).
        # If set to 1.0, it tries to spend the whole $100 every day unless in a drawdown.
        base_buy = daily_budget * self.config.get("target_ratio", 0.85)

        drawdown = market_data.get("drawdown", 0.0)
        live_war_chest = account_state.get("war_chest", 0.0)

        # Drawdown logic (Values are negative, e.g., -0.15 is a 15% drop)
        if drawdown <= -0.20:
            multiplier = self.config.get("edca_severe_mult", 3.0)  # -20% Crash
            regime = "EDCA_SEVERE"
        elif drawdown <= -0.10:
            multiplier = self.config.get("edca_heavy_mult", 2.0)  # -10% Correction
            regime = "EDCA_HEAVY"
        elif drawdown <= -0.05:
            multiplier = self.config.get("edca_mild_mult", 1.5)  # -5% Dip
            regime = "EDCA_MILD"
        # elif drawdown >= -0.01:
        #     multiplier = 0.75
        #     regime = "GREEDY"
        else:
            multiplier = 1.0  # Bull Market / ATH
            regime = "EDCA_BASELINE"

        target_buy = base_buy * multiplier

        # Guardrails
        actual_buy = min(target_buy, live_war_chest)
        if actual_buy < 1.00:
            actual_buy = 0.0

        return {
            "regime": regime,
            "target_buy_amount": round(actual_buy, 2)
        }

class OverflowEDCAStrategy(BaseStrategy):
    """
    Core-Satellite Overflow Strategy:
    The standard daily budget ($80) always buys the base asset (QQQ).
    During a crash, the multiplier increases the total spend.
    100% of the EXCESS spend overflows exclusively into the leveraged asset (TQQQ).
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_asset = self.config.get("base_asset", "QQQ")
        self.leveraged_asset = self.config.get("leveraged_asset", "TQQQ")
        self.daily_budget = self.config.get("daily_budget", 100.0)

        # 0.8 means we spend $80 daily, hoarding $20 for the crash
        self.target_ratio = self.config.get("target_ratio", 0.80)

    def calculate_order_amount(self, market_data: dict, account_state: dict) -> dict:
        drawdown = market_data.get("drawdown", 0.0)
        live_war_chest = account_state.get("war_chest", 0.0)

        # Baseline QQQ purchase
        base_buy = self.daily_budget * self.target_ratio

        # 1. Determine Total Target Spend (EDCA Logic)
        if drawdown <= -0.20:
            multiplier = self.config.get("edca_severe_mult", 3.0)  # e.g., 3.0 * $80 = $240
            regime = "EDCA_SEVERE_CRASH"
        elif drawdown <= -0.10:
            multiplier = self.config.get("edca_heavy_mult", 2.0)  # e.g., 2.0 * $80 = $160
            regime = "EDCA_HEAVY_CORRECTION"
        elif drawdown <= -0.05:
            multiplier = self.config.get("edca_mild_mult", 1.5)  # e.g., 1.5 * $80 = $120
            regime = "EDCA_MILD_DIP"
        elif drawdown >= -0.01:
            multiplier = 0.8  # e.g., 1.5 * $80 = $120
            regime = "EDCA_GREEDY"
        else:
            multiplier = 1.0  # e.g., 1.0 * $80 = $80
            regime = "EDCA_BASELINE"

        target_total_spend = base_buy * multiplier

        # Guardrail: Cannot spend more cash than we actually have
        actual_total_spend = min(target_total_spend, live_war_chest)
        if actual_total_spend < 1.00:
            actual_total_spend = 0.0

        # 2. The "Overflow" Split Logic
        if actual_total_spend <= base_buy:
            # Normal market (or running out of cash): Everything goes to QQQ
            qqq_dollars = actual_total_spend
            tqqq_dollars = 0.0
        else:
            # Crash market: Base goes to QQQ, the excess goes to TQQQ
            qqq_dollars = base_buy
            tqqq_dollars = actual_total_spend - base_buy

        return {
            "regime_detected": regime,
            "target_orders": {
                self.base_asset: round(qqq_dollars, 2),
                self.leveraged_asset: round(tqqq_dollars, 2)
            }
        }