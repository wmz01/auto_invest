import pandas as pd
import numpy as np
import yfinance as yf
import requests
import io
from datetime import datetime, timedelta
from random import choice
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from notifier import send_discord_alert

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_4) AppleWebKit/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
]


def _fetch_cnn_fear_greed() -> float:
    """Fetches the latest CNN Fear & Greed Index value."""
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    headers = {"User-Agent": choice(USER_AGENTS)}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()['fear_and_greed_historical']['data']
        # Return the most recent 'y' value (the index score)
        return float(data[-1]['y'])
    except Exception as e:
        warning_msg = f"⚠️ **Data Warning:** CNN Fear & Greed fetch failed: {e}. Defaulting to 50.0"
        print(warning_msg)
        send_discord_alert(warning_msg) # Push the exception to Discord
        return 50.0


def _fetch_fred_high_yield_spread() -> float:
    """Fetches the latest ICE BofA US High Yield Index Spread."""
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2"
    headers = {"User-Agent": choice(USER_AGENTS)}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text), na_values='.')
        # Drop NaNs and get the absolute latest value
        latest_val = df['BAMLH0A0HYM2'].dropna().iloc[-1]
        return float(latest_val)
    except Exception as e:
        warning_msg = f"⚠️ **Data Warning:** FRED Spread fetch failed: {e}. Defaulting to 4.0"
        print(warning_msg)
        send_discord_alert(warning_msg) # Push the exception to Discord
        return 4.0


def _fetch_vix_close() -> float:
    try:
        vix = yf.Ticker("^VIX").history(period="5d")
        return float(vix['Close'].iloc[-1])
    except Exception as e:
        warning_msg = f"⚠️ **Data Warning:** VIX fetch failed (`{e}`). Defaulting to 20.0."
        print(warning_msg)
        send_discord_alert(warning_msg) # Push the exception to Discord
        return 20.0



def get_today_market_features(api_key: str = None, secret_key: str = None, base_symbol: str = "QQQ",
                              leveraged_symbol: str = None) -> dict:
    """
    Fetches market features for the primary asset and pricing for the secondary asset.
    """
    try:
        # 1. Fetch Base Asset Data & Technicals
        base_ticker = yf.Ticker(base_symbol)
        hist = base_ticker.history(period="1y")

        if hist.empty:
            raise ValueError(f"No data returned for {base_symbol}")

        close_price = hist['Close'].iloc[-1]

        # Calculate Rolling High and Drawdown
        rolling_high = hist['Close'].rolling(window=252, min_periods=1).max().iloc[-1]
        drawdown = (close_price - rolling_high) / rolling_high if rolling_high > 0 else 0.0

        # Calculate RSI (14-day)
        delta = hist['Close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / 14, min_periods=14).mean().iloc[-1]
        avg_loss = loss.ewm(alpha=1 / 14, min_periods=14).mean().iloc[-1]
        rs = avg_gain / avg_loss if avg_loss > 0 else 0
        rsi = 100 - (100 / (1 + rs))

        # 2. Fetch Secondary Asset Pricing
        lev_close = 0.0
        if leveraged_symbol:
            lev_ticker = yf.Ticker(leveraged_symbol)
            lev_hist = lev_ticker.history(period="5d")
            if not lev_hist.empty:
                lev_close = lev_hist['Close'].iloc[-1]

        # 3. Fetch Macro Data
        try:
            vix = yf.Ticker("^VIX").history(period="5d")['Close'].iloc[-1]
        except:
            vix = 15.0

        return {
            "close": float(close_price),
            "lev_Close": float(lev_close),
            "drawdown": float(drawdown),
            "rsi": float(rsi),
            "vix": float(vix),
            "spread": 4.0,  # Fallback constants if FRED API isn't implemented
            "fear_greed": 50.0  # Fallback constants if CNN API isn't implemented
        }
    except Exception as e:
        print(f"[ERROR] Data Pipeline Failure: {e}")
        # Return safe neutral dictionary to prevent catastrophic algorithmic math
        return {
            "close": 100.0, "lev_Close": 100.0, "drawdown": 0.0,
            "rsi": 50.0, "vix": 15.0, "spread": 4.0, "fear_greed": 50.0
        }