import math
from .base_strategy import BaseStrategy


class VolatilityTargetingStrategy(BaseStrategy):
    """
    Volatility Targeting Baseline:
    Dynamically sizes portfolio exposure inversely proportional to market volatility.
    Targets a specific annualized volatility (e.g., 15%).
    Will BUY when volatility drops, and SELL when volatility spikes.
    """

    def calculate_order_amount(self, market_data: dict, account_state: dict) -> dict:
        # Pull parameter from config (defaults to 15% target volatility)
        target_vol = self.config.get("target_vol", 0.15)

        # Get current state
        curr_vol = market_data.get("realized_vol_20d")
        net_worth = account_state.get("net_worth", 0.0)
        war_chest = account_state.get("war_chest", 0.0)

        # Derive the current value of invested assets
        shares_value = net_worth - war_chest

        # Calculate target exposure weight
        if curr_vol is None or curr_vol == 0 or math.isnan(curr_vol):
            target_weight = 1.0  # Default to fully invested if data is missing
        else:
            target_weight = target_vol / curr_vol
            target_weight = min(target_weight, 1.0)  # Never use leverage (cap at 100%)

        # Calculate the exact dollar amount we want to have in the market
        target_equity = net_worth * target_weight
        diff = target_equity - shares_value

        target_buy = 0.0
        target_sell = 0.0

        if diff > 0:
            target_buy = diff
        elif diff < 0:
            target_sell = abs(diff)

        # Guardrails (No micro-transactions)
        if target_buy < 1.00: target_buy = 0.0
        if target_sell < 1.00: target_sell = 0.0

        return {
            "regime": "VOL_TARGET",
            "target_buy_amount": round(target_buy, 2),
            "target_sell_amount": round(target_sell, 2)
        }