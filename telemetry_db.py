import sqlite3
from datetime import datetime
import os


class TradingLedger:
    def __init__(self, strategy_name: str, paper: bool = True):
        # Clean the strategy name (replace spaces with underscores, lowercase)
        clean_name = strategy_name.strip().replace(" ", "_").lower()
        mode = "paper" if paper else "live"

        # Dynamically route to the correct database file
        db_name = f"{clean_name}_{mode}.db"

        self.conn = sqlite3.connect(db_name)
        self.cursor = self.conn.cursor()
        self._create_table()

        self.pending_statuses = (
            'new', 'accepted', 'pending_new', 'accepted_for_bidding',
            'held', 'queued', 'partially_filled'
        )
    def _create_table(self):
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS execution_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                
                -- State of the World
                voo_close REAL,
                vix_value REAL,
                rsi_value REAL,
                spread_value REAL,
                fear_greed_value REAL,
                
                -- The Brain
                regime_detected TEXT,
                war_chest_before REAL,
                
                -- The Action
                target_buy_amount REAL,
                alpaca_order_id TEXT,
                order_status TEXT,
                
                -- Reconciliation (Filled Tomorrow)
                filled_qty REAL,
                filled_avg_price REAL
            )
        ''')
        # Add the new Equity Curve table
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
        from datetime import datetime  # Just in case it's not imported at the top
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
        """
        Safely serializes multi-asset order routing into JSON strings for database insertion.
        """
        # Serialize the dictionaries to strings so they fit in standard TEXT columns
        target_buy_str = json.dumps(target_orders)

        # Extract IDs and Statuses from the complex response dictionary
        ids_dict = {sym: resp.get("order_id", "N/A") for sym, resp in order_responses.items()}
        statuses_dict = {sym: resp.get("status", "N/A") for sym, resp in order_responses.items()}

        order_ids_str = json.dumps(ids_dict)
        statuses_str = json.dumps(statuses_dict)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                           INSERT INTO executions (date, close_price, vix, spread, rsi, fear_greed,
                                                   regime, war_chest, target_buy, order_id, status)
                           VALUES (DATE('now', 'localtime'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ''', (
                               features.get("close", 0.0),
                               features.get("vix", 15.0),
                               features.get("spread", 2.0),
                               features.get("rsi", 50.0),
                               features.get("fear_greed", 50.0),
                               regime,
                               war_chest,
                               target_buy_str,  # Now a JSON string (e.g., '{"QQQ": 60, "SPY": 40}')
                               order_ids_str,  # Now a JSON string
                               statuses_str  # Now a JSON string
                           ))
            conn.commit()
    def check_if_already_run_today(self) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")

        # Include 'filled' because if an order was filled instantly, we still don't want to run again.
        check_statuses = self.pending_statuses + ('filled',)
        placeholders = ','.join(['?'] * len(check_statuses))

        query = f'''
            SELECT COUNT(*) FROM execution_logs 
            WHERE timestamp LIKE ? AND order_status IN ({placeholders})
        '''

        # Pass the date wildcard as the first argument, followed by the unpacked tuple
        self.cursor.execute(query, (f"{today}%", *check_statuses))
        count = self.cursor.fetchone()[0]
        return count > 0

    def get_unreconciled_orders(self) -> list:
        placeholders = ','.join(['?'] * len(self.pending_statuses))
        query = f'''
            SELECT alpaca_order_id FROM execution_logs 
            WHERE order_status IN ({placeholders})
        '''

        self.cursor.execute(query, self.pending_statuses)
        return [row[0] for row in self.cursor.fetchall() if row[0] not in ("SKIPPED", "FAILED")]

    def update_order_status(self, order_id: str, status: str, filled_qty: float, filled_price: float):
        self.cursor.execute('''
                            UPDATE execution_logs
                            SET order_status     = ?,
                                filled_qty       = ?,
                                filled_avg_price = ?
                            WHERE alpaca_order_id = ?
                            ''', (status, filled_qty, filled_price, order_id))
        self.conn.commit()
        print(f"[DATABASE] Reconciled Order {order_id} -> Final Status: {status}")

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
        # Returns None if the table is completely empty (e.g., Day 1 of the simulation)
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