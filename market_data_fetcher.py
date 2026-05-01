import os
import io
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import pandas_datareader.data as web
from datetime import datetime, timedelta
from random import choice
from dotenv import load_dotenv

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

# Load environment variables
load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY_REAL_CASH")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY_REAL_CASH")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_4) AppleWebKit/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
]


class MarketArchiver:
    def __init__(self, data_dir: str = "data_lake"):
        self.data_dir = data_dir
        self.today = datetime.now()
        self.today_str = self.today.strftime("%Y-%m-%d")

        # Partition data by Year and Month for lightning-fast querying in the future
        year_month = self.today.strftime("%Y/%m")
        self.save_path = os.path.join(self.data_dir, year_month)
        os.makedirs(self.save_path, exist_ok=True)

        # Alpaca Client for Intraday Bars
        self.alpaca_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)

    def fetch_intraday_bars(self, symbols: list):
        """PILLAR 1: High-fidelity 15-minute price action"""
        print(f"[{self.today_str}] Fetching Intraday Bars for {symbols}...")
        try:
            req = StockBarsRequest(
                symbol_or_symbols=symbols,
                timeframe=TimeFrame(15, TimeFrameUnit.Minute),  # <-- The exact fix
                start=self.today - timedelta(days=2),
                end=self.today
            )
            bars = self.alpaca_client.get_stock_bars(req)
            df = bars.df

            if not df.empty:
                filename = os.path.join(self.save_path, f"intraday_bars_{self.today_str}.parquet")
                df.to_parquet(filename, engine='pyarrow')
                print(f"  -> Saved {len(df)} rows to {filename}")
            else:
                print("  -> Warning: No intraday data returned (Market Holiday?)")
        except Exception as e:
            print(f"  -> ERROR fetching intraday bars: {e}")

    def fetch_spy_options_sentiment(self) -> dict:
        """PILLAR 2: Options Chain Data with Hyper-Verbose Logging"""
        print(f"\n[{self.today_str}] --- STARTING OPTIONS FETCH ---")
        options_data = {
            "atm_call_iv": np.nan, "atm_put_iv": np.nan,
            "total_call_oi": np.nan, "total_put_oi": np.nan,
            "put_call_ratio": np.nan
        }

        tickers_to_try = ["SPY", "^SPX"]
        MIN_LIQUIDITY_THRESHOLD = 50000

        for ticker_symbol in tickers_to_try:
            try:
                print(f"  -> [DEBUG] Requesting {ticker_symbol} from yfinance...")
                asset = yf.Ticker(ticker_symbol)

                # Check 1: Can we even get the price?
                hist = asset.history(period="1d")
                if hist.empty:
                    print(f"    [FAIL] No price history returned for {ticker_symbol}.")
                    continue
                current_price = hist['Close'].iloc[-1]
                print(f"    [SUCCESS] {ticker_symbol} Current Price: ${current_price:.2f}")

                # Check 2: Are there expirations?
                expirations = asset.options
                print(f"    [DEBUG] Found {len(expirations)} total expiration dates.")
                if not expirations:
                    print(f"    [FAIL] yfinance returned an empty tuple for expirations.")
                    continue

                # Check 3: Date filtering
                valid_expirations = [
                    exp for exp in expirations
                    if 20 <= (datetime.strptime(exp, '%Y-%m-%d') - self.today).days <= 40
                ]
                print(f"    [DEBUG] Found {len(valid_expirations)} expirations in the 20-40 day window.")
                if not valid_expirations:
                    valid_expirations = expirations

                best_expiry = None
                max_oi = -1
                best_chain = None

                # Check 4: Liquidity Scan
                print(f"    [DEBUG] Scanning {len(valid_expirations)} chains for liquidity...")
                for exp in valid_expirations:
                    chain = asset.option_chain(exp)
                    calls_oi = chain.calls['openInterest'].fillna(0).sum()
                    puts_oi = chain.puts['openInterest'].fillna(0).sum()
                    total_oi = calls_oi + puts_oi

                    if total_oi > max_oi:
                        max_oi = total_oi
                        best_expiry = exp
                        best_chain = chain

                print(f"    [DEBUG] Highest liquidity found: {max_oi:,.0f} OI on {best_expiry}")

                # Check 5: Threshold Enforcement
                if max_oi < MIN_LIQUIDITY_THRESHOLD:
                    print(
                        f"    [FAIL] Max OI ({max_oi}) < Threshold ({MIN_LIQUIDITY_THRESHOLD}). Ghost chain detected.")
                    continue

                calls, puts = best_chain.calls, best_chain.puts
                active_calls = calls[calls['openInterest'] > 0]
                active_puts = puts[puts['openInterest'] > 0]

                if active_calls.empty or active_puts.empty:
                    print(f"    [FAIL] The 'best' chain had literally 0 active contracts. yfinance bug.")
                    continue

                atm_strike_call = min(active_calls['strike'], key=lambda x: abs(x - current_price))
                atm_strike_put = min(active_puts['strike'], key=lambda x: abs(x - current_price))

                atm_call = active_calls[active_calls['strike'] == atm_strike_call].iloc[0]
                atm_put = active_puts[active_puts['strike'] == atm_strike_put].iloc[0]

                total_call_oi = calls['openInterest'].fillna(0).sum()
                total_put_oi = puts['openInterest'].fillna(0).sum()

                options_data.update({
                    "atm_call_iv": atm_call['impliedVolatility'],
                    "atm_put_iv": atm_put['impliedVolatility'],
                    "total_call_oi": int(total_call_oi),
                    "total_put_oi": int(total_put_oi),
                    "put_call_ratio": total_put_oi / total_call_oi if total_call_oi > 0 else np.nan
                })
                print(f"  -> [SUCCESS] Extracted robust data from {ticker_symbol}!")
                return options_data

            except Exception as e:
                # We want to see the EXACT python error now
                import traceback
                print(f"  -> [CRITICAL ERROR] Failed on {ticker_symbol}: {repr(e)}")
                traceback.print_exc()

        print("  -> [FATAL] All options fetch attempts failed. Returning NaNs.")
        return options_data

    def fetch_macro_and_sentiment(self):
        """PILLAR 3 & 4: Point-in-Time Macro, Yield Curve, and Market Breadth"""
        print(f"[{self.today_str}] Fetching Macro & Sentiment Indicators...")

        # Initialize our master row for today
        data_payload = {"Date": pd.to_datetime(self.today_str)}

        # --- 1. FRED Macro Data ---
        fred_series = {
            'BAMLH0A0HYM2': 'high_yield_spread',
            'DFF': 'fed_funds_rate',
            'T10Y2Y': 'yield_curve_10y_2y'  # Classic Recession Indicator
        }
        for fred_ticker, mapped_name in fred_series.items():
            try:
                df = web.DataReader(fred_ticker, 'fred', start=self.today - timedelta(days=5))
                data_payload[mapped_name] = df.iloc[-1].values[0]
            except Exception as e:
                print(f"  -> ERROR fetching {mapped_name}: {e}")
                data_payload[mapped_name] = np.nan

        # --- 2. VIX (Volatility Index) ---
        try:
            vix_close = yf.Ticker("^VIX").history(period="1d")['Close'].iloc[-1]
            data_payload['vix_close'] = vix_close
        except Exception:
            data_payload['vix_close'] = np.nan

        # --- 3. CNN Fear & Greed ---
        try:
            url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
            headers = {"User-Agent": choice(USER_AGENTS)}
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            fg_data = r.json()['fear_and_greed_historical']['data']
            data_payload['fear_greed'] = float(fg_data[-1]['y'])
        except Exception as e:
            print(f"  -> ERROR fetching CNN Fear/Greed: {e}")
            data_payload['fear_greed'] = np.nan

        # --- Merge Options Data ---
        options_metrics = self.fetch_spy_options_sentiment()
        data_payload.update(options_metrics)

        # --- Save to Master Parquet Ledger ---
        df = pd.DataFrame([data_payload])
        df.set_index("Date", inplace=True)

        master_file = os.path.join(self.data_dir, "master_macro_sentiment.parquet")

        try:
            if os.path.exists(master_file):
                master_df = pd.read_parquet(master_file)
                # Drop today if it somehow already exists to avoid duplicates
                master_df = master_df[~master_df.index.isin(df.index)]
                master_df = pd.concat([master_df, df])
                master_df.to_parquet(master_file, engine='pyarrow')
            else:
                df.to_parquet(master_file, engine='pyarrow')
            print(f"  -> Successfully appended Macro/Sentiment to {master_file}")
        except Exception as e:
            print(f"  -> FATAL ERROR saving macro parquet: {e}")


if __name__ == "__main__":
    print("==================================================")
    print(f" INITIATING DATA LAKE ARCHIVER ")
    print("==================================================")

    archiver = MarketArchiver()

    # 1. Fetch High-Res Intraday Pricing
    archiver.fetch_intraday_bars(["VOO", "SPY", "QQQ", "TLT", "GLD"])

    # 2. Fetch Point-in-Time Macro, Breadth, and Options Sentiment
    archiver.fetch_macro_and_sentiment()

    print("\n[SUCCESS] Archiving pass complete.")