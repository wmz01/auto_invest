from .base_strategy import BaseStrategy


class FixedSplitStrategy(BaseStrategy):
    """
    A rigid baseline strategy that ignores market conditions.
    It splits the daily budget into two assets based on fixed percentage weights.
    It uses the standard config keys to perfectly match the backtester engine.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        # Use universal keys so it automatically adapts to whatever tickers you provide
        self.base_asset = self.config.get("base_asset", "QQQ")
        self.leveraged_asset = self.config.get("leveraged_asset", "SPY")

        self.weight_base = self.config.get("weight_base", 0.60)
        self.weight_lev = self.config.get("weight_lev", 0.40)

        self.daily_budget = self.config.get("daily_budget", 100.0)

    def calculate_order_amount(self, market_data: dict, account_state: dict) -> dict:
        dollars_base = self.daily_budget * self.weight_base
        dollars_lev = self.daily_budget * self.weight_lev

        return {
            "regime_detected": "FIXED_SPLIT_DCA",
            "target_orders": {
                self.base_asset: round(dollars_base, 2),
                self.leveraged_asset: round(dollars_lev, 2)
            }
        }