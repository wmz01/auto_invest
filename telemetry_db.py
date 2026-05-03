import sqlite3
import os
import json
from datetime import datetime


class TradingLedger:
    def __init__(self, strategy_name: str, paper: bool = True):
        # Clean the strategy name (replace spaces with underscores, lowercase)
        clean_name = strategy_name.strip().replace(" ", "_").lower()
        mode = "paper" if paper else "live"

        # Dynamically route to the correct database file
        db_name = f"{clean_name}_{mode}.db"

        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()

        self.pending_statuses = (
            'new', 'accepted', 'pending_new', 'accepted_for_bidding',
            'held', 'queued', 'partially_filled'
        )

        self._create_table()

    def _create_table(self):
        # 1. Execution Logs Table (Multi-Asset JSON Schema)
        self.cursor.execute('''
                            CREATE TABLE IF NOT EXISTS execution_logs
                            (
                                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                                timestamp        TEXT,

                                -- State of the World
                                base_asset_price REAL,
                                vix_value        REAL,
                                rsi_value        REAL,
                                spread_value     REAL,
                                fear_greed_value REAL,

                                -- The Brain
                                regime_detected  TEXT,
                                war_chest_before REAL,

                                -- The Action (JSON strings)
                                target_orders    TEXT,
                                alpaca_order_ids TEXT,
                                order_statuses   TEXT,

                                -- Reconciliation
                                filled_qty       REAL DEFAULT 0.0,
                                filled_avg_price REAL DEFAULT 0.0
                            )
                            ''')
        # 2. Equity Curve Table
        self.cursor.execute('''
                            CREATE TABLE IF NOT EXISTS daily_equity_curve
                            (
                                date             TEXT PRIMARY KEY,
                                total_net_worth  REAL,
                                free_cash        REAL,
                                base_asset_price REAL,
                                net_cash_flow    REAL
                            )
                            ''')
        # 3. Paper Account Table
        self.cursor.execute('''
                            CREATE TABLE IF NOT EXISTS paper_account_state
                            (
                                id                INTEGER PRIMARY KEY CHECK (id = 1),
                                current_cash      REAL DEFAULT 0.0,
                                current_shares    REAL DEFAULT 0.0,
                                next_deposit_date TEXT
                            )
                            ''')
        self.conn.commit()

    def log_equity_snapshot(self, net_worth: float, free_cash: float, base_price: float, cash_flow: float = 0.0):
        today = datetime.now().strftime("%Y-%m-%d")

        self.cursor.execute('''
            INSERT OR REPLACE INTO daily_equity_curve 
            (date, total_net_worth, free_cash, base_asset_price, net_cash_flow)
            VALUES (?, ?, ?, ?, ?)
        ''', (today, net_worth, free_cash, base_price, cash_flow))

        self.conn.commit()
        print(
            f"[DATABASE] Logged equity snapshot: Net Worth=${net_worth:,.2f} | Base Asset=${base_price:,.2f} | Deposit=${cash_flow:,.2f}")

    def log_execution(self, features: dict, regime: str, war_chest: float, target_orders: dict, order_responses: dict):
        """Safely serializes multi-asset order routing into JSON strings for database insertion."""
        target_buy_str = json.dumps(target_orders)

        ids_dict = {sym: resp.get("order_id", "N/A") for sym, resp in order_responses.items()}
        statuses_dict = {sym: resp.get("status", "N/A") for sym, resp in order_responses.items()}

        order_ids_str = json.dumps(ids_dict)
        statuses_str = json.dumps(statuses_dict)

        self.cursor.execute('''
                            INSERT INTO execution_logs (timestamp, base_asset_price, vix_value, rsi_value, spread_value,
                                                        fear_greed_value, regime_detected, war_chest_before,
                                                        target_orders,
                                                        alpaca_order_ids, order_statuses)
                            VALUES (datetime('now', 'localtime'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                features.get("close", 0.0),
                                features.get("vix", 15.0),
                                features.get("rsi", 50.0),
                                features.get("spread", 2.0),
                                features.get("fear_greed", 50.0),
                                regime,
                                war_chest,
                                target_buy_str,
                                order_ids_str,
                                statuses_str
                            ))
        self.conn.commit()

    def check_if_already_run_today(self) -> bool:
        """Parses the JSON order_statuses to check if we already executed today."""
        today = datetime.now().strftime("%Y-%m-%d")

        self.cursor.execute("SELECT order_statuses FROM execution_logs WHERE timestamp LIKE ?", (f"{today}%",))
        rows = self.cursor.fetchall()

        if not rows:
            return False

        check_statuses = self.pending_statuses + ('filled', 'skipped')
        for row in rows:
            if not row[0]: continue
            try:
                statuses_dict = json.loads(row[0])
                for sym, status in statuses_dict.items():
                    if status in check_statuses:
                        return True
            except Exception:
                return True  # Failsafe: If parsing fails but a log exists, halt to prevent duplicate orders
        return False

    def get_unreconciled_orders(self) -> list:
        """Fetches pending order IDs from the JSON dictionary payload."""
        unreconciled_ids = []

        self.cursor.execute("SELECT alpaca_order_ids, order_statuses FROM execution_logs ORDER BY id DESC LIMIT 10")
        for row in self.cursor.fetchall():
            if not row[0] or not row[1]: continue

            try:
                ids_dict = json.loads(row[0])
                statuses_dict = json.loads(row[1])

                for sym, oid in ids_dict.items():
                    if oid and oid not in ["N/A", "SKIPPED", "FAILED", "SKIPPED_SELL"]:
                        status = statuses_dict.get(sym, "unknown")
                        if status in self.pending_statuses:
                            unreconciled_ids.append(oid)
            except Exception:
                pass

        return unreconciled_ids

    def update_order_status(self, order_id: str, status: str, filled_qty: float, filled_price: float):
        """Finds the JSON dictionary containing the order_id, updates it, and saves it back."""
        self.cursor.execute(
            "SELECT id, order_statuses, alpaca_order_ids FROM execution_logs WHERE alpaca_order_ids LIKE ?",
            (f'%{order_id}%',)
        )
        row = self.cursor.fetchone()

        if row:
            row_id = row[0]
            try:
                statuses_dict = json.loads(row[1])
                ids_dict = json.loads(row[2])

                for sym, oid in ids_dict.items():
                    if oid == order_id:
                        statuses_dict[sym] = status

                new_statuses_str = json.dumps(statuses_dict)

                self.cursor.execute('''
                                    UPDATE execution_logs
                                    SET order_statuses   = ?,
                                        filled_qty       = ?,
                                        filled_avg_price = ?
                                    WHERE id = ?
                                    ''', (new_statuses_str, filled_qty, filled_price, row_id))

                self.conn.commit()
                print(f"[DATABASE] Reconciled Order {order_id[:8]}... -> Final Status: {status}")

            except Exception as e:
                print(f"[DATABASE ERROR] Could not parse JSON for reconciliation: {e}")

    def get_paper_state(self) -> dict:
        """Retrieves the simulated paper account balances."""
        self.cursor.execute(
            'SELECT current_cash, current_shares, next_deposit_date FROM paper_account_state WHERE id = 1')
        row = self.cursor.fetchone()

        if row:
            return {
                "current_cash": row[0],
                "current_shares": row[1],
                "next_deposit_date": row[2]
            }
        return None

    def update_paper_state(self, current_cash: float, current_shares: float, next_deposit_date: str):
        """Overwrites the simulated paper account state."""
        self.cursor.execute('''
            INSERT OR REPLACE INTO paper_account_state 
            (id, current_cash, current_shares, next_deposit_date)
            VALUES (1, ?, ?, ?)
        ''', (current_cash, current_shares, next_deposit_date))
        self.conn.commit()

    def close(self):
        self.conn.close()