import argparse
import os
import sys
from dotenv import load_dotenv
import traceback
from notifier import send_discord_alert
# Import our custom isolated modules
from telemetry_db import TradingLedger
from broker_client import LiveBroker
from data_pipeline import get_today_market_features
from Strategies.dynamic_regime import DynamicRegimeStrategy
from Strategies.dummy_dca import DummyDCAStrategy
from Strategies.enhanced_dca import EnhancedDCAStrategy

# 1. The Strategy Registry
# Maps the command-line string to the actual class
STRATEGY_REGISTRY = {
    "dynamic_regime": DynamicRegimeStrategy,
    "dummy_dca": DummyDCAStrategy,
    "enhanced_dca": EnhancedDCAStrategy,
}


def main():
    # 2. Parse Command Line Arguments
    parser = argparse.ArgumentParser(description="T+1 Algorithmic Trading Orchestrator")
    parser.add_argument(
        "--strategy",
        type=str,
        required=True,
        choices=STRATEGY_REGISTRY.keys(),
        help="The name of the strategy to execute."
    )
    args = parser.parse_args()

    STRATEGY_NAME = args.strategy
    PAPER_TRADING_MODE = True
    SYMBOL = "VOO"

    print("==================================================")
    print(f" INITIATING T+1 ORCHESTRATOR: {STRATEGY_NAME.upper()} ")
    print("==================================================")

    # 3. Dynamically Load API Keys based on Strategy Name
    load_dotenv()
    env_suffix = STRATEGY_NAME.upper()  # converts "dummy_dca" to "DUMMY_DCA"

    API_KEY = os.getenv(f"ALPACA_API_KEY_{env_suffix}")
    SECRET_KEY = os.getenv(f"ALPACA_SECRET_KEY_{env_suffix}")

    if not API_KEY or not SECRET_KEY:
        error_msg = f"[FATAL ERROR] API keys for {env_suffix} not found in .env file."
        print(error_msg)
        send_discord_alert(f"🚨 **CRITICAL BOT FAILURE** 🚨\n"
                        f"**Strategy Model: {STRATEGY_NAME} **\n"
                        f"{error_msg}")
        sys.exit(1)

    # 4. Universal Configuration
    # The dummy strategy will just ignore the variables it doesn't need
    STRATEGY_CONFIG = {
        "daily_budget": 100.0,
        "target_ratio": 0.85,
        "lambda_replenish": 0.5,
        "tau": 0.02,
        "alpha_mult": 3.0,
        "beta_mult": 4.0,
        "crisis_vix_threshold": 30.0,
        "crisis_spread_threshold": 5.0,
        "crisis_fg_threshold": 15.0,
        "greedy_rsi_threshold": 75.0,
        "greedy_drawdown_threshold": -0.015,
        "greedy_fg_threshold": 60.0,
        "greedy_capital_preservation": 0.5
    }

    # Initialize Infrastructure
    ledger = TradingLedger(strategy_name=STRATEGY_NAME, paper=PAPER_TRADING_MODE)

    broker = LiveBroker(
        api_key=API_KEY,
        secret_key=SECRET_KEY,
        paper=PAPER_TRADING_MODE,
        ledger=ledger,
        daily_budget=STRATEGY_CONFIG.get("daily_budget", 100.0)
    )

    try:
        # ==========================================
        # PHASE 1: RECONCILIATION
        # ==========================================
        print("\n[PHASE 1] Reconciling previous orders...")
        unreconciled_orders = ledger.get_unreconciled_orders()
        reconciliation_summary = ""

        if not unreconciled_orders:
            reconciliation_summary = "> No pending orders to reconcile."
        else:
            for order_id in unreconciled_orders:
                details = broker.get_order_status(order_id)
                status = details['status']

                # Format the ID to make the Discord message cleaner
                short_id = order_id[:8]

                if status not in ['accepted', 'new', 'queued', 'unknown']:
                    ledger.update_order_status(
                        order_id=order_id,
                        status=status,
                        filled_qty=details['filled_qty'],
                        filled_price=details['filled_avg_price']
                    )
                    if status == 'filled':
                        # MODIFICATION: Execute paper simulation math ONLY if in paper mode
                        if PAPER_TRADING_MODE:
                            filled_qty = float(details['filled_qty'])
                            filled_price = float(details['filled_avg_price'])
                            cost_basis = filled_qty * filled_price

                            state = ledger.get_paper_state()
                            if state:
                                new_cash = state['current_cash'] - cost_basis
                                new_shares = state['current_shares'] + filled_qty
                                # Add 1 day of 5% interest on the remaining uninvested cash
                                daily_interest_rate = 0.05 / 252
                                new_cash = new_cash * (1 + daily_interest_rate)

                                ledger.update_paper_state(new_cash, new_shares, state['next_deposit_date'])

                        reconciliation_summary += f"> Order `{short_id}`: **FILLED** ({details['filled_qty']} shares @ ${details['filled_avg_price']:.2f})\n"
                    else:
                        reconciliation_summary += f"> Order `{short_id}`: **{status.upper()}**\n"
                else:
                    reconciliation_summary += f"> Order `{short_id}`: Still **{status.upper()}**\n"

        # ==========================================
        # PHASE 2: STATE & DATA INGESTION
        # ==========================================
        print("\n[PHASE 2] Ingesting State & Market Features...")
        market_data = get_today_market_features(api_key=API_KEY, secret_key=SECRET_KEY, symbol=SYMBOL)
        current_voo_price = market_data.get("close")
        account_state = broker.get_account_state(current_price=current_voo_price)

        # ==========================================
        # PHASE 3: IDEMPOTENCY CHECK
        # ==========================================
        print("\n[PHASE 3] Checking Idempotency Lock...")
        if ledger.check_if_already_run_today():
            print(" -> [HALT] Algorithm has already executed a successful pass today.")
            print(" -> Shutting down safely to prevent duplicate orders.")
            idem_msg = (f"🔴 ** Warning: why is this script executed more than once today? **\n"
                        f"**Strategy Model: {STRATEGY_NAME} **\n"
                        f"      Algorithm has already executed a successful pass today.\n"
                        f"      Shutting down safely to prevent duplicate orders.\n"
                        )
            send_discord_alert(idem_msg)
            sys.exit(0)
        print(" -> Lock clear. Proceeding to execution.")

        # ==========================================
        # PHASE 4: INFERENCE (STRATEGY MATH)
        # ==========================================
        print("\n[PHASE 4] Running Inference Engine...")

        # Dynamically instantiate the correct strategy class from the registry
        StrategyClass = STRATEGY_REGISTRY[STRATEGY_NAME]
        active_strategy = StrategyClass(config=STRATEGY_CONFIG)

        inference_result = active_strategy.calculate_order_amount(
            market_data=market_data,
            account_state=account_state
        )

        target_buy_amount = inference_result["target_buy_amount"]
        regime = inference_result["regime"]

        print(f" -> Inference Complete: Detected {regime} REGIME.")
        print(f" -> Target Buy Amount: ${target_buy_amount:,.2f}")
        # ==========================================
        # PHASE 5: EXECUTION & LOGGING
        # ==========================================
        print("\n[PHASE 5] Execution & Telemetry...")
        if target_buy_amount >= 1.00:
            order_response = broker.queue_market_on_open_buy(symbol=SYMBOL, notional_amount=target_buy_amount)
        else:
            order_response = {"order_id": "SKIPPED", "status": "skipped"}

        # Automatically fetch any ACH/Wire deposits that landed today
        todays_deposit = broker.get_todays_cash_flow()

        ledger.log_equity_snapshot(
            net_worth=account_state.get("net_worth"),
            free_cash=account_state.get("war_chest"),
            voo_price=current_voo_price,
            cash_flow=todays_deposit
        )

        ledger.log_execution(
            features=market_data,
            regime=regime,
            war_chest=account_state.get("war_chest"),
            target_buy=target_buy_amount,
            order_id=order_response["order_id"],
            status=order_response["status"]
        )

        # Build the ultimate daily dispatch message, injecting the Reconciliation string
        success_msg = (
            f"🟢 **Nightly Trading Pass Complete**\n"
            f"**Strategy Model: {STRATEGY_NAME} **\n"
            f"**1. Yesterday's Order Status:**\n"
            f"{reconciliation_summary.strip()}\n\n"
            f"**2. Tomorrow's Queued Execution:**\n"
            f"> **Symbol:** {SYMBOL}\n"
            f"> **Regime Detected:** `{regime}`\n"
            f"> **Target Order:** `${target_buy_amount:,.2f}`\n"
            f"```text\n"
            f"VOO Close:  ${market_data.get('close'):.2f}\n"
            f"VIX Value:  {market_data.get('vix'):.2f}\n"
            f"RSI Value:  {market_data.get('rsi'):.2f}\n"
            f"Spread:     {market_data.get('spread'):.2f}\n"
            f"War Chest:  ${account_state.get('war_chest'):,.2f}\n"
            f"```"
        )

        send_discord_alert(success_msg)
        print("\n[SUCCESS] Nightly trading pass complete.")

    except Exception as e:
        print(f"\n[FATAL ERROR] Unhandled exception during main loop: {e}")
        # In a full production system, you would trigger an SNS / Email / Discord alert here.
        # If ANYTHING in the script fails (internet down, Alpaca API crash, etc.)
        error_details = traceback.format_exc()
        print(f"\n[FATAL ERROR] {e}")
        error_msg = (
            f"🚨 **CRITICAL BOT FAILURE** 🚨\n"
            f"**Strategy Model: {STRATEGY_NAME} **\n"
            f"The trading engine crashed during the nightly run.\n\n"
            f"**Exception:** `{e}`\n"
            f"**Traceback:**\n"
        )
        send_discord_alert(error_msg)

        # Exit with an error code so the OS knows the cron job failed
        sys.exit(1)
    finally:
        # Always ensure the database connection is closed safely
        ledger.close()


if __name__ == "__main__":
    main()