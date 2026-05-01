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
                                date                TEXT PRIMARY KEY,
                                total_net_worth     REAL,
                                free_cash           REAL,
                                benchmark_voo_price REAL,
                                net_cash_flow       REAL DEFAULT 0.0
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

    def log_equity_snapshot(self, net_worth: float, free_cash: float, voo_price: float, cash_flow: float = 0.0):
        today = datetime.now().strftime("%Y-%m-%d")

        self.cursor.execute('''
            INSERT OR REPLACE INTO daily_equity_curve 
            (date, total_net_worth, free_cash, benchmark_voo_price, net_cash_flow)
            VALUES (?, ?, ?, ?, ?)
        ''', (today, net_worth, free_cash, voo_price, cash_flow))
        self.conn.commit()
        print(f"[DATABASE] Logged equity snapshot: Net Worth=${net_worth:,.2f} | Deposit=${cash_flow:,.2f}")

    def log_execution(self, features: dict, regime: str, war_chest: float, target_buy: float, order_id: str, status: str):
        """Pass the whole 'features' dictionary from data_pipeline to log it all cleanly."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.cursor.execute('''
            INSERT INTO execution_logs 
            (timestamp, voo_close, vix_value, rsi_value, spread_value, fear_greed_value, 
             regime_detected, war_chest_before, target_buy_amount, alpaca_order_id, order_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            now,
            features.get("close"),
            features.get("vix"),
            features.get("rsi"),
            features.get("spread"),
            features.get("fear_greed"),
            regime,
            war_chest,
            target_buy,
            order_id,
            status
        ))
        self.conn.commit()
        print(f"[DATABASE] Logged {regime} execution. VOO closed at ${features.get('close'):.2f}")

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