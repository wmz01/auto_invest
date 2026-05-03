import os

import pandas as pd
from strategies.dummy_dca import DummyDCAStrategy
from strategies.dynamic_regime import DynamicRegimeStrategy
from strategies.fixed_split_baseline import FixedSplitStrategy
from strategies.static_ratio_dca import StaticRatioDCAStrategy
from strategies.volatility_targeting import VolatilityTargetingStrategy
from strategies.enhanced_dca import EnhancedDCAStrategy, OverflowEDCAStrategy, FixedSplitEDCA
from strategies.moving_avg_dca import MovingAverageDCAStrategy
from strategies.zscore_leverage import ZScoreMarginStrategy, ZScoreBaseStrategy, FlowScaledZScoreStrategy
from strategies.dynamic_rebalance import DynamicRebalanceEDCA
from backtester import ProfessionalBacktester


def save_results_to_csv(results_dict: dict, filename: str = "backtest_summary.csv"):
    rows = []
    for strategy_name, metrics in results_dict.items():
        if not metrics:
            rows.append({"Strategy": strategy_name, "Status": "FAILED/EMPTY"})
            continue
        row = {"Strategy": strategy_name}
        row.update(metrics)
        rows.append(row)

    df = pd.DataFrame(rows).fillna("N/A")
    os.makedirs(os.path.dirname(filename) if os.path.dirname(filename) else '.', exist_ok=True)
    df.to_csv(filename, index=False)
    print(f"\n[+] Successfully saved {len(rows)} strategy results to '{filename}'")


def print_report(title: str, results: dict):
    if not results: return
    print(f"\n==================================================")
    print(f" {title} ")
    print(f"==================================================")
    print(f"Total Cash Injected    : ${results.get('total_cash_injected', 0):,.2f}")
    print(f"Final Net Worth        : ${results.get('final_net_worth', 0):,.2f}")
    print(f"  -> Shares Value      : ${results.get('final_shares_value', 0):,.2f}")
    print(f"  -> Cash Remaining    : ${results.get('final_cash_remaining', 0):,.2f}")
    print(f"  -> Interest Earned   : ${results.get('total_interest_earned', 0):,.2f}")
    print(f"--------------------------------------------------")
    print(f"Net Worth CAGR         : {results.get('net_worth_cagr_pct', 0)}% / yr")
    print(f"Invested Capital CAGR  : {results.get('invested_capital_cagr_pct', 0)}% / yr")
    print(f"Time-Weighted CAGR     : {results.get('twr_cagr_pct', 0)}% / yr")
    print(f"--------------------------------------------------")
    print(f"Strategy Beta          : {results.get('beta', 0)}")
    print(f"Jensen's Alpha (CAPM)  : {results.get('jensens_alpha_pct', 0)}%")
    print(f"Treynor Ratio          : {results.get('treynor', 0)}")
    print(f"--------------------------------------------------")
    print(f"Max Drawdown (MDD)     : {results.get('mdd_pct', 0)}%")
    print(f"Time to Recovery       : {results.get('max_recovery_days', 0)} days")
    print(f"Sharpe Ratio           : {results.get('sharpe', 0)}")
    print(f"Sortino Ratio          : {results.get('sortino', 0)}")
    print(f"Calmar Ratio           : {results.get('calmar', 0)}")


# ============================================================
# EXECUTION
# ============================================================
if __name__ == "__main__":

    symbol = "SPY"
    leverage_asset = "TQQQ"
    sim_start = "2016-01-01"
    sim_end = None

    backtester = ProfessionalBacktester(daily_cash_flow=100.0)

    # Pre-fetch every ticker any of your strategies might need
    backtester.prepare_historical_data(
        symbols=["QQQ", "SPY", "VGT", "VOO", "TQQQ"],
        start_date=sim_start,
        end_date=sim_end
    )

    # 1. Universal Config for custom strategies
    config = {
        "tax_rate": 0.35,
        "daily_budget": 100.0,
        "target_ratio": 0.8,
        "lambda_replenish": 0.3,
        "tau": 0.02,
        "alpha_mult": 3.0,
        "beta_mult": 4.0,
        "crisis_vix_threshold": 30.0,
        "crisis_spread_threshold": 5.0,
        "crisis_fg_threshold": 15.0,
        "greedy_rsi_threshold": 75.0,
        "greedy_drawdown_threshold": -0.015,
        "greedy_fg_threshold": 60.0,
        "greedy_capital_preservation": 0.5,
        # volatility targeting strategy config
        "target_vol": 0.15,
        # enhanced dca config
        "edca_mild_mult": 1.5,
        "edca_heavy_mult": 2.0,
        "edca_severe_mult": 3.0,
        # moving avg dca config
        "ma_aggressiveness": 3.0,
        # Z-Score Leverage config
        "lookback_window": 50,  # Dynamic MA/Z-Score window to use
        "start_z": -1.5,  # Start scaling into TQQQ here
        "max_z": -3.0,  # 100% TQQQ here
        "base_asset": symbol,
        "leveraged_asset": leverage_asset
    }

    # 2. Instantiate your LIVE strategy files
    dummy_strategy = DummyDCAStrategy(config)
    static_ratio_strategy = StaticRatioDCAStrategy(config)
    vol_target_strategy = VolatilityTargetingStrategy(config)
    dynamic_strategy = DynamicRegimeStrategy(config)
    edca_strategy = EnhancedDCAStrategy(config)
    ma_strategy = MovingAverageDCAStrategy(config)
    zscore_strategy = ZScoreBaseStrategy(config)
    overflow_strategy = OverflowEDCAStrategy(config)
    rebalance_strategy = DynamicRebalanceEDCA(config)

    config = {
        "base_asset": "QQQ",  # The backtester will buy this
        "leveraged_asset": "SPY",  # The backtester will buy this
        "weight_base": 0.60,  # Allocates $60/day
        "weight_lev": 0.40,  # Allocates $40/day
    }
    fixed_strategy = FixedSplitStrategy(config)
    fixed_edca_strategy = FixedSplitEDCA(config)

    # 4. Run through the engine
    edca_results, _ = backtester.run_custom_strategy(edca_strategy)
    fixed_split_results, _ = backtester.run_custom_strategy(fixed_strategy)
    fixed_edca_results, _ = backtester.run_custom_strategy(fixed_edca_strategy)
    ma_results, _ = backtester.run_custom_strategy(ma_strategy)
    dummy_results, _ = backtester.run_custom_strategy(dummy_strategy)
    static_ratio_results, _ = backtester.run_custom_strategy(static_ratio_strategy)
    vol_results, _ = backtester.run_custom_strategy(vol_target_strategy)
    dynamic_results, _ = backtester.run_custom_strategy(dynamic_strategy)
    zscore_results, _ = backtester.run_custom_strategy(zscore_strategy)
    overflow_results, _ = backtester.run_custom_strategy(overflow_strategy)
    rebalance_results, _ = backtester.run_custom_strategy(rebalance_strategy)

    all_results = {
        "CONTROL 1: DUMMY ISO CLASS": dummy_results,
        "CONTROL 2: STATIC RATIO ISO CLASS": static_ratio_results,
        "CONTROL 3: FIXED SPLIT BASELINE": fixed_split_results,
        "CONTROL 4: VOLATILITY TARGETING ISO": vol_results,
        "CONTROL 5: ENHANCED DCA": edca_results,
        "CONTROL 6: FIXED SPLIT EDCA": fixed_edca_results,
        # "CONTROL 6: MOVING AVERAGE DCA": ma_results,
        # "EXPERIMENTAL: DYNAMIC REGIME ISO CLASS": dynamic_results,
        # "EXPERIMENTAL 2: Z-SCORE CONVEXITY": zscore_results,
        "EXPERIMENTAL 3: OVERFLOW TQQQ": overflow_results,
        "EXPERIMENTAL 4: DYNAMIC REBALANCING": rebalance_results
    }

    for strategy_name, result_metrics in all_results.items():
        print_report(strategy_name, result_metrics)

    save_results_to_csv(all_results,
                        filename=f"./backtest_summary/backtest_summary_{symbol}_{sim_start}_to_{sim_end}.csv")