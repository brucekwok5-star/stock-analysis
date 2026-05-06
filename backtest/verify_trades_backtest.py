#!/usr/bin/env python3
"""
Backtest Trade Verification
Verifies historical trades from portfolio files using actual price data.
For backtest: gets data AFTER the recommendation time to check if target/stop was hit.
"""

# Suppress warnings and yfinance errors before any imports
import warnings
warnings.filterwarnings('ignore')
import logging
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

import pandas as pd
from datetime import datetime, timedelta
import pytz
import glob
import json
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Timezones
HK_TZ = pytz.timezone('Asia/Hong_Kong')
US_TZ = pytz.timezone('US/Eastern')


def is_hk_stock(code: str) -> bool:
    """Check if stock code is HK market"""
    return code.endswith('.HK') or (code.isdigit() and len(code) <= 5)


def normalize_hk_ticker(code: str) -> str:
    """Normalize HK stock ticker for Yahoo Finance."""
    if not code.endswith('.HK'):
        return code

    numeric = code.replace('.HK', '')
    if len(numeric) < 4:
        numeric = numeric.zfill(4)
    return f"{numeric}.HK"


def get_historical_data(code: str, start_date: str, end_date: str = None) -> pd.DataFrame:
    """Get historical data for verification using yfinance"""
    try:
        import yfinance as yf

        if is_hk_stock(code):
            yahoo_code = normalize_hk_ticker(code)
        else:
            yahoo_code = code.upper()

        ticker = yf.Ticker(yahoo_code)

        if end_date:
            df = ticker.history(start=start_date, end=end_date, interval="1m")
        else:
            df = ticker.history(period="5d", interval="1m")

        return df
    except Exception as e:
        print(f"  Error fetching data: {e}")
        return pd.DataFrame()


def check_backtest_trade(code: str, entry: float, stop: float, target: float,
                         timestamp: str, is_short: bool = False) -> dict:
    """
    Check trade result using historical data AFTER the recommendation timestamp.
    """
    try:
        import yfinance as yf

        # Parse timestamp
        ts = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        ts = HK_TZ.localize(ts)

        # Get data starting from entry time
        start_str = ts.strftime('%Y-%m-%d')
        # Fetch 3 days to ensure we have enough data
        end_dt = ts + timedelta(days=3)
        end_str = end_dt.strftime('%Y-%m-%d')

        if is_hk_stock(code):
            yahoo_code = normalize_hk_ticker(code)
            ticker = yf.Ticker(yahoo_code)
            df = ticker.history(start=start_str, end=end_str, interval="1m")
            if not df.empty:
                df = df.tz_convert(HK_TZ)
        else:
            ts_us = ts.astimezone(US_TZ)
            start_str_us = ts_us.strftime('%Y-%m-%d')
            end_str_us = end_dt.astimezone(US_TZ).strftime('%Y-%m-%d')
            ticker = yf.Ticker(code.upper())
            df = ticker.history(start=start_str_us, end=end_str_us, interval="1m")
            if not df.empty:
                df = df.tz_convert(US_TZ)

        if df.empty:
            return {'status': 'NO DATA', 'reason': 'No historical data available',
                    'actual_high': None, 'actual_low': None, 'exit_date': None}

        # Filter to only include data AFTER entry time
        df_after = df[df.index >= ts]

        if df_after.empty:
            # Use first available data
            df_after = df

        # Limit to 48 hours from entry
        ts_end = ts + timedelta(hours=48)
        df_check = df_after[df_after.index <= ts_end]

        if df_check.empty:
            df_check = df_after

        if df_check.empty:
            return {'status': 'NO DATA', 'reason': 'No data after entry time',
                    'actual_high': None, 'actual_low': None, 'exit_date': None}

        # Get actual high/low
        actual_high = df_check['High'].max()
        actual_low = df_check['Low'].min()
        entry_price = df_check['Open'].iloc[0]
        exit_date = df_check.index[0].strftime('%Y-%m-%d')

        # Check each candle
        for idx, row in df_check.iterrows():
            high = row['High']
            low = row['Low']

            if is_short:
                # Short: GAIN when price drops to target, LOSS when rises to stop
                if low <= target:
                    return {
                        'status': 'GAIN',
                        'entry_price': entry_price,
                        'exit_price': target,
                        'time': idx.strftime('%H:%M'),
                        'exit_date': idx.strftime('%Y-%m-%d'),
                        'reason': f'SHORT: Target {target} hit at {idx.strftime("%H:%M")}',
                        'actual_high': actual_high,
                        'actual_low': actual_low
                    }
                if high >= stop:
                    return {
                        'status': 'LOSS',
                        'entry_price': entry_price,
                        'exit_price': stop,
                        'time': idx.strftime('%H:%M'),
                        'exit_date': idx.strftime('%Y-%m-%d'),
                        'reason': f'SHORT: Stop {stop} hit at {idx.strftime("%H:%M")}',
                        'actual_high': actual_high,
                        'actual_low': actual_low
                    }
            else:
                # Long: GAIN when price rises to target, LOSS when drops to stop
                if high >= target:
                    return {
                        'status': 'GAIN',
                        'entry_price': entry_price,
                        'exit_price': target,
                        'time': idx.strftime('%H:%M'),
                        'exit_date': idx.strftime('%Y-%m-%d'),
                        'reason': f'LONG: Target {target} hit at {idx.strftime("%H:%M")}',
                        'actual_high': actual_high,
                        'actual_low': actual_low
                    }
                if low <= stop:
                    return {
                        'status': 'LOSS',
                        'entry_price': entry_price,
                        'exit_price': stop,
                        'time': idx.strftime('%H:%M'),
                        'exit_date': idx.strftime('%Y-%m-%d'),
                        'reason': f'LONG: Stop {stop} hit at {idx.strftime("%H:%M")}',
                        'actual_high': actual_high,
                        'actual_low': actual_low
                    }

        # Neither hit - pending
        last_price = df_check['Close'].iloc[-1]
        return {
            'status': 'PENDING',
            'entry_price': entry_price,
            'exit_price': last_price,
            'time': df_check.index[-1].strftime('%H:%M'),
            'exit_date': df_check.index[-1].strftime('%Y-%m-%d'),
            'reason': f'Neither hit. Last: {last_price:.2f}',
            'actual_high': actual_high,
            'actual_low': actual_low
        }

    except Exception as e:
        return {'status': 'ERROR', 'reason': str(e),
                'actual_high': None, 'actual_low': None, 'exit_date': None}


def load_backtest_recommendations(portfolio_files: list) -> list:
    """Load recommendations from backtest portfolio files"""
    recs = []
    seen = set()  # For deduplication by code+entry (keep first only)

    for filepath in portfolio_files:
        try:
            with open(filepath) as f:
                data = json.load(f)

            for r in data.get('results', []):
                recommendation = r.get('recommendation', '')
                if recommendation in ['BUY', 'SELL']:
                    code = r.get('code', '')

                    if code.isdigit():
                        code = f"{code}.HK"
                    elif not code.endswith('.HK') and not any(c.isalpha() for c in code):
                        code = f"{code}.HK"

                    entry = r.get('entry', 0)
                    # Dedup by code + entry price (keep first occurrence)
                    unique_key = (code, entry)

                    # Skip duplicates
                    if unique_key in seen:
                        continue
                    seen.add(unique_key)

                    timestamp = r.get('timestamp', '')
                    analysis = r.get('analysis', {})
                    recs.append({
                        'code': code,
                        'recommendation': recommendation,
                        'entry': entry,
                        'stop': r.get('stop', 0),
                        'target': r.get('target', 0),
                        'timestamp': timestamp,
                        'confidence': r.get('confidence', 'LOW'),
                        'stock_name': r.get('stock_name', ''),
                        'rec_price': analysis.get('price', 0),
                    })
        except Exception as e:
            print(f"Error loading {filepath}: {e}")

    return recs


def verify_backtest_trades(recs: list, verbose: bool = True) -> pd.DataFrame:
    """Verify all backtest trades"""
    results = []

    for i, rec in enumerate(recs, 1):
        entry = rec.get('entry', 0)
        stop = rec.get('stop', 0)
        target = rec.get('target', 0)
        rec_type = rec.get('recommendation', 'BUY')
        code = rec['code']

        # Determine timezone suffix
        tz_suffix = "HKT" if is_hk_stock(code) else "EDT"

        if not entry or not stop or not target:
            if verbose:
                print(f"{i:2d}. {code:<12} → ⚠️ INVALID (missing entry/stop/target)")
            results.append({
                'index': i,
                'code': code,
                'recommendation': rec_type,
                'entry_rec': entry,
                'stop': stop,
                'target': target,
                'status': 'INVALID',
                'gain_loss_pct': None,
                'time': None,
                'exit_date': None,
                'timestamp': rec['timestamp'],
                'tz': tz_suffix,
                'reason': 'Missing entry/stop/target',
            })
            continue

        result = check_backtest_trade(
            code,
            entry,
            stop,
            target,
            rec['timestamp'],
            is_short=(rec_type == 'SELL')
        )

        # Calculate gain/loss
        gl_pct = None
        rec_entry = rec.get('entry', 0)
        if rec_entry and result.get('exit_price'):
            if result['status'] == 'GAIN':
                if rec_type == 'BUY':
                    gl_pct = ((result['exit_price'] - rec_entry) / rec_entry) * 100
                else:  # SELL
                    gl_pct = ((rec_entry - result['exit_price']) / rec_entry) * 100
            elif result['status'] == 'LOSS':
                if rec_type == 'BUY':
                    gl_pct = ((result['exit_price'] - rec_entry) / rec_entry) * 100
                else:  # SELL
                    gl_pct = ((rec_entry - result['exit_price']) / rec_entry) * 100

        results.append({
            'code': code,
            'recommendation': rec_type,
            'entry_datetime': rec['timestamp'],
            'exit_datetime': f"{result.get('exit_date', '')} {result.get('time', '')}".strip(),
            'timezone': tz_suffix,
            'entry_price': rec['entry'],
            'exit_price': result.get('exit_price'),
            'status': result.get('status'),
            'gain_loss_pct': gl_pct,
        })

        if verbose:
            # Format entry_datetime
            entry_datetime = rec.get('timestamp', '')[:19] if rec.get('timestamp') else 'N/A'

            # Format exit_datetime
            exit_datetime = ''
            if result.get('exit_date') and result.get('time'):
                exit_datetime = f"{result.get('exit_date')} {result.get('time', '')}"

            gl_str = f"{gl_pct:+.2f}%" if gl_pct is not None else "N/A"
            exit_price_str = f"{result.get('exit_price', 0):.2f}" if result.get('exit_price') else "N/A"

            print(f"{i:2d}. {code:<12} {rec_type:<6} {entry_datetime:<19} {exit_datetime:<16} "
                  f"{tz_suffix:<4} ${rec['entry']:>8.2f} ${exit_price_str:>8} "
                  f"{result.get('status', 'ERROR'):<10} {gl_str:>8}")

    return pd.DataFrame(results)


def print_summary(df: pd.DataFrame):
    """Print summary statistics"""
    print("\n" + "=" * 60)
    print("BACKTEST SUMMARY")
    print("=" * 60)

    closed = df[df['status'].isin(['GAIN', 'LOSS'])]
    pending = df[df['status'] == 'PENDING']
    invalid = df[df['status'] == 'INVALID']

    gains = len(closed[closed['status'] == 'GAIN'])
    losses = len(closed[closed['status'] == 'LOSS'])

    total_closed = gains + losses
    win_rate = (gains / total_closed * 100) if total_closed > 0 else 0

    avg_gain = closed[closed['status'] == 'GAIN']['gain_loss_pct'].mean() if gains > 0 else 0
    avg_loss = closed[closed['status'] == 'LOSS']['gain_loss_pct'].mean() if losses > 0 else 0

    print(f"\nResults:")
    print(f"  GAIN (Target hit first):    {gains}")
    print(f"  LOSS (Stop hit first):      {losses}")
    print(f"  PENDING (neither hit):      {len(pending)}")
    print(f"  INVALID:                    {len(invalid)}")
    print(f"\nWin Rate: {win_rate:.1f}% ({gains}/{total_closed})")
    print(f"Average GAIN: {avg_gain:+.2f}%")
    print(f"Average LOSS: {avg_loss:+.2f}%")

    # By direction
    buy_recs = df[df['recommendation'] == 'BUY']
    sell_recs = df[df['recommendation'] == 'SELL']

    buy_closed = buy_recs[buy_recs['status'].isin(['GAIN', 'LOSS'])]
    sell_closed = sell_recs[sell_recs['status'].isin(['GAIN', 'LOSS'])]

    print(f"\nBy Direction:")
    print(f"  BUY (Long):  {len(buy_closed[buy_closed['status']=='GAIN'])}/{len(buy_closed)} wins")
    print(f"  SELL (Short): {len(sell_closed[sell_closed['status']=='GAIN'])}/{len(sell_closed)} wins")


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Verify backtest trades')
    parser.add_argument('files', nargs='*', help='Portfolio JSON files to verify')
    parser.add_argument('-d', '--dir', default='backtest', help='Directory with portfolio files')
    parser.add_argument('-o', '--output', help='Output CSV file')
    args = parser.parse_args()

    # Get files from directory or command line
    if args.files:
        files = args.files
    else:
        files = glob.glob(f'{args.dir}/portfolio_*.json')
        files = [f for f in files if 'backtest' not in f]  # Exclude this script's output

    if not files:
        print(f"No portfolio files found in {args.dir}/")
        print("Usage: python verify_trades_backtest.py [files] or -d <directory>")
        sys.exit(1)

    print(f"Loading recommendations from {len(files)} files...")

    recs = load_backtest_recommendations(files)
    print(f"Found {len(recs)} recommendations\n")

    print("Verifying trades...")
    df = verify_backtest_trades(recs)

    print_summary(df)

    if args.output:
        df.to_csv(args.output, index=False)
        print(f"\nResults saved to {args.output}")


if __name__ == '__main__':
    main()