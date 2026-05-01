import pandas as pd
import os


def inject_historical_fear_greed():
    historical_file = "fear-greed.csv"
    cache_file = "macro_data.csv"
    cutoff_date = pd.to_datetime("2025-05-01")

    # 1. Verify files exist
    if not os.path.exists(historical_file):
        print(f"[ERROR] Could not find {historical_file}. Please ensure it is in the same directory.")
        return
    if not os.path.exists(cache_file):
        print(f"[ERROR] Could not find {cache_file}. Please run your backtester once to generate the cache.")
        return

    print("Loading datasets...")
    # Load historical data and extract just the 'Fear Greed' column as a Series
    hist_df = pd.read_csv(historical_file, parse_dates=['Date'], index_col='Date')
    hist_fg_series = hist_df['Fear Greed']

    # Load the macro cache
    macro_df = pd.read_csv(cache_file, parse_dates=True, index_col=0)

    # 2. Identify the target dates
    # We only want to touch dates BEFORE May 1, 2025
    mask = macro_df.index < cutoff_date
    target_dates = macro_df[mask].index

    print(f"Found {len(target_dates)} dates prior to {cutoff_date.date()} to process.")

    # 3. Align and Override
    # Align the historical data to exactly match the dates we are targeting in the cache
    aligned_hist_fg = hist_fg_series.reindex(target_dates)

    # Count how many we actually found before we fill the NaNs
    found_count = aligned_hist_fg.notna().sum()
    missing_count = aligned_hist_fg.isna().sum()

    # Apply the default 50.0 to any dates that were missing in the historical CSV
    aligned_hist_fg = aligned_hist_fg.fillna(50.0)

    # Inject the aligned data directly back into the macro dataframe
    macro_df.loc[mask, 'fear_greed'] = aligned_hist_fg

    # 4. Save the patched cache
    macro_df.to_csv(cache_file)

    print("==================================================")
    print(" INJECTION COMPLETE ")
    print("==================================================")
    print(f"Overwrote {found_count} historical values.")
    print(f"Defaulted {missing_count} missing values to Neutral (50.0).")
    print(f"Dates on or after {cutoff_date.date()} were left completely untouched.")
    print(f"Saved successfully to: {cache_file}")


if __name__ == "__main__":
    inject_historical_fear_greed()