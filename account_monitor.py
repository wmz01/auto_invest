import os
import requests
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus


class RealCashMonitor:
    def __init__(self):
        load_dotenv()

        # Explicitly pull the master real-money keys
        self.api_key = os.getenv("ALPACA_API_KEY_REAL_CASH")
        self.secret_key = os.getenv("ALPACA_SECRET_KEY_REAL_CASH")
        self.webhook_url = os.getenv("DISCORD_WEBHOOK")

        if not self.api_key or not self.secret_key:
            raise ValueError("CRITICAL: Missing REAL_CASH API keys in .env.")

        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Booting Real Cash Monitor...")

        # paper=False guarantees we are looking at the live B/D account
        self.client = TradingClient(api_key=self.api_key, secret_key=self.secret_key, paper=False)

    def fetch_account_state(self):
        print(" -> Fetching global account state...")
        account = self.client.get_account()
        positions = self.client.get_all_positions()

        net_worth = float(account.portfolio_value)

        # For cash accounts, cash is usually non_marginable_buying_power or cash.
        # We check both to be safe depending on your exact Alpaca account tier.
        cash = float(account.non_marginable_buying_power) if float(account.non_marginable_buying_power) > 0 else float(
            account.cash)

        holdings = []
        for p in positions:
            holdings.append(
                f"**{p.symbol}**: {p.qty} shares | Market Val: ${float(p.market_value):,.2f} | "
                f"Unrealized: ${float(p.unrealized_pl):,.2f} ({(float(p.unrealized_plpc) * 100):.2f}%)"
            )

        return net_worth, cash, holdings

    def fetch_24h_orders(self):
        print(" -> Fetching last 24h of order activity...")
        # We query ALL orders to catch fills, cancels, and rejections
        req = GetOrdersRequest(
            status=QueryOrderStatus.ALL,
            limit=50
        )
        orders = self.client.get_orders(req)

        yesterday = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_orders = []

        for order in orders:
            if order.updated_at and order.updated_at > yesterday:
                status_str = str(order.status.value).upper() if hasattr(order.status, 'value') else str(
                    order.status).upper()

                # Format differently based on whether it actually filled
                if status_str == "FILLED":
                    icon = "✅"
                    details = f"Filled {order.filled_qty} @ ${float(order.filled_avg_price):,.2f}"
                elif status_str in ["CANCELED", "REJECTED", "EXPIRED"]:
                    icon = "❌"
                    details = f"Status: {status_str}"
                else:
                    icon = "⏳"
                    details = f"Status: {status_str} (Pending)"

                recent_orders.append(
                    f"{icon} **{order.side.name} {order.symbol}**\n"
                    f"{details}\n"
                    f"*Updated: {order.updated_at.strftime('%Y-%m-%d %H:%M:%S')} UTC*"
                )

        return recent_orders

    def send_discord_report(self, net_worth, cash, holdings, recent_orders):
        print(" -> Transmitting Global Risk Report to Discord...")
        if not self.webhook_url:
            print(" -> [WARNING] No Discord Webhook URL found.")
            return

        # Institutional Blue for the master account summary
        embed_color = 0x3498db

        embed = {
            "title": "🌅 Morning Trade Reconciliation",
            "description": "**Status:** Live Market Data Sync",
            "color": embed_color,
            "fields": [
                {
                    "name": "💵 Total Liquidity & Equity",
                    "value": f"**Net Worth:** ${net_worth:,.2f}\n**Available Cash:** ${cash:,.2f}",
                    "inline": False
                },
                {
                    "name": "📦 Current Holdings",
                    "value": "\n".join(holdings) if holdings else "No active positions.",
                    "inline": False
                },
                {
                    "name": "⚡ Global Order Flow (Last 24h)",
                    "value": "\n\n".join(
                        recent_orders) if recent_orders else "No trading activity in the last 24 hours.",
                    "inline": False
                }
            ],
            "footer": {
                "text": f"Executive Summary • {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            }
        }

        try:
            response = requests.post(self.webhook_url, json={"embeds": [embed]})
            response.raise_for_status()
            print(" -> [SUCCESS] Report sent.")
        except Exception as e:
            print(f" -> [ERROR] Failed to send Discord message: {e}")

    def run(self):
        try:
            net_worth, cash, holdings = self.fetch_account_state()
            recent_orders = self.fetch_24h_orders()
            self.send_discord_report(net_worth, cash, holdings, recent_orders)
        except Exception as e:
            import traceback
            print(f"[FATAL ERROR] Master Monitor crashed: {e}")
            traceback.print_exc()
            if hasattr(self, 'webhook_url') and self.webhook_url:
                requests.post(self.webhook_url, json={"content": f"🚨 **GLOBAL MONITOR FAILURE**\n`{e}`"})


if __name__ == "__main__":
    monitor = RealCashMonitor()
    monitor.run()