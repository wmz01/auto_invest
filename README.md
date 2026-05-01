# Automated T+1 Algorithmic Trading & Backtesting Engine

An institutional-grade, fully automated trading orchestrator and backtesting suite designed for systematic Value Accumulation and dynamic Dollar Cost Averaging (DCA). 

This project goes beyond simple retail trading scripts by implementing **Code Isomorphism**—the exact same strategy mathematical classes are evaluated in both the live execution engine and the historical backtester. It accurately models bi-weekly cash flows, accrues risk-free interest on uninvested capital, and utilizes Time-Weighted Returns (TWR) to calculate pure strategy alpha without cash-flow corruption.

## 🚀 Key Features

* **Universal Orchestrator (`main_loop.py`):** A unified execution engine triggered by `cron` that handles market-on-open (MOO) T+1 execution, idempotency locks, order reconciliation, and dynamic strategy routing.
* **Dual Execution Modes:** * **Live Mode (`--live`):** Connects to Alpaca's Live Trading API to execute real capital and automatically track incoming ACH bank transfers and monthly interest sweeps.
  * **Paper Simulation:** Bypasses Alpaca's static paper balances and uses a local SQLite database to rigorously simulate bi-weekly paycheck deposits and overnight interest accruals.
* **Code Isomorphism:** Strategies are isolated into modular classes. A strategy written once in the `strategies/` directory is seamlessly imported by both the live orchestrator and the historical backtester.
* **Macro-Aware Data Pipeline:** Automatically fetches and caches daily symbol prices (`yfinance`), the CNN Fear & Greed Index, and St. Louis FRED macroeconomic data (High Yield Spreads, Fed Funds Rate).
* **Institutional Telemetry:** Logs daily raw equity curves to SQLite and generates advanced QuantStats tearsheets (Sharpe, Sortino, Jensen's Alpha, Max Drawdown) on the fly via `metrics_dashboard.py`.
* **Discord Integration:** Real-time webhooks for daily trade reconciliation summaries, execution logs, and fatal crash alerts.

---

## 📁 Project Structure

```
AutomatedTrading/
│
├── .env                        # API keys, Discord webhooks, and Configs
├── .gitignore                  
├── requirements.txt            # Python dependencies
├── README.md                   # Project documentation
│
├── main_loop.py                # Core cron-triggered T+1 execution engine
├── broker_client.py            # Smart wrapper for Alpaca API (handles live & simulation states)
├── data_pipeline.py            # Fetches yfinance, FRED, and CNN market features
├── telemetry_db.py             # SQLite ledger for execution logs and equity curves
├── metrics_dashboard.py        # QuantStats script for advanced risk-adjusted return math
├── notifier.py                 # Discord webhook integration
├── api_sample_usages.py        # Scratchpad for testing API endpoints
│
├── strategies/                 # 🧠 Isolated Strategy Engine
│   ├── __init__.py
│   ├── base_strategy.py        # Abstract Base Class for all models
│   ├── dummy_dca.py            # Baseline: 100% blind DCA
│   ├── static_ratio_dca.py     # Baseline: Fixed ratio (e.g., 85/15)
│   ├── moving_avg_dca.py       # Valuation: Buys at a discount to 200-day SMA
│   ├── enhanced_dca.py         # Valuation: Aggressive multipliers based on ATH drawdowns
│   ├── volatility_targeting.py # Risk Parity: Targets a fixed portfolio volatility 
│   └── dynamic_regime.py       # Experimental: Multi-factor regime detection model
│
└── offline_poc/                # 🕰️ Universal Backtesting Suite
    ├── __init__.py
    ├── backtester.py           # Core time-machine engine (supports cash flows & TWR)
    ├── backtest_main.py        # Execution script to race multiple strategies
    ├── market_cache/           # Local CSV cache for historical data (bypasses rate limits)
```
---

## 🧠 Strategy Architectures

All trading logic is decoupled from execution logic. By inheriting from `BaseStrategy`, any model can be hot-swapped into the pipeline.

1. **Standard DCA (`dummy_dca.py`):** The ultimate control. Sweeps 100% of available cash into the market immediately, acting as the baseline to measure Alpha generation.
2. **Enhanced DCA (`enhanced_dca.py`):** Protects capital during bull markets but uses aggressive, tiered multipliers (e.g., 2x, 3x, 4x) when the asset drops specific percentages from its All-Time High.
3. **Moving Average DCA (`moving_avg_dca.py`):** Scales up buying power proportionally based on the percentage discount the current price has relative to its 200-day Simple Moving Average.
4. **Volatility Targeting (`volatility_targeting.py`):** Dynamically sizes portfolio exposure inversely proportional to the 20-day realized volatility. Safely executes overnight sell signals during extreme market turbulence.
5. **Dynamic Regime (`dynamic_regime.py`):** Monitors VIX, High Yield Spreads, RSI, and Fear & Greed to classify the market into `GREEDY`, `REGULAR`, or `CRISIS` regimes, dynamically shifting capital preservation and alpha multipliers.

---

## ⚙️ Installation & Setup

**1. Clone and Install**
git clone https://github.com/wmz01/AutomatedTrading.git
cd AutomatedTrading
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

**2. Environment Variables**
Create a `.env` file in the root directory. You can suffix API keys with the strategy name to cleanly separate multiple paper accounts.

# --- Strategy: Dynamic Regime ---
ALPACA_API_KEY_DYNAMIC_REGIME=your_paper_key
ALPACA_SECRET_KEY_DYNAMIC_REGIME=your_paper_secret

# --- Strategy: Baseline DCA ---
ALPACA_API_KEY_DUMMY_DCA=your_paper_key
ALPACA_SECRET_KEY_DUMMY_DCA=your_paper_secret

DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

---

## 🚦 Usage

### 1. Live Deployment (Cron)
The orchestrator relies on Python's `argparse`. You deploy strategies by passing the mapped string name to `--strategy`.

To run the paper simulation daily at 5:00 PM PT:
0 17 * * 1-5 cd /path/to/AutomatedTrading && .venv/bin/python main_loop.py --strategy dynamic_regime >> dynamic_execution.log 2>&1

To run with real money (Live Mode):
0 17 * * 1-5 cd /path/to/AutomatedTrading && .venv/bin/python main_loop.py --strategy dynamic_regime --live >> live_execution.log 2>&1

### 2. Historical Backtesting
To race your newly developed strategy against the baselines, navigate to the `offline_poc` directory and run the backtester. It will automatically compile all historical FRED/yfinance data, simulate the bi-weekly cash flows, and generate a comparative CSV matrix.

cd offline_poc
python backtest_main.py

### 3. Performance Analytics
To view institutional risk metrics (Sharpe, Calmar, Beta, Jensen's Alpha) for a live or paper account, simply run the dashboard script. It will read the local SQLite equity curve and print a tearsheet.

python metrics_dashboard.py