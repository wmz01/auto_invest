import os
import pandas as pd
import pyarrow.dataset as ds
import glob
from datetime import datetime


class MarketDataLoader:
    def __init__(self, data_dir: str = "data_lake"):
        self.data_dir = data_dir
        self.macro_file = os.path.join(self.data_dir, "master_macro_sentiment.parquet")

    def load_macro_data(self, start_date: str, end_date: str = None) -> pd.DataFrame:
        """
        Loads the daily macro, yield curve, and options sentiment data.
        Because it's a single master file, we load it and slice by index.
        """
        print(f"Loading Macro & Sentiment data from {start_date} to {end_date or 'Present'}...")

        if not os.path.exists(self.macro_file):
            raise FileNotFoundError(f"Master macro file not found at {self.macro_file}")

        # Read the parquet file
        df = pd.read_parquet(self.macro_file, engine='pyarrow')

        # Ensure the index is a datetime object for clean slicing
        if not pd.api.types.is_datetime64_any_dtype(df.index):
            df.index = pd.to_datetime(df.index)

        # Slice the dates
        mask = (df.index >= pd.to_datetime(start_date))
        if end_date:
            mask = mask & (df.index <= pd.to_datetime(end_date))

        sliced_df = df.loc[mask].copy()
        print(f" -> Loaded {len(sliced_df)} daily macro records.")
        return sliced_df

    def load_intraday_bars(self, symbols: list, start_date: str, end_date: str = None) -> pd.DataFrame:
        """
        Loads high-fidelity intraday bars.
        Uses PyArrow Datasets to scan the nested YYYY/MM folders and lazy-load
        only the required dates and symbols into memory.
        """
        if isinstance(symbols, str):
            symbols = [symbols]
        print(f"Loading Intraday Bars for {symbols} from {start_date} to {end_date or 'Present'}...")

        # 1. Find all intraday parquet files in the nested YYYY/MM directories
        search_pattern = os.path.join(self.data_dir, "**", "intraday_bars_*.parquet")
        all_files = glob.glob(search_pattern, recursive=True)

        if not all_files:
            raise FileNotFoundError("No intraday parquet files found in the data lake.")

        # 2. Create a PyArrow Dataset (This does NOT load the data into RAM yet)
        dataset = ds.dataset(all_files, format="parquet")

        # 3. Build our filters (Predicate Pushdown)
        # We tell the engine to ONLY grab rows matching our symbols and date range

        # FIX: Force Pandas to make these UTC-aware to match Alpaca's parquet formatting
        start_ts = pd.to_datetime(start_date, utc=True)

        if end_date:
            end_ts = pd.to_datetime(end_date, utc=True)
        else:
            end_ts = pd.Timestamp.now(tz='UTC')

        # 'symbol' and 'timestamp' are the default column names Alpaca uses for its bars
        symbol_filter = ds.field("symbol").isin(symbols)
        date_filter = (ds.field("timestamp") >= start_ts) & (ds.field("timestamp") <= end_ts)
        combined_filter = symbol_filter & date_filter

        # 4. Execute the query and convert to Pandas
        # This is where the actual hard drive read happens, and it's lightning fast
        table = dataset.to_table(filter=combined_filter)
        df = table.to_pandas()

        if df.empty:
            print(" -> Warning: No intraday data matched your query.")
            return df

        # 5. Clean up the DataFrame to match our backtester format

        # Flatten the MultiIndex restored by Parquet if 'timestamp' is trapped in the index
        if 'timestamp' not in df.columns:
            df.reset_index(inplace=True)

        # Now safely set it as the primary time-series index
        df.set_index("timestamp", inplace=True)
        df.sort_index(inplace=True)

        print(f" -> Loaded {len(df)} intraday rows across {len(symbols)} symbols.")
        return df

def main():
    market_loader = MarketDataLoader()
    df = market_loader.load_macro_data("2026-04-30")
    for col in df.columns:
        print(f"Column: {col}")
        print(df[col])
        print("-" * 20)  # Optional separator
    print(market_loader.load_intraday_bars(["VOO"], "2026-04-30"))
if __name__ == "__main__":
    main()