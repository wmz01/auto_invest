from abc import ABC, abstractmethod


class BaseStrategy(ABC):
    """Abstract Base Class for all inference engines."""

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def calculate_order_amount(self, market_data: dict, account_state: dict) -> dict:
        """
        Takes in market features and account balances.
        Returns a dictionary containing the regime detected and the target buy amount.
        """
        pass