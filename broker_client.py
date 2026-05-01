import os
import requests
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from datetime import datetime, timedelta

class LiveBroker:
    def __init__(self, api_key: str, secret_key: str, paper: bool = True, ledger=None, daily_budget: float = 100.0):
        self.api_key = api_key
        self.secret_key = secret_key

        self.paper = paper
        self.ledger = ledger
        self.daily_budget = daily_budget
        mode = "PAPER" if paper else "LIVE REAL MONEY"
        print(f"[BROKER] Initializing Alpaca Client ({mode} Mode)...")
        self.client = TradingClient(api_key=api_key, secret_key=secret_key, paper=paper)

    def _normalize_status(self, raw_status) -> str:
        """Extracts the raw string value from an Alpaca OrderStatus Enum."""
        # If it's an enum, it has a .value property
        if hasattr(raw_status, 'value'):
            return str(raw_status.value).lower()

        # Fallback if it's somehow already stringified as "OrderStatus.PENDING_NEW"
        status_str = str(raw_status)
        if '.' in status_str:
            status_str = status_str.split('.')[-1]

        return status_str.lower()

    def get_account_state(self, current_price: float = None) -> dict:
        """Retrieves live account state, or calculates simulated state."""
        if not self.paper:
            # ==========================================
            # LIVE ACCOUNT: Query Alpaca API
            # ==========================================
            try:
                account = self.client.get_account()
                war_chest = float(account.non_marginable_buying_power)
                net_worth = float(account.portfolio_value)
                return {"net_worth": net_worth, "war_chest": war_chest}
            except Exception as e:
                error_msg = f"⚠️ **Broker Warning:** Failed to retrieve live account state (`{e}`)."
                print(error_msg)
                return {"net_worth": 0.0, "war_chest": 0.0}

        else:
            # ==========================================
            # PAPER SIMULATION: Calculate from Database
            # ==========================================
            if not self.ledger or current_price is None:
                raise ValueError("Ledger and current_price must be provided in paper mode.")

            state = self.ledger.get_paper_state()

            # If the database is completely empty (e.g. before the first run)
            if state is None:
                return {"net_worth": 0.0, "war_chest": 0.0}

            cash = state['current_cash']
            shares = state['current_shares']

            # Net Worth = Uninvested Cash + Value of Holdings
            net_worth = cash + (shares * current_price)

            return {
                "net_worth": net_worth,
                "war_chest": cash
            }

    def get_todays_cash_flow(self) -> float:
        """Fetches live deposits, or simulates a bi-weekly paycheck in paper mode."""
        if not self.paper:
            # ==========================================
            # LIVE ACCOUNT: Manual REST API Workaround
            # ==========================================
            try:
                base_url = "https://paper-api.alpaca.markets" if self.paper else "https://api.alpaca.markets"
                url = f"{base_url}/v2/account/activities"

                headers = {
                    "APCA-API-KEY-ID": self.api_key,
                    "APCA-API-SECRET-KEY": self.secret_key,
                    "accept": "application/json"
                }

                params = {
                    "activity_types": "CSD,INT",
                    "date": datetime.now().date().isoformat()
                }

                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()
                activities = response.json()

                total_deposit = 0.0
                for activity in activities:
                    net_amount = activity.get("net_amount")
                    if net_amount and float(net_amount) > 0:
                        total_deposit += float(net_amount)

                        # Print exactly what type of cash just landed
                        act_type = "Interest Payment" if activity.get("activity_type") == "INT" else "External Deposit"
                        print(f"[BROKER] Detected {act_type} today: ${float(net_amount):,.2f}")

                return total_deposit

            except Exception as e:
                print(f"[BROKER WARNING] Could not fetch daily live deposit activities: {e}")
                return 0.0

        else:
            # ==========================================
            # PAPER SIMULATION: Query Local Database
            # ==========================================
            if not self.ledger:
                raise ValueError("Ledger must be provided to LiveBroker in paper mode.")

            biweekly_deposit = 10 * self.daily_budget
            today = datetime.now().date()
            state = self.ledger.get_paper_state()

            # Day 1: Initialize the completely empty account
            if state is None:
                next_deposit = today + timedelta(days=14)
                self.ledger.update_paper_state(
                    current_cash=biweekly_deposit,
                    current_shares=0.0,
                    next_deposit_date=next_deposit.isoformat()
                )
                print(f"[SIMULATION] Initialized Paper Account. Deposited Paycheck: ${biweekly_deposit:,.2f}")
                return biweekly_deposit

            # Routine Check: Is it Payday?
            next_deposit_date = datetime.fromisoformat(state['next_deposit_date']).date()
            if today >= next_deposit_date:
                new_cash = state['current_cash'] + biweekly_deposit
                next_deposit = today + timedelta(days=14)

                self.ledger.update_paper_state(
                    current_cash=new_cash,
                    current_shares=state['current_shares'],
                    next_deposit_date=next_deposit.isoformat()
                )
                print(f"[SIMULATION] Bi-Weekly Payday! Deposited: ${biweekly_deposit:,.2f}")
                return biweekly_deposit

            # Not payday, no new cash
            return 0.0

    def queue_market_on_open_buy(self, symbol: str, notional_amount: float) -> dict:
        print(f"[BROKER] Submitting MOO order for ${notional_amount:,.2f} of {symbol}...")

        market_order_data = MarketOrderRequest(
            symbol=symbol,
            notional=notional_amount,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY
        )

        try:
            order = self.client.submit_order(order_data=market_order_data)
            normalized_status = self._normalize_status(order.status)
            print(f"[BROKER] Success. Order {order.id} is {normalized_status}.")

            return {
                "order_id": str(order.id),
                "status": normalized_status
            }
        except Exception as e:
            print(f"[BROKER ERROR] Failed to route order: {e}")
            return {"order_id": "FAILED", "status": "failed"}

    def get_order_status(self, order_id: str) -> dict:
        if order_id == "FAILED" or order_id == "SKIPPED":
            return {"status": "failed", "filled_qty": 0.0, "filled_avg_price": 0.0}

        try:
            order = self.client.get_order_by_id(order_id)
            return {
                "status": self._normalize_status(order.status),
                "filled_qty": float(order.filled_qty) if order.filled_qty else 0.0,
                "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else 0.0
            }
        except Exception as e:
            print(f"[BROKER ERROR] Could not fetch status for {order_id}: {e}")
            return {"status": "unknown", "filled_qty": 0.0, "filled_avg_price": 0.0}