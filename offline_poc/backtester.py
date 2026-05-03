import os
import io
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from random import choice
import pandas_datareader.data as web

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.67 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_4) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.67 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.67 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:100.0) Gecko/20100101 Firefox/100.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12.4; rv:100.0) Gecko/20100101 Firefox/100.0",
]


class ProfessionalBacktester:
    def __init__(self, ticker: str = "VOO", leveraged_ticker: str = None, daily_cash_flow: float = 100.0,
                 risk_free_rate: float = 0.042):
        self.ticker = ticker
        self.leveraged_ticker = leveraged_ticker
        self.benchmark_ticker = "SPY"
        self.daily_cash_flow = daily_cash_flow
        self.biweekly_injection = daily_cash_flow * 10  # 10 trading days per 2 weeks
        self.risk_free_rate = risk_free_rate
        self.data = None
        self.tax_rate = 0.4

    def _get_latest_market_date(self) -> pd.Timestamp:
        try:
            recent = yf.Ticker(self.ticker).history(period="5d")
            return recent.index[-1].tz_localize(None).normalize()
        except Exception:
            return pd.Timestamp.today().normalize()

    def fetch_cnn_fear_greed(self) -> pd.Series:
        print("Fetching CNN Fear & Greed Index...")
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {"User-Agent": choice(USER_AGENTS)}
        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()['fear_and_greed_historical']['data']
            df = pd.DataFrame(data)
            df['Date'] = pd.to_datetime(df['x'], unit='ms').dt.normalize()
            return df.set_index('Date')['y'].rename('fear_greed')
        except Exception as e:
            print(f"[WARNING] CNN Fear & Greed fetch failed: {e}. Defaulting to Neutral (50).")
            return pd.Series(dtype=float, name='fear_greed')

    def fetch_fred_high_yield_spread(self) -> pd.Series:
        print("Fetching FRED High Yield Spread via pandas-datareader...")
        try:
            # Fetches data from 1990 to today automatically
            df = web.DataReader('BAMLH0A0HYM2', 'fred', start='1990-01-01')
            return df['BAMLH0A0HYM2'].astype(float).rename('spread')
        except Exception as e:
            print(f"[WARNING] FRED Spread fetch failed: {e}. Defaulting to 4.0.")
            return pd.Series(dtype=float, name='spread')

    def fetch_fred_federal_funds_rate(self) -> pd.Series:
        print("Fetching FRED Federal Funds Rate (DFF) via pandas-datareader...")
        try:
            df = web.DataReader('DFF', 'fred', start='1990-01-01')
            return df['DFF'].astype(float).rename('fed_funds_rate')
        except Exception as e:
            print(f"[WARNING] FRED DFF fetch failed: {e}. Defaulting to 2.0%.")
            return pd.Series(dtype=float, name='fed_funds_rate')

    def prepare_historical_data(self, start_date: str, end_date: str = None, force_fetch: bool = False):
        cache_dir = "market_cache"
        os.makedirs(cache_dir, exist_ok=True)

        macro_cache_file = os.path.join(cache_dir, "macro_data.csv")

        latest_market_date = self._get_latest_market_date()
        target_end_date = pd.to_datetime(end_date) if end_date else latest_market_date
        required_freshness = min(latest_market_date, target_end_date)

        macro_df = pd.DataFrame()
        fetch_macro = True
        overlap_days = 5

        # --- MACRO DATA ---
        if os.path.exists(macro_cache_file):
            macro_df = pd.read_csv(macro_cache_file, index_col=0, parse_dates=True)
            if not macro_df.empty and macro_df.index.max() >= required_freshness:
                fetch_macro = False
                print(f"[CACHE HIT] Macro Data up-to-date.")

        if fetch_macro or force_fetch:
            print("[FETCHING] Downloading fresh Macro Data...")
            if not macro_df.empty:
                fetch_start = macro_df.index.max() - pd.Timedelta(days=overlap_days)
                vix = yf.Ticker("^VIX").history(start=fetch_start.strftime('%Y-%m-%d'))
            else:
                vix = yf.Ticker("^VIX").history(period="max")

            vix.index = vix.index.tz_localize(None).normalize()
            new_macro = vix[['Close']].rename(columns={'Close': 'vix'})

            fg_series = self.fetch_cnn_fear_greed()
            spread_series = self.fetch_fred_high_yield_spread()
            ffr_series = self.fetch_fred_federal_funds_rate()

            new_macro = new_macro.join(fg_series).join(spread_series).join(ffr_series)

            if not macro_df.empty:
                macro_df = pd.concat([macro_df[macro_df.index < fetch_start], new_macro])
            else:
                macro_df = new_macro

            macro_df['vix'] = macro_df['vix'].ffill().fillna(15.0)
            macro_df['fear_greed'] = macro_df['fear_greed'].ffill().fillna(50.0)
            macro_df['spread'] = macro_df['spread'].ffill().fillna(4.0)
            macro_df['fed_funds_rate'] = macro_df['fed_funds_rate'].ffill().fillna(2.0)

            macro_df.to_csv(macro_cache_file)

        # --- SYMBOL DATA (Decoupled Architecture) ---
        # 1. Fetch Primary Asset
        base_df = self._get_symbol_data(self.ticker, required_freshness, force_fetch)
        if base_df.empty:
            raise ValueError(f"Failed to load primary asset {self.ticker}")

        # 2. Fetch Leveraged Asset
        if hasattr(self, 'leveraged_ticker') and self.leveraged_ticker:
            lev_df = self._get_symbol_data(self.leveraged_ticker, required_freshness, force_fetch)
            if not lev_df.empty:
                base_df['lev_Open'] = lev_df['Open']
                base_df['lev_Close'] = lev_df['Close']

        # 3. Fetch Benchmark Asset
        if hasattr(self, 'benchmark_ticker') and self.benchmark_ticker:
            bench_df = self._get_symbol_data(self.benchmark_ticker, required_freshness, force_fetch)
            if not bench_df.empty:
                base_df['bench_Close'] = bench_df['Close']
            else:
                base_df['bench_Close'] = base_df['Close']  # Safe fallback
        else:
            base_df['bench_Close'] = base_df['Close']  # Safe fallback

        # --- MERGE & SLICE ---
        df = base_df.join(macro_df).dropna(subset=['Close']).copy()
        mask = (df.index >= pd.to_datetime(start_date))
        if end_date:
            mask = mask & (df.index <= pd.to_datetime(end_date))

        self.data = df.loc[mask].copy()
        if self.data.empty:
            raise ValueError("Simulation window returned no data. Check your dates.")

        print(f"Loaded {len(self.data)} active trading days for the backtest.")

    def _get_symbol_data(self, symbol: str, required_freshness: pd.Timestamp,
                         force_fetch: bool = False) -> pd.DataFrame:
        """
        Universally fetches, caches, and calculates metrics for ANY given symbol.
        Treats every asset as a standalone entity to prevent cache corruption.
        """
        if not symbol: return pd.DataFrame()

        cache_dir = "market_cache"
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"{symbol}_price_data.csv")

        symbol_df = pd.DataFrame()
        fetch_symbol = True
        overlap_days = 5

        # 1. Check existing isolated cache
        if os.path.exists(cache_file):
            symbol_df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            if not symbol_df.empty and 'Open' in symbol_df.columns and symbol_df.index.max() >= required_freshness:
                fetch_symbol = False
                print(f"[CACHE HIT] Symbol Data for {symbol} is up-to-date.")

        # 2. Fetch from Yahoo Finance if missing or stale
        if fetch_symbol or force_fetch:
            print(f"[FETCHING] Downloading fresh data for {symbol}...")
            asset = yf.Ticker(symbol)
            if not symbol_df.empty and 'Open' in symbol_df.columns:
                fetch_start = symbol_df.index.max() - pd.Timedelta(days=overlap_days)
                new_symbol = asset.history(start=fetch_start.strftime('%Y-%m-%d'))
                new_symbol.index = new_symbol.index.tz_localize(None).normalize()
                symbol_df = pd.concat(
                    [symbol_df[['Open', 'Close']][symbol_df.index < fetch_start], new_symbol[['Open', 'Close']]])
            else:
                symbol_df = asset.history(period="max")
                if symbol_df.empty:
                    print(f"[WARNING] Failed to fetch {symbol}")
                    return pd.DataFrame()
                symbol_df.index = symbol_df.index.tz_localize(None).normalize()
                symbol_df = symbol_df[['Open', 'Close']].copy()

            # 3. Calculate all standard metrics universally for this symbol
            symbol_df['rolling_high'] = symbol_df['Close'].rolling(window=252, min_periods=1).max()
            symbol_df['drawdown'] = (symbol_df['Close'] - symbol_df['rolling_high']) / symbol_df['rolling_high']

            delta = symbol_df['Close'].diff()
            gain = delta.where(delta > 0, 0.0)
            loss = -delta.where(delta < 0, 0.0)
            avg_gain = gain.ewm(alpha=1 / 14, min_periods=14).mean()
            avg_loss = loss.ewm(alpha=1 / 14, min_periods=14).mean()
            rs = avg_gain / avg_loss
            symbol_df['rsi'] = 100 - (100 / (1 + rs))
            symbol_df['realized_vol_20d'] = symbol_df['Close'].pct_change().rolling(window=20).std() * np.sqrt(252)

            # Dynamic Moving Averages and Z-Scores
            for window in [20, 50, 100, 200]:
                symbol_df[f'sma_{window}'] = symbol_df['Close'].rolling(window=window, min_periods=1).mean()
                symbol_df[f'std_{window}'] = symbol_df['Close'].rolling(window=window, min_periods=1).std()
                symbol_df[f'z_score_{window}'] = np.where(
                    symbol_df[f'std_{window}'] > 0,
                    (symbol_df['Close'] - symbol_df[f'sma_{window}']) / symbol_df[f'std_{window}'],
                    0.0
                )

            # 4. Save to isolated cache
            symbol_df = symbol_df.dropna(subset=['Close']).copy()
            symbol_df.to_csv(cache_file)

        return symbol_df
    def _calculate_metrics(self, tracking_df: pd.DataFrame) -> dict:
        days = (tracking_df.index[-1] - tracking_df.index[0]).days
        years_elapsed = days / 365.25

        final_row = tracking_df.iloc[-1]
        total_cash_injected = final_row['total_injected']
        final_net_worth = final_row['net_worth']
        final_shares_value = final_row['shares_value']
        final_cash_remaining = final_row['war_chest']
        total_interest_earned = final_row.get('total_interest', 0.0)

        if total_cash_injected == 0 or years_elapsed <= 0: return {}

        nw_cagr = ((final_net_worth / total_cash_injected) ** (1 / years_elapsed)) - 1
        capital_deployed = total_cash_injected - final_cash_remaining
        invested_cagr = ((final_shares_value / capital_deployed) ** (
                    1 / years_elapsed)) - 1 if capital_deployed > 0 else 0.0

        prev_nw = tracking_df['net_worth'].shift(1).fillna(0)

        # Adjust strat_return calculation for days with cash injections
        cash_in = tracking_df['total_injected'].diff().fillna(tracking_df['total_injected'].iloc[0])
        denom = prev_nw + cash_in
        strat_returns = np.where(denom > 0, (tracking_df['net_worth'] - denom) / denom, 0.0)
        tracking_df['strat_return'] = strat_returns

        twr_index = (1 + tracking_df['strat_return']).cumprod()
        twr_cagr = (twr_index.iloc[-1] ** (1 / years_elapsed)) - 1

        # ... [keep the top part of the function the same] ...
        running_max = twr_index.cummax()
        mdd = ((twr_index - running_max) / running_max).min()

        is_high = (twr_index == running_max)
        high_dates = tracking_df.index[is_high]
        max_recovery_days = (high_dates.to_series().diff().max()).days if len(high_dates) > 1 else days

        # --- NEW: Calculate Risk Metrics strictly against SPY ---
        # 1. Market Returns are now SPY returns, not QQQ returns
        market_returns = tracking_df['bench_Close'].pct_change().fillna(0)

        # 2. Covariance of Strategy Returns against SPY
        cov = tracking_df['strat_return'].cov(market_returns)
        var = market_returns.var()
        beta = cov / var if var > 0 else 1.0

        strat_std_ann = tracking_df['strat_return'].std() * np.sqrt(252)
        sharpe = (twr_cagr - self.risk_free_rate) / strat_std_ann if strat_std_ann > 0 else 0.0

        downside_returns = tracking_df['strat_return'][tracking_df['strat_return'] < 0]
        down_dev_ann = np.sqrt(np.mean(downside_returns ** 2)) * np.sqrt(252) if len(downside_returns) > 0 else 0.0
        sortino = (twr_cagr - self.risk_free_rate) / down_dev_ann if down_dev_ann > 0 else 0.0

        # 3. Market CAGR is now SPY CAGR
        market_cagr = ((tracking_df['bench_Close'].iloc[-1] / tracking_df['bench_Close'].iloc[0]) ** (
                    1 / years_elapsed)) - 1

        # 4. CAPM Alpha calculation uses SPY expected return
        alpha = twr_cagr - (self.risk_free_rate + beta * (market_cagr - self.risk_free_rate))
        treynor = (twr_cagr - self.risk_free_rate) / beta if beta > 0 else 0.0
        calmar = twr_cagr / abs(mdd) if mdd < 0 else 0.0

        return {
            "total_cash_injected": round(total_cash_injected, 2),
            "final_net_worth": round(final_net_worth, 2),
            "total_interest_earned": round(total_interest_earned, 2),
            "final_shares_value": round(final_shares_value, 2),
            "final_cash_remaining": round(final_cash_remaining, 2),
            "net_worth_cagr_pct": round(nw_cagr * 100, 2),
            "invested_capital_cagr_pct": round(invested_cagr * 100, 2),
            "twr_cagr_pct": round(twr_cagr * 100, 2),
            "mdd_pct": round(mdd * 100, 2),
            "max_recovery_days": max_recovery_days,
            "beta": round(beta, 4),
            "jensens_alpha_pct": round(alpha * 100, 2),
            "treynor": round(treynor, 3),
            "calmar": round(calmar, 3),
            "sharpe": round(sharpe, 3),
            "sortino": round(sortino, 3)
        }

    def run_custom_strategy(self, strategy) -> dict:
        """
        Universal engine that evaluates any class inheriting from BaseStrategy.
        Supports both single-asset and multi-asset tactical allocation.
        """
        df = self.data.copy()
        day_counter = 0
        tracking_records = []

        war_chest = 0.0
        total_injected = 0.0
        total_interest = 0.0

        # Dynamic asset list (safely handles if leveraged_ticker isn't set)
        assets = [self.ticker]
        if hasattr(self, 'leveraged_ticker') and self.leveraged_ticker:
            assets.append(self.leveraged_ticker)

        # Track shares and pending orders individually for all active assets
        shares = {sym: 0.0 for sym in assets}
        pending_buys = {sym: 0.0 for sym in assets}
        pending_sells = {sym: 0.0 for sym in assets}

        for date, row in df.iterrows():
            open_price = row['Open']
            close_price = row['Close']
            day_counter += 1

            # 1. MORNING T+1 EXECUTION (Multi-Asset)
            for sym in assets:
                # Route to the correct opening price
                sym_open = row['Open'] if sym == self.ticker else row.get('lev_Open', np.nan)

                # Skip if the asset didn't exist yet (e.g., TQQQ before 2010)
                if pd.isna(sym_open):
                    continue

                if pending_buys[sym] > 0:
                    actual_buy = min(pending_buys[sym], war_chest)
                    war_chest -= actual_buy
                    shares[sym] += (actual_buy / sym_open)
                    pending_buys[sym] = 0.0

                if pending_sells[sym] > 0:
                    # Convert the dollar amount to sell into fractional shares
                    shares_to_sell = pending_sells[sym] / sym_open
                    actual_sell_shares = min(shares_to_sell, shares[sym])

                    war_chest += (actual_sell_shares * sym_open)
                    shares[sym] -= actual_sell_shares
                    pending_sells[sym] = 0.0

            # 2. BI-WEEKLY PAYCHECK
            if day_counter % 10 == 1:
                war_chest += self.biweekly_injection
                total_injected += self.biweekly_injection

            # 3. OVERNIGHT INTEREST ACCRUAL
            daily_rate = (row['fed_funds_rate'] / 100.0) / 252.0
            interest_today = war_chest * daily_rate * (1 - self.tax_rate)
            war_chest += interest_today
            total_interest += interest_today

            # 4. EOD PORTFOLIO VALUATION (Multi-Asset)
            shares_value = 0.0
            for sym in assets:
                sym_close = close_price if sym == self.ticker else row.get('lev_Close', np.nan)
                if not pd.isna(sym_close):
                    shares_value += (shares[sym] * sym_close)

            net_worth = shares_value + war_chest

            tracking_records.append({
                "Date": date,
                "Open": open_price,
                "Close": close_price,
                "bench_Close": row.get('bench_Close', close_price),
                "cash_injected": self.daily_cash_flow,
                "total_injected": total_injected,
                "total_interest": total_interest,
                "shares_value": shares_value,
                "war_chest": war_chest,
                "net_worth": net_worth
            })

            # 5. ALGORITHM GENERATES TOMORROW'S ORDER
            # Dynamically pack all pre-computed MAs and Z-Scores into the payload
            market_data = {
                "close": close_price,
                "vix": row.get('vix', 15.0),
                "spread": row.get('spread', 2.0),
                "rsi": row.get('rsi', 50.0),
                "fear_greed": row.get('fear_greed', 50.0),
                "drawdown": row.get('drawdown', 0.0),
                "realized_vol_20d": row.get('realized_vol_20d', 0.15)
            }

            # Inject all dynamic window metrics
            for window in [20, 50, 100, 200]:
                market_data[f"sma_{window}"] = row.get(f"sma_{window}", close_price)
                market_data[f"z_score_{window}"] = row.get(f"z_score_{window}", 0.0)

            account_state = {
                "net_worth": net_worth,
                "war_chest": war_chest,
                "current_holdings": shares  # Useful for strategies that need to rebalance
            }

            # Pass the data into the strategy object
            inference_result = strategy.calculate_order_amount(market_data, account_state)

            # 6. ROUTE ORDERS
            if "target_orders" in inference_result:
                # NEW MODE: Multi-Asset Routing dict
                for sym in assets:
                    pending_buys[sym] = inference_result["target_orders"].get(sym, 0.0)
            else:
                # LEGACY MODE: Backwards compatibility for your old single-asset models
                pending_buys[self.ticker] = inference_result.get("target_buy_amount", 0.0)
                pending_sells[self.ticker] = inference_result.get("target_sell_amount", 0.0)

        return self._calculate_metrics(pd.DataFrame(tracking_records).set_index("Date"))