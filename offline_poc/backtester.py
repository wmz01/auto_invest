import os
import io
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from random import choice
import pandas_datareader.data as web

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_4) AppleWebKit/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
]


class ProfessionalBacktester:
    def __init__(self, daily_cash_flow: float = 100.0, risk_free_rate: float = 0.042):
        self.daily_cash_flow = daily_cash_flow
        self.biweekly_injection = daily_cash_flow * 10
        self.risk_free_rate = risk_free_rate
        self.benchmark_ticker = "SPY"  # Global benchmark for risk metrics
        self.data = None

    def _get_latest_market_date(self) -> pd.Timestamp:
        try:
            recent = yf.Ticker("SPY").history(period="5d")
            return recent.index[-1].tz_localize(None).normalize()
        except Exception:
            return pd.Timestamp.today().normalize()

    def fetch_cnn_fear_greed(self) -> pd.Series:
        print("Fetching CNN Fear & Greed Index...")
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {"User-Agent": choice(USER_AGENTS)}
        try:
            r = requests.get(url, headers=headers, timeout=10)
            data = r.json()['fear_and_greed_historical']['data']
            df = pd.DataFrame(data)
            df['Date'] = pd.to_datetime(df['x'], unit='ms').dt.normalize()
            return df.set_index('Date')['y'].rename('fear_greed')
        except Exception:
            return pd.Series(dtype=float, name='fear_greed')

    def fetch_fred_high_yield_spread(self) -> pd.Series:
        print("Fetching FRED High Yield Spread...")
        try:
            df = web.DataReader('BAMLH0A0HYM2', 'fred', start='1990-01-01')
            return df['BAMLH0A0HYM2'].astype(float).rename('spread')
        except Exception:
            return pd.Series(dtype=float, name='spread')

    def fetch_fred_federal_funds_rate(self) -> pd.Series:
        print("Fetching FRED Federal Funds Rate...")
        try:
            df = web.DataReader('DFF', 'fred', start='1990-01-01')
            return df['DFF'].astype(float).rename('fed_funds_rate')
        except Exception:
            return pd.Series(dtype=float, name='fed_funds_rate')

    def _get_symbol_data(self, symbol: str, required_freshness: pd.Timestamp,
                         force_fetch: bool = False) -> pd.DataFrame:
        if not symbol: return pd.DataFrame()
        cache_dir = "market_cache"
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"{symbol}_price_data.csv")

        symbol_df = pd.DataFrame()
        fetch_symbol = True
        overlap_days = 5

        if os.path.exists(cache_file):
            symbol_df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
            if not symbol_df.empty and 'Open' in symbol_df.columns and symbol_df.index.max() >= required_freshness:
                fetch_symbol = False
                print(f"[CACHE HIT] {symbol} up-to-date.")

        if fetch_symbol or force_fetch:
            print(f"[FETCHING] Downloading {symbol}...")
            asset = yf.Ticker(symbol)
            if not symbol_df.empty and 'Open' in symbol_df.columns:
                fetch_start = symbol_df.index.max() - pd.Timedelta(days=overlap_days)
                new_symbol = asset.history(start=fetch_start.strftime('%Y-%m-%d'))
                new_symbol.index = new_symbol.index.tz_localize(None).normalize()
                symbol_df = pd.concat(
                    [symbol_df[['Open', 'Close']][symbol_df.index < fetch_start], new_symbol[['Open', 'Close']]])
            else:
                symbol_df = asset.history(period="max")
                symbol_df.index = symbol_df.index.tz_localize(None).normalize()
                symbol_df = symbol_df[['Open', 'Close']].copy()

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

            for window in [20, 50, 100, 200]:
                symbol_df[f'sma_{window}'] = symbol_df['Close'].rolling(window=window, min_periods=1).mean()
                symbol_df[f'std_{window}'] = symbol_df['Close'].rolling(window=window, min_periods=1).std()
                symbol_df[f'z_score_{window}'] = np.where(
                    symbol_df[f'std_{window}'] > 0,
                    (symbol_df['Close'] - symbol_df[f'sma_{window}']) / symbol_df[f'std_{window}'], 0.0)

            symbol_df = symbol_df.dropna(subset=['Close']).copy()
            symbol_df.to_csv(cache_file)

        return symbol_df

    def prepare_historical_data(self, symbols: list, start_date: str, end_date: str = None, force_fetch: bool = False):
        cache_dir = "market_cache"
        os.makedirs(cache_dir, exist_ok=True)
        macro_cache_file = os.path.join(cache_dir, "macro_data.csv")

        latest_market_date = self._get_latest_market_date()
        target_end_date = pd.to_datetime(end_date) if end_date else latest_market_date
        required_freshness = min(latest_market_date, target_end_date)

        # 1. Macro Data
        macro_df = pd.DataFrame()
        fetch_macro = True
        if os.path.exists(macro_cache_file):
            macro_df = pd.read_csv(macro_cache_file, index_col=0, parse_dates=True)
            if not macro_df.empty and macro_df.index.max() >= required_freshness:
                fetch_macro = False
                print(f"[CACHE HIT] Macro Data up-to-date.")

        if fetch_macro or force_fetch:
            print("[FETCHING] Macro Data...")
            vix = yf.Ticker("^VIX").history(period="max")
            vix.index = vix.index.tz_localize(None).normalize()
            macro_df = vix[['Close']].rename(columns={'Close': 'vix'})
            macro_df = macro_df.join(self.fetch_cnn_fear_greed()).join(self.fetch_fred_high_yield_spread()).join(
                self.fetch_fred_federal_funds_rate())
            macro_df['vix'] = macro_df['vix'].ffill().fillna(15.0)
            macro_df['fear_greed'] = macro_df['fear_greed'].ffill().fillna(50.0)
            macro_df['spread'] = macro_df['spread'].ffill().fillna(4.0)
            macro_df['fed_funds_rate'] = macro_df['fed_funds_rate'].ffill().fillna(2.0)
            macro_df.to_csv(macro_cache_file)

        # Ensure benchmark is loaded for metrics
        if self.benchmark_ticker not in symbols:
            symbols.append(self.benchmark_ticker)

        # 2. Build the Data Lake
        master_df = macro_df.copy()
        for sym in symbols:
            sym_df = self._get_symbol_data(sym, required_freshness, force_fetch)
            if not sym_df.empty:
                sym_df = sym_df.add_prefix(f"{sym}_")  # Prefix columns! (e.g., QQQ_Close)
                master_df = master_df.join(sym_df, how='outer')

        # 3. Slice and store
        df = master_df.dropna(subset=[f"{symbols[0]}_Close"]).copy()
        mask = (df.index >= pd.to_datetime(start_date))
        if end_date: mask = mask & (df.index <= pd.to_datetime(end_date))
        self.data = df.loc[mask].copy()
        print(f"Loaded {len(self.data)} active trading days for the backtest.")

    def run_custom_strategy(self, strategy) -> dict:
        df = self.data.copy()

        # Determine assets from the specific strategy config
        base_sym = strategy.config.get("base_asset")
        lev_sym = strategy.config.get("leveraged_asset", None)

        assets = [base_sym]
        if lev_sym: assets.append(lev_sym)

        day_counter = 0
        tracking_records = []
        war_chest = 0.0
        total_injected = 0.0
        total_interest = 0.0

        shares = {sym: 0.0 for sym in assets}
        total_cost_basis = {sym: 0.0 for sym in assets}
        pending_buys = {sym: 0.0 for sym in assets}
        pending_sells = {sym: 0.0 for sym in assets}

        for date, row in df.iterrows():
            day_counter += 1

            # 1. MORNING T+1 EXECUTION
            for sym in assets:
                sym_open = row.get(f"{sym}_Open", np.nan)
                if pd.isna(sym_open): continue

                # Sells First (T+0 Rotation)
                if pending_sells[sym] > 0:
                    shares_to_sell = pending_sells[sym] / sym_open
                    actual_sell_shares = min(shares_to_sell, shares[sym])
                    if actual_sell_shares > 0:
                        revenue = actual_sell_shares * sym_open
                        avg_cost_per_share = total_cost_basis[sym] / shares[sym]
                        cost_of_shares_sold = actual_sell_shares * avg_cost_per_share
                        profit = revenue - cost_of_shares_sold
                        tax_owed = (profit * strategy.config.get("tax_rate", 0.0)) if profit > 0 else 0.0

                        war_chest += (revenue - tax_owed)
                        shares[sym] -= actual_sell_shares
                        total_cost_basis[sym] -= cost_of_shares_sold
                    pending_sells[sym] = 0.0

                # Buys Second
                if pending_buys[sym] > 0:
                    actual_buy = min(pending_buys[sym], war_chest)
                    shares_bought = actual_buy / sym_open
                    war_chest -= actual_buy
                    shares[sym] += shares_bought
                    total_cost_basis[sym] += actual_buy
                    pending_buys[sym] = 0.0

            # 2. INJECTIONS & INTEREST
            if day_counter % 10 == 1:
                war_chest += self.biweekly_injection
                total_injected += self.biweekly_injection

            daily_rate = (row['fed_funds_rate'] / 100.0) / 252.0
            interest_today = war_chest * daily_rate * (1 - strategy.config.get("tax_rate", 0.0))
            war_chest += interest_today
            total_interest += interest_today

            # 3. EOD VALUATION
            base_value = shares[base_sym] * row.get(f"{base_sym}_Close", 0.0)
            lev_value = shares[lev_sym] * row.get(f"{lev_sym}_Close", 0.0) if lev_sym else 0.0
            shares_value = base_value + lev_value
            net_worth = shares_value + war_chest

            tracking_records.append({
                "Date": date,
                "Open": row.get(f"{base_sym}_Open", np.nan),
                "Close": row.get(f"{base_sym}_Close", np.nan),
                "bench_Close": row.get(f"{self.benchmark_ticker}_Close", np.nan),
                "cash_injected": self.daily_cash_flow,
                "total_injected": total_injected,
                "total_interest": total_interest,
                "base_value": base_value,
                "lev_value": lev_value,
                "shares_value": shares_value,
                "war_chest": war_chest,
                "net_worth": net_worth
            })

            # 4. ALGORITHM PAYLOAD PREP
            market_data = {
                "close": row.get(f"{base_sym}_Close", 0.0),
                "lev_Close": row.get(f"{lev_sym}_Close", 0.0) if lev_sym else 0.0,
                "drawdown": row.get(f"{base_sym}_drawdown", 0.0),
                "rsi": row.get(f"{base_sym}_rsi", 50.0),
                "vix": row.get('vix', 15.0),
                "spread": row.get('spread', 2.0),
                "fear_greed": row.get('fear_greed', 50.0),
            }
            for window in [20, 50, 100, 200]:
                market_data[f"sma_{window}"] = row.get(f"{base_sym}_sma_{window}", 0.0)
                market_data[f"z_score_{window}"] = row.get(f"{base_sym}_z_score_{window}", 0.0)

            # 5. EXECUTE STRATEGY
            inference_result = strategy.calculate_order_amount(market_data,
                                                               {"net_worth": net_worth, "war_chest": war_chest,
                                                                "current_holdings": shares})

            # 6. ROUTE ORDERS
            if "target_orders" in inference_result:
                # --- NEW MODE: Multi-Asset Routing ---
                for sym in assets:
                    target_amt = inference_result["target_orders"].get(sym, 0.0)
                    if target_amt > 0:
                        pending_buys[sym] = target_amt
                        pending_sells[sym] = 0.0
                    elif target_amt < 0:
                        pending_sells[sym] = abs(target_amt)
                        pending_buys[sym] = 0.0
                    else:
                        pending_buys[sym] = 0.0
                        pending_sells[sym] = 0.0
            else:
                # --- LEGACY MODE: Backwards Compatibility ---
                # Safely catches old strategies that only output a single target_buy_amount
                buy_amt = inference_result.get("target_buy_amount", 0.0)
                sell_amt = inference_result.get("target_sell_amount", 0.0)

                if buy_amt > 0:
                    pending_buys[base_sym] = buy_amt
                    pending_sells[base_sym] = 0.0
                elif sell_amt > 0:
                    pending_sells[base_sym] = sell_amt
                    pending_buys[base_sym] = 0.0
                else:
                    pending_buys[base_sym] = 0.0
                    pending_sells[base_sym] = 0.0



        df_tracking = pd.DataFrame(tracking_records).set_index("Date")
        metrics = self._calculate_metrics(df_tracking)
        metrics['final_base_shares'] = shares[base_sym]
        if lev_sym: metrics['final_lev_shares'] = shares[lev_sym]

        return metrics, df_tracking

    def _calculate_metrics(self, tracking_df: pd.DataFrame) -> dict:
        # [Keep this exactly the same as your current file, no changes needed here!]
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
        cash_in = tracking_df['total_injected'].diff().fillna(tracking_df['total_injected'].iloc[0])
        denom = prev_nw + cash_in
        strat_returns = np.where(denom > 0, (tracking_df['net_worth'] - denom) / denom, 0.0)
        tracking_df['strat_return'] = strat_returns

        twr_index = (1 + tracking_df['strat_return']).cumprod()
        twr_cagr = (twr_index.iloc[-1] ** (1 / years_elapsed)) - 1

        running_max = twr_index.cummax()
        mdd = ((twr_index - running_max) / running_max).min()

        is_high = (twr_index == running_max)
        high_dates = tracking_df.index[is_high]
        max_recovery_days = (high_dates.to_series().diff().max()).days if len(high_dates) > 1 else days

        market_returns = tracking_df['bench_Close'].pct_change().fillna(0)
        cov = tracking_df['strat_return'].cov(market_returns)
        var = market_returns.var()
        beta = cov / var if var > 0 else 1.0

        strat_std_ann = tracking_df['strat_return'].std() * np.sqrt(252)
        sharpe = (twr_cagr - self.risk_free_rate) / strat_std_ann if strat_std_ann > 0 else 0.0

        downside_returns = tracking_df['strat_return'][tracking_df['strat_return'] < 0]
        down_dev_ann = np.sqrt(np.mean(downside_returns ** 2)) * np.sqrt(252) if len(downside_returns) > 0 else 0.0
        sortino = (twr_cagr - self.risk_free_rate) / down_dev_ann if down_dev_ann > 0 else 0.0

        market_cagr = ((tracking_df['bench_Close'].iloc[-1] / tracking_df['bench_Close'].iloc[0]) ** (
                    1 / years_elapsed)) - 1
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