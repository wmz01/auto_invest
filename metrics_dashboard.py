import sqlite3
import pandas as pd
import quantstats as qs


def calculate_performance_metrics(db_path: str = "dynamic_regime_paper.db"):
    print(f"Loading data from {db_path}...")

    # 1. Connect and Extract
    try:
        conn = sqlite3.connect(db_path)
        df = pd.read_sql_query("SELECT * FROM daily_equity_curve ORDER BY date ASC", conn)
        conn.close()
    except Exception as e:
        print(f"Failed to load database: {e}")
        return

    if len(df) < 2:
        print("Not enough data to calculate metrics. Need at least 2 days of trading history.")
        return

    # 2. Format DataFrame for QuantStats
    # QuantStats expects a Pandas Series with a DatetimeIndex
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)

    # 3. Calculate Daily Returns (Using Time-Weighted Return logic)

    # Get previous day's net worth
    prev_nw = df['total_net_worth'].shift(1)
    cf = df['net_cash_flow']
    current_nw = df['total_net_worth']

    # TWR Formula: R = (Current - (Prev + CF)) / (Prev + CF)
    strategy_returns = (current_nw - (prev_nw + cf)) / (prev_nw + cf)
    strategy_returns = strategy_returns.dropna()

    # Benchmark returns remain a simple percentage change
    benchmark_returns = df['benchmark_voo_price'].pct_change().dropna()

    # Align indexes in case of any data gaps
    strategy_returns, benchmark_returns = strategy_returns.align(benchmark_returns, join='inner')

    print("\n==================================================")
    print(" LIVE PERFORMANCE METRICS (SINCE INCEPTION)")
    print("==================================================")
    print(f"Total Trading Days Tracked: {len(strategy_returns)}")
    print(f"Current Net Worth: ${df['total_net_worth'].iloc[-1]:,.2f}")
    print(f"Current Cash Drag: ${df['free_cash'].iloc[-1]:,.2f}\n")

    # 4. Calculate Risk-Adjusted Metrics using QuantStats
    # Annualization factor is 252 for daily trading days
    try:
        sharpe = qs.stats.sharpe(strategy_returns, periods=252)
        sortino = qs.stats.sortino(strategy_returns, periods=252)
        calmar = qs.stats.calmar(strategy_returns)
        max_dd = qs.stats.max_drawdown(strategy_returns)
        cagr = qs.stats.cagr(strategy_returns)

        # Relative metrics (Requires Benchmark)
        beta = qs.stats.greeks.beta(strategy_returns, benchmark_returns)
        alpha = qs.stats.greeks.alpha(strategy_returns, benchmark_returns)  # Jensen's Alpha
        treynor = qs.stats.treynor_ratio(strategy_returns, benchmark_returns, periods=252)

        print(f"CAGR:              {cagr * 100:.2f}%")
        print(f"Max Drawdown:      {max_dd * 100:.2f}%")
        print(f"Sharpe Ratio:      {sharpe:.2f}")
        print(f"Sortino Ratio:     {sortino:.2f}")
        print(f"Calmar Ratio:      {calmar:.2f}")
        print("-" * 30)
        print(f"Beta (vs VOO):     {beta:.2f}")
        print(f"Jensen's Alpha:    {alpha * 100:.2f}%")
        print(f"Treynor Ratio:     {treynor:.4f}")

    except Exception as e:
        print(f"Warning: Not enough variance to calculate all metrics yet. Let the bot run longer. (Error: {e})")

    # 5. Optional: Generate HTML Tearsheet
    # This will create a beautiful, institutional-grade PDF/HTML report in your folder
    print("\nGenerating comprehensive HTML tear sheet...")
    qs.reports.html(strategy_returns, benchmark=benchmark_returns, output='strategy_tearsheet.html',
                    title="Dynamic Regime Algorithm Performance")
    print("Saved as 'strategy_tearsheet.html'. Open this file in your web browser.")


if __name__ == "__main__":
    # You can pass the specific database name here if tracking multiple strategies
    calculate_performance_metrics("dynamic_regime_paper.db")