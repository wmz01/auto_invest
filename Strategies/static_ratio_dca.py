from .base_strategy import BaseStrategy


class StaticRatioDCAStrategy(BaseStrategy):
    """
    The Static Ratio DCA Strategy (e.g., 85/15):
    Invests a fixed percentage of the daily budget, leaving the rest in cash.
    Ignores all market indicators.
    """

    def calculate_order_amount(self, market_data: dict, account_state: dict) -> dict:
        # Pull parameters from the universal config
        daily_budget = self.config.get("daily_budget", 100.0)
        target_ratio = self.config.get("target_ratio", 0.85)  # Defaults to 85%

        live_war_chest = account_state.get("war_chest", 0.0)

        # Calculate the target spend (e.g., $100 * 0.85 = $85.00)
        target_buy = daily_budget * target_ratio

        # Guardrail: Cannot spend more than what is in the cash balance
        actual_buy = min(target_buy, live_war_chest)

        # Guardrail: Minimum order size for Alpaca fractional trading
        if actual_buy < 1.00:
            actual_buy = 0.0

        return {
            "regime": "STATIC_RATIO",
            "target_buy_amount": round(actual_buy, 2)
        }