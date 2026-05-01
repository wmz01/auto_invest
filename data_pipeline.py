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


def get_today_market_features(api_key: str, secret_key: str, symbol: str = "VOO") -> dict:
    """
    Acts as the Feature Store. Pulls history from Alpaca, calculates technicals,
    merges with macro data, and returns a clean dictionary for the inference engine.
    """
    print("[PIPELINE] Booting up feature extraction...")

    # 1. Initialize Alpaca Data Client
    data_client = StockHistoricalDataClient(api_key, secret_key)

    # Pull 400 calendar days to guarantee we have 252 active trading days for rolling math
    start_dt = datetime.now() - timedelta(days=400)
    request_params = StockBarsRequest(
        symbol_or_symbols=symbol,
        timeframe=TimeFrame.Day,
        start=start_dt,
        end=datetime.now()
    )

    print(f"[PIPELINE] Fetching historical bars for {symbol} from Alpaca...")
    bars = data_client.get_stock_bars(request_params).df

    # Alpaca returns a MultiIndex (symbol, timestamp). We drop the symbol level.
    bars = bars.reset_index(level=0, drop=True)

    # 2. Calculate Technical Features (Exactly as backtested)
    bars['rolling_high'] = bars['close'].rolling(window=252, min_periods=1).max()
    bars['drawdown'] = (bars['close'] - bars['rolling_high']) / bars['rolling_high']

    delta = bars['close'].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / 14, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, min_periods=14).mean()
    rs = avg_gain / avg_loss
    bars['rsi'] = 100 - (100 / (1 + rs))

    # 3. Extract Today's State
    latest_close = float(bars['close'].iloc[-1])
    latest_drawdown = float(bars['drawdown'].iloc[-1])
    latest_rsi = float(bars['rsi'].iloc[-1])

    # 4. Fetch Macro Features
    print("[PIPELINE] Fetching Macro Indicators...")
    latest_vix = _fetch_vix_close()
    latest_spread = _fetch_fred_high_yield_spread()
    latest_fg = _fetch_cnn_fear_greed()

    features = {
        "close": latest_close,
        "drawdown": latest_drawdown,
        "rsi": latest_rsi,
        "vix": latest_vix,
        "spread": latest_spread,
        "fear_greed": latest_fg
    }

    print(f"[PIPELINE] Feature extraction complete: {features}")
    return features