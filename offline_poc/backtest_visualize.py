import os
import pandas as pd
import matplotlib.pyplot as plt
import yfinance as yf
from backtester import ProfessionalBacktester
from strategies.dummy_dca import DummyDCAStrategy
from strategies.enhanced_dca import OverflowEDCAStrategy, FixedSplitEDCA
from strategies.dynamic_rebalance import DynamicRebalanceEDCA
from strategies.fixed_split_baseline import FixedSplitStrategy


def print_final_state(strategy_name: str, metrics: dict, config: dict):
    base_sym = config.get("base_asset", "Base")
    lev_sym = config.get("leveraged_asset", "Leveraged")

    print(f"\n=== {strategy_name} Final State ===")
    print(f"Total Cash Injected : ${metrics.get('total_cash_injected', 0):,.2f}")
    print(f"Final Net Worth     : ${metrics.get('final_net_worth', 0):,.2f}")
    print(f"Cash (War Chest)    : ${metrics.get('final_cash_remaining', 0):,.2f}")
    print(f"Base Shares ({base_sym}) : {metrics.get('final_base_shares', 0):,.2f} shares")
    if 'final_lev_shares' in metrics:
        print(f"Lev Shares ({lev_sym}) : {metrics.get('final_lev_shares', 0):,.2f} shares")
    print(f"Cumulative Return   : {metrics.get('twr_cagr_pct', 0)}% CAGR")
    print(f"Max Drawdown        : {metrics.get('mdd_pct', 0)}%")
    print(f"Strategy Beta        : {100*metrics.get('beta', 0)}%")
    print(f"Jensen's Alpha      : {metrics.get('jensens_alpha_pct', 0)}%")


def plot_backtest_results(baseline_df: pd.DataFrame, strategy_df: pd.DataFrame, config: dict):
    base_sym = config.get("base_asset", "Base")
    lev_sym = config.get("leveraged_asset", "Leveraged")

    # 1. Determine Resampling Frequency (Weekly if < 2 years, else Monthly)
    total_days = len(strategy_df)
    resample_freq = 'W' if total_days < 504 else 'ME'

    # Resample taking the LAST observation of the period
    base_resampled = baseline_df.resample(resample_freq).last()
    strat_resampled = strategy_df.resample(resample_freq).last()

    # Calculate Percentage Gains for the Portfolios (DCA Math)
    strat_gain = ((strat_resampled['net_worth'] - strat_resampled['total_injected']) / strat_resampled[
        'total_injected'].clip(lower=1)) * 100
    base_dca_gain = ((base_resampled['net_worth'] - base_resampled['total_injected']) / base_resampled[
        'total_injected'].clip(lower=1)) * 100

    # --- FIX: ALWAYS EXPLICITLY LOAD PURE SPY AND QQQ ---
    def get_index_gain(ticker):
        cache_path = f"./market_cache/{ticker}_price_data.csv"
        # 1. Try to read from your offline cache first
        if os.path.exists(cache_path):
            df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
        else:
            # 2. Fallback to web if cache is missing
            try:
                print(f"[WEB] Plotter fetching {ticker} to construct baseline...")
                df = yf.Ticker(ticker).history(period="max")
            except Exception:
                return pd.Series(0, index=strat_resampled.index)

        # Clean and align the external data exactly to our backtest timeline
        df.index = df.index.tz_localize(None).normalize()
        df = df[~df.index.duplicated(keep='first')]
        df = df.reindex(strat_resampled.index, method='ffill')

        # Calculate pure buy-and-hold gain
        return ((df['Close'] - df['Close'].iloc[0]) / df['Close'].iloc[0]) * 100

    sp500_gain = get_index_gain("SPY")
    nasdaq_gain = get_index_gain("QQQ")

    # 2. Setup the Plotting Grid
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10), gridspec_kw={'height_ratios': [2, 1]})
    plt.subplots_adjust(hspace=0.3)

    # --- PLOT 1: PERFORMANCE COMPARISON ---
    ax1.set_title(f"Cumulative Profit (%) vs Benchmarks ({base_sym} / {lev_sym})", fontsize=14, fontweight='bold')

    # The active portfolios
    ax1.plot(strat_gain.index, strat_gain, label=f"Overflow EDCA Strategy", color='purple', linewidth=2.5)
    ax1.plot(base_dca_gain.index, base_dca_gain, label=f"Baseline DCA ({base_sym})", color='blue', linestyle='--',
             linewidth=1.5)

    # The pure un-managed indices
    ax1.plot(sp500_gain.index, sp500_gain, label="S&P 500 (SPY)", color='gray', alpha=0.6)
    ax1.plot(nasdaq_gain.index, nasdaq_gain, label="Nasdaq 100 (QQQ)", color='orange', alpha=0.6)

    ax1.set_ylabel("Cumulative Gain (%)")
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="upper left")

    # --- PLOT 2: ALLOCATION PERCENTAGES (100% Stacked Area) ---
    pct_base = (strat_resampled['base_value'] / strat_resampled['net_worth']) * 100
    pct_lev = (strat_resampled['lev_value'] / strat_resampled['net_worth']) * 100
    pct_cash = (strat_resampled['war_chest'] / strat_resampled['net_worth']) * 100

    ax2.set_title("Strategy Portfolio Allocation (%)", fontsize=14, fontweight='bold')
    ax2.stackplot(strat_resampled.index,
                  pct_base, pct_lev, pct_cash,
                  labels=[f'Base Asset ({base_sym})', f'Leveraged Asset ({lev_sym})', 'Cash (War Chest)'],
                  colors=['#1f77b4', '#ff7f0e', '#2ca02c'],
                  alpha=0.8)

    ax2.set_ylabel("Allocation (%)")
    ax2.set_ylim(0, 100)
    ax2.margins(x=0)
    ax2.legend(loc="lower left")

    plt.show()


# ============================================================
# EXECUTION
# ============================================================
if __name__ == "__main__":
    BASE_TICKER = "SPY"
    LEV_TICKER = "QQQ"
    sim_start = "2016-01-01"
    sim_end = "2025-07-15"

    backtester = ProfessionalBacktester(daily_cash_flow=100.0)

    # Pre-fetch every ticker any of your strategies might need
    backtester.prepare_historical_data(
        symbols=["QQQ", "SPY", "VGT", "VOO", "TQQQ"],
        start_date=sim_start,
        end_date=sim_end
    )
    config = {
        "daily_budget": 100.0,
        "target_ratio": 0.8,
        "base_asset": "TQQQ",  # The backtester will buy this
        "leveraged_asset": "SPY",  # The backtester will buy this
        "weight_base": 0.2,  # Allocates $60/day
        "weight_lev": 0.65,  # Allocates $40/day
    }

    # 1. Instantiate Strategies
    # baseline_strategy = DummyDCAStrategy(config)
    baseline_strategy = FixedSplitEDCA(config)

    config = {
        "tax_rate": 0.35,
        "daily_budget": 100.0,
        "target_ratio": 0.8,
        "base_asset": BASE_TICKER,
        "leveraged_asset": LEV_TICKER,
        "edca_mild_mult": 1.5,
        "edca_heavy_mult": 2.0,
        "edca_severe_mult": 3.0,
    }
    experiment_strategy = DynamicRebalanceEDCA(config)
    # experiment_strategy = OverflowEDCAStrategy(config)

    # 2. Run Backtests
    print(f"\nRunning Baseline Strategy...")
    base_metrics, base_df = backtester.run_custom_strategy(baseline_strategy)

    print(f"Running Experiment Strategy...")
    strat_metrics, strat_df = backtester.run_custom_strategy(experiment_strategy)

    # 3. Print Final End States
    print_final_state(f"BASELINE ", base_metrics, config)
    print_final_state(f"OVERFLOW STRATEGY", strat_metrics, config)

    # 4. Generate Visualizations
    print("\nGenerating Visualizations...")
    plot_backtest_results(base_df, strat_df, config)