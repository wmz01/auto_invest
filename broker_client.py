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
        """
        Dynamically calculates Net Worth based on ALL held assets.
        Returns a detailed ledger of current holdings for rebalancing strategies.
        """
        if self.paper and self.ledger:
            # Paper trading state routing (unchanged)
            state = self.ledger.get_paper_state()
            if not state:
                return {"net_worth": 0.0, "war_chest": 0.0, "current_holdings": {}}

            # Simple fallback for paper trading multi-asset simulation
            net_worth = state['current_cash'] + (state['current_shares'] * (current_price or 0.0))
            return {
                "net_worth": net_worth,
                "war_chest": state['current_cash'],
                "current_holdings": {"BASE_ASSET_PAPER": state['current_shares']}
            }

        # LIVE MULTI-ASSET ROUTING
        try:
            account = self.api.get_account()
            positions = self.api.list_positions()

            current_holdings = {}
            total_shares_value = 0.0

            # Dynamically aggregate all assets currently held in the Alpaca account
            for pos in positions:
                sym = pos.symbol
                qty = float(pos.qty)
                market_value = float(pos.market_value)

                current_holdings[sym] = qty
                total_shares_value += market_value

            war_chest = float(account.cash)
            net_worth = war_chest + total_shares_value

            return {
                "net_worth": net_worth,
                "war_chest": war_chest,
                "current_holdings": current_holdings
            }
        except Exception as e:
            print(f"[ERROR] Failed to fetch live account state: {e}")
            return {"net_worth": 0.0, "war_chest": 0.0, "current_holdings": {}}

    def queue_market_on_open_sell(self, symbol: str, notional_amount: float) -> dict:
        """Executes fractional sell orders to trim leverage and lock in profits."""
        if self.paper:
            print(f"[PAPER] Simulated SELL of ${notional_amount:,.2f} on {symbol}")
            return {"order_id": f"sim_sell_{int(time.time())}", "status": "accepted"}

        try:
            order = self.api.submit_order(
                symbol=symbol,
                notional=notional_amount,
                side='sell',
                type='market',
                time_in_force='day'
            )
            return {"order_id": order.id, "status": order.status}
        except Exception as e:
            print(f"[ERROR] Live SELL Order Failed: {e}")
            return {"order_id": "FAILED", "status": "failed"}

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