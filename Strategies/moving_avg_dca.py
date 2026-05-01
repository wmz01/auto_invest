from .base_strategy import BaseStrategy


class MovingAverageDCAStrategy(BaseStrategy):
    """
    Moving Average Valuation DCA:
    Buys the baseline amount when the price is in an uptrend (Above 200 SMA).
    Scales up the buy amount proportionally when the price falls below the SMA.
    """

    def calculate_order_amount(self, market_data: dict, account_state: dict) -> dict:
        daily_budget = self.config.get("daily_budget", 100.0)
        base_buy = daily_budget * self.config.get("target_ratio", 0.85)
        aggressiveness = self.config.get("ma_aggressiveness", 3.0)

        close_price = market_data.get("close")
        sma_200 = market_data.get("sma_200")
        live_war_chest = account_state.get("war_chest", 0.0)

        if not close_price or not sma_200 or sma_200 == 0:
            # Fallback if data is missing
            target_buy = base_buy
            regime = "MA_FALLBACK"
        elif close_price < sma_200:
            # Price is undervalued relative to the trend
            discount = (sma_200 - close_price) / sma_200

            # e.g., If price is 10% below SMA, buy base * (1 + (0.10 * 3.0)) = 1.3x base
            target_buy = base_buy * (1.0 + (aggressiveness * discount))
            regime = "MA_UNDERVALUED"
        else:
            # Price is overvalued or trending upward
            target_buy = base_buy
            regime = "MA_UPTREND"

        # Guardrails
        actual_buy = min(target_buy, live_war_chest)
        if actual_buy < 1.00:
            actual_buy = 0.0

        return {
            "regime": regime,
            "target_buy_amount": round(actual_buy, 2)
        }