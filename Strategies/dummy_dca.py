from .base_strategy import BaseStrategy

class DummyDCAStrategy(BaseStrategy):
    """
    The Dummy DCA Strategy: Invest a fixed daily amount, completely ignoring the market.
    """

    def calculate_order_amount(self, market_data: dict, account_state: dict) -> dict:
        daily_budget = self.config.get("daily_budget", 100.0)
        live_war_chest = account_state.get("war_chest", 0.0)

        # Guardrail: Cannot spend more than what is in the cash balance
        actual_buy = min(daily_budget, live_war_chest)

        # Guardrail: Minimum order size
        if actual_buy < 1.00:
            actual_buy = 0.0

        return {
            "regime": "BASELINE",
            "target_buy_amount": round(actual_buy, 2)
        }