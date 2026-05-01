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