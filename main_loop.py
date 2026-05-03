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
from strategies.dynamic_regime import DynamicRegimeStrategy
from strategies.dummy_dca import DummyDCAStrategy
from strategies.enhanced_dca import EnhancedDCAStrategy, OverflowEDCAStrategy, FixedSplitEDCA

# 1. The Strategy Registry
STRATEGY_REGISTRY = {
    "dynamic_regime": DynamicRegimeStrategy,
    "dummy_dca": DummyDCAStrategy,
    "enhanced_dca": EnhancedDCAStrategy,
    "overflow_edca": OverflowEDCAStrategy,
    "fixed_split_edca": FixedSplitEDCA
}


def main():
    parser = argparse.ArgumentParser(description="T+1 Algorithmic Trading Orchestrator")
    parser.add_argument(
        "--strategy",
        type=str,
        required=True,
        choices=STRATEGY_REGISTRY.keys(),
        help="The name of the strategy to execute."
    )
    parser.add_argument(
        "--live_mode",
        action='store_true',
        help="Enabling live mode (in contrast to paper money)"
    )
    args = parser.parse_args()

    STRATEGY_NAME = args.strategy
    PAPER_TRADING_MODE = not args.live_mode

    print("==================================================")
    print(f" INITIATING T+1 ORCHESTRATOR: {STRATEGY_NAME.upper()} ")
    print("==================================================")

    # 3. Dynamically Load API Keys based on Strategy Name
    load_dotenv()
    env_suffix = STRATEGY_NAME.upper()
    if PAPER_TRADING_MODE:
        API_KEY = os.getenv(f"ALPACA_API_KEY_{env_suffix}")
        SECRET_KEY = os.getenv(f"ALPACA_SECRET_KEY_{env_suffix}")
    else:
        API_KEY = os.getenv("ALPACA_API_KEY_REAL_CASH")
        SECRET_KEY = os.getenv("ALPACA_SECRET_KEY_REAL_CASH")

    if not API_KEY or not SECRET_KEY:
        error_msg = f"[FATAL ERROR] API keys for {env_suffix} not found in .env file."
        print(error_msg)
        send_discord_alert(f"🚨 **CRITICAL BOT FAILURE** 🚨\n**Strategy Model: {STRATEGY_NAME} **\n{error_msg}")
        sys.exit(1)

    # 4. Universal Configuration (Upgraded for Multi-Asset)
    STRATEGY_CONFIG = {
        "daily_budget": 100.0,
        "target_ratio": 0.85,
        "base_asset": "QQQ",  # Core Asset
        "leveraged_asset": "SPY",  # Secondary/Leveraged Asset
        "weight_base": 0.60,
        "weight_lev": 0.40,
        "edca_mild_mult": 1.5,
        "edca_heavy_mult": 2.0,
        "edca_severe_mult": 3.0,
        "crisis_vix_threshold": 30.0,
        "max_lev_weight": 0.25,
        "tax_rate": 0.35
    }

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
                short_id = order_id[:8]

                if status not in ['accepted', 'new', 'queued', 'unknown']:
                    ledger.update_order_status(
                        order_id=order_id,
                        status=status,
                        filled_qty=details['filled_qty'],
                        filled_price=details['filled_avg_price']
                    )
                    if status == 'filled':
                        if PAPER_TRADING_MODE:
                            filled_qty = float(details['filled_qty'])
                            filled_price = float(details['filled_avg_price'])
                            cost_basis = filled_qty * filled_price

                            state = ledger.get_paper_state()
                            if state:
                                new_cash = state['current_cash'] - cost_basis
                                new_shares = state['current_shares'] + filled_qty
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
        base_sym = STRATEGY_CONFIG.get("base_asset", "QQQ")
        lev_sym = STRATEGY_CONFIG.get("leveraged_asset", None)

        market_data = get_today_market_features(
            api_key=API_KEY, secret_key=SECRET_KEY,
            base_symbol=base_sym, leveraged_symbol=lev_sym
        )
        current_base_price = market_data.get("close")
        # Account state no longer requires current_price because it scans Alpaca directly!
        account_state = broker.get_account_state()

        # ==========================================
        # PHASE 3: IDEMPOTENCY CHECK
        # ==========================================
        print("\n[PHASE 3] Checking Idempotency Lock...")
        if ledger.check_if_already_run_today():
            print(" -> [HALT] Algorithm has already executed a successful pass today.")
            idem_msg = (f"🔴 ** Warning: why is this script executed more than once today? **\n"
                        f"**Strategy Model: {STRATEGY_NAME} **\n"
                        f"      Algorithm has already executed a successful pass today.\n"
                        f"      Shutting down safely to prevent duplicate orders.\n")
            send_discord_alert(idem_msg)
            sys.exit(0)
        print(" -> Lock clear. Proceeding to execution.")

        # ==========================================
        # PHASE 4: INFERENCE (STRATEGY MATH)
        # ==========================================
        print("\n[PHASE 4] Running Inference Engine...")
        StrategyClass = STRATEGY_REGISTRY[STRATEGY_NAME]
        active_strategy = StrategyClass(config=STRATEGY_CONFIG)

        inference_result = active_strategy.calculate_order_amount(
            market_data=market_data,
            account_state=account_state
        )

        # Legacy Fallback Router
        regime = inference_result.get("regime_detected", inference_result.get("regime", "UNKNOWN"))
        if "target_orders" in inference_result:
            pending_orders = inference_result["target_orders"]
        else:
            # Wrap old output in the new dictionary format
            pending_orders = {base_sym: inference_result.get("target_buy_amount", 0.0)}

        print(f" -> Inference Complete: Detected {regime} REGIME.")
        # ==========================================
        # PHASE 5: EXECUTION & LOGGING
        # ==========================================
        print("\n[PHASE 5] Execution & Telemetry...")

        order_responses = {}
        for sym, target_amount in pending_orders.items():
            if target_amount >= 1.00:
                print(f" -> Queuing BUY for {sym}: ${target_amount:,.2f}")
                resp = broker.queue_market_on_open_buy(symbol=sym, notional_amount=target_amount)
                order_responses[sym] = resp

            elif target_amount <= -1.00:
                print(f" -> Queuing SELL for {sym}: ${abs(target_amount):,.2f}")
                resp = broker.queue_market_on_open_sell(symbol=sym, notional_amount=abs(target_amount))
                order_responses[sym] = resp

            else:
                order_responses[sym] = {"order_id": "SKIPPED", "status": "skipped"}
        todays_deposit = broker.get_todays_cash_flow()

        # UPDATED: Using 'base_price' instead of 'voo_price'
        ledger.log_equity_snapshot(
            net_worth=account_state.get("net_worth"),
            free_cash=account_state.get("war_chest"),
            base_price=current_base_price,
            cash_flow=todays_deposit
        )

        ledger.log_execution(
            features=market_data,
            regime=regime,
            war_chest=account_state.get("war_chest"),
            target_orders=pending_orders,
            order_responses=order_responses
        )

        # Format Discord summary for multiple assets
        order_details_str = ""
        for sym, target_amount in pending_orders.items():
            direction = "BUY" if target_amount > 0 else "SELL"
            order_details_str += f"> **{sym}:** {direction} `${abs(target_amount):,.2f}`\n"

        # UPDATED: Discord alert now dynamically prints the correct Base Asset ticker
        success_msg = (
            f"🟢 **Nightly Trading Pass Complete**\n"
            f"**Strategy Model: {STRATEGY_NAME} **\n"
            f"**1. Yesterday's Order Status:**\n"
            f"{reconciliation_summary.strip()}\n\n"
            f"**2. Tomorrow's Queued Execution:**\n"
            f"> **Regime Detected:** `{regime}`\n"
            f"{order_details_str}"
            f"```text\n"
            f"{base_sym} Close: ${current_base_price:.2f}\n"
            f"VIX Value:  {market_data.get('vix'):.2f}\n"
            f"War Chest:  ${account_state.get('war_chest'):,.2f}\n"
            f"```"
        )

        send_discord_alert(success_msg)
        print("\n[SUCCESS] Nightly trading pass complete.")

    except Exception as e:
        print(f"\n[FATAL ERROR] Unhandled exception during main loop: {e}")
        error_details = traceback.format_exc()
        send_discord_alert(
            f"🚨 **CRITICAL BOT FAILURE** 🚨\n**Strategy Model: {STRATEGY_NAME} **\nThe trading engine crashed.\n\n**Exception:** `{e}`")
        sys.exit(1)
    finally:
        ledger.close()


if __name__ == "__main__":
    main()