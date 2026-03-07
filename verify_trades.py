#!/usr/bin/env python3
"""
Trade Verification Script
Analyzes BUY recommendations from portfolio JSON files and verifies
whether target or stop was hit first using minute-by-minute historical data.
"""

import pandas as pd
from datetime import datetime, timedelta
import pytz
import glob
import json
import sys
import time
import requests

# Timezones
HK_TZ = pytz.timezone('Asia/Hong_Kong')
US_TZ = pytz.timezone('US/Eastern')

# iTick API
ITICK_TOKEN = "f7c4e856149740a9b3149ad9fbbbbce33f8c7fa9b36244ebbaceaad5f530ab85"
ITICK_BASE_URL = "https://api.itick.org"


def is_hk_stock(code: str) -> bool:
    """Check if stock code is HK market"""
    # HK stocks have .HK suffix or are pure digits (e.g., "3690", "100")
    return code.endswith('.HK') or (code.isdigit() and len(code) <= 5)


def itick_request(endpoint: str, params: dict, delay: float = 1.0) -> dict:
    """Make request to iTick API with rate limiting"""
    time.sleep(delay)
    url = f"{ITICK_BASE_URL}{endpoint}"
    headers = {"token": ITICK_TOKEN}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        print(f"  iTick error: {e}")
    return None


def get_itick_klines(code: str, region: str, ktype: int = 2, limit: int = 100) -> pd.DataFrame:
    """Get kline data from iTick and convert to DataFrame"""
    # ktype: 1=1m, 2=5m, 3=15m, 4=30m, 5=60m
    data = itick_request("/stock/klines", {"region": region, "codes": code, "kType": ktype, "limit": limit})

    # Response format: {"code": 0, "data": {"CODE": [...]}}
    if not data or data.get('code') != 0 or 'data' not in data:
        return pd.DataFrame()

    data_dict = data.get('data', {})
    klines = data_dict.get(code.upper(), [])
    if not klines:
        # Try lowercase
        klines = data_dict.get(code.lower(), [])

    if not klines:
        return pd.DataFrame()

    # Convert to DataFrame
    df = pd.DataFrame(klines)
    if 't' in df.columns:
        # iTick returns timestamps in milliseconds since epoch
        # First try milliseconds, if that fails use seconds
        try:
            df['datetime'] = pd.to_datetime(df['t'], unit='ms')
        except Exception:
            try:
                df['datetime'] = pd.to_datetime(df['t'], unit='s')
            except Exception as e:
                print(f"  Timestamp parse error: {e}")
                return pd.DataFrame()

        df.set_index('datetime', inplace=True)
        # Add timezone - iTick returns HK time
        df.index = df.index.tz_localize(HK_TZ)
        # Convert to OHLC format
        df = df.rename(columns={'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume'})
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']]

    return df


def check_trade_result(code: str, entry: float, stop: float, target: float,
                       timestamp: str) -> dict:
    """
    Check which level was hit first: target (gain) or stop (loss)
    Uses Yahoo for historical data (both HK and US) - has 8 days of history

    Returns:
        dict with status (GAIN/LOSS/PENDING/ERROR), entry_price, exit_price, time, reason
    """
    try:
        import yfinance as yf

        if is_hk_stock(code):
            # HK stock - use Yahoo with .HK suffix
            ticker = yf.Ticker(code)
            return check_hk_trade(ticker, entry, stop, target, timestamp)
        else:
            # US stock - use Yahoo
            ticker = yf.Ticker(code)
            return check_us_trade(ticker, entry, stop, target, timestamp)

    except Exception as e:
        return {'status': 'ERROR', 'reason': str(e)}


def check_hk_trade_itick(code: str, entry: float, stop: float, target: float,
                          timestamp: str) -> dict:
    """Check HK stock trade result using iTick"""
    try:
        # Parse timestamp in HK time
        ts = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        ts = HK_TZ.localize(ts)

        # Get 5-minute klines from iTick
        df = get_itick_klines(code, "HK", ktype=2, limit=200)

        if df.empty:
            return {'status': 'NO DATA', 'reason': 'No data from iTick'}

        # Filter from entry time onwards
        df = df[df.index >= ts]

        if df.empty:
            return {'status': 'NO DATA AFTER', 'reason': 'No data after entry time'}

        # Use first available data as entry
        entry_price = df['Open'].iloc[0]

        # Check candle by candle
        for idx, row in df.iterrows():
            high = row['High']
            low = row['Low']

            if low <= stop:
                return {
                    'status': 'LOSS',
                    'entry_price': entry_price,
                    'exit_price': stop,
                    'time': idx.strftime('%H:%M'),
                    'reason': f'Stop {stop} hit at {idx.strftime("%H:%M")}'
                }

            if high >= target:
                return {
                    'status': 'GAIN',
                    'entry_price': entry_price,
                    'exit_price': target,
                    'time': idx.strftime('%H:%M'),
                    'reason': f'Target {target} hit at {idx.strftime("%H:%M")}'
                }

        # Neither hit - pending
        last_price = df['Close'].iloc[-1]
        return {
            'status': 'PENDING',
            'entry_price': entry_price,
            'exit_price': last_price,
            'time': df.index[-1].strftime('%H:%M'),
            'reason': f'Neither hit. Last: {last_price:.2f}'
        }

    except Exception as e:
        return {'status': 'ERROR', 'reason': str(e)}


def check_us_trade_itick(code: str, entry: float, stop: float, target: float,
                         timestamp: str) -> dict:
    """Check US stock trade result using iTick"""
    try:
        # Parse timestamp in HK time
        ts = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        ts = HK_TZ.localize(ts)

        # Get 5-minute klines from iTick US region
        df = get_itick_klines(code, "US", ktype=2, limit=200)

        if df.empty:
            return {'status': 'NO DATA', 'reason': 'No data from iTick'}

        # Filter from entry time onwards
        df = df[df.index >= ts]

        if df.empty:
            return {'status': 'NO DATA AFTER', 'reason': 'No data after entry time'}

        # Use first available data as entry
        entry_price = df['Open'].iloc[0]

        # Check candle by candle
        for idx, row in df.iterrows():
            high = row['High']
            low = row['Low']

            if low <= stop:
                return {
                    'status': 'LOSS',
                    'entry_price': entry_price,
                    'exit_price': stop,
                    'time': idx.strftime('%H:%M'),
                    'reason': f'Stop {stop} hit at {idx.strftime("%H:%M")}'
                }

            if high >= target:
                return {
                    'status': 'GAIN',
                    'entry_price': entry_price,
                    'exit_price': target,
                    'time': idx.strftime('%H:%M'),
                    'reason': f'Target {target} hit at {idx.strftime("%H:%M")}'
                }

        # Neither hit - pending
        last_price = df['Close'].iloc[-1]
        return {
            'status': 'PENDING',
            'entry_price': entry_price,
            'exit_price': last_price,
            'time': df.index[-1].strftime('%H:%M'),
            'reason': f'Neither hit. Last: {last_price:.2f}'
        }

    except Exception as e:
        return {'status': 'ERROR', 'reason': str(e)}


def check_hk_trade(ticker, entry: float, stop: float, target: float,
                    timestamp: str) -> dict:
    """Check HK stock trade result"""
    try:
        # Parse timestamp in HK time
        ts = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        ts = HK_TZ.localize(ts)

        df = ticker.history(period="8d", interval="1m")

        if df.empty:
            return {'status': 'NO DATA', 'reason': 'No data returned'}

        # Filter to only include data from entry time onwards
        df = df[df.index >= ts]

        if df.empty:
            return {'status': 'NO DATA AFTER', 'reason': 'No data after entry time'}

        # Get entry price
        entry_price = df['Open'].iloc[0]

        # Check minute by minute
        for idx, row in df.iterrows():
            high = row['High']
            low = row['Low']

            # Check if stop was hit first
            if low <= stop:
                return {
                    'status': 'LOSS',
                    'entry_price': entry_price,
                    'exit_price': stop,
                    'time': idx.strftime('%H:%M'),
                    'reason': f'Stop {stop} hit at {idx.strftime("%H:%M")}'
                }

            # Check if target was hit first
            if high >= target:
                return {
                    'status': 'GAIN',
                    'entry_price': entry_price,
                    'exit_price': target,
                    'time': idx.strftime('%H:%M'),
                    'reason': f'Target {target} hit at {idx.strftime("%H:%M")}'
                }

        # Neither hit - pending
        last_price = df['Close'].iloc[-1]
        return {
            'status': 'PENDING',
            'entry_price': entry_price,
            'exit_price': last_price,
            'time': df.index[-1].strftime('%H:%M'),
            'reason': f'Neither hit. Last: {last_price:.2f}'
        }

    except Exception as e:
        return {'status': 'ERROR', 'reason': str(e)}


def check_us_trade(ticker, entry: float, stop: float, target: float,
                    timestamp: str) -> dict:
    """Check US stock trade result - check from entry time onwards"""
    try:
        # Parse timestamp in HK time and convert to US Eastern
        ts = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        ts = HK_TZ.localize(ts)
        # Convert to US/Eastern for filtering
        ts_us = ts.astimezone(US_TZ)

        df = ticker.history(period="8d", interval="1m")

        if df.empty:
            return {'status': 'NO DATA', 'reason': 'No data returned'}

        # Filter from entry time onwards
        df = df[df.index >= ts_us]

        if df.empty:
            return {'status': 'NO DATA AFTER', 'reason': 'No data after entry time'}

        # Filter for regular trading hours (09:30-16:00 US ET)
        df = df[(df.index.hour >= 9) & (df.index.hour <= 16)]

        if df.empty:
            return {'status': 'NO TRADING HOURS', 'reason': 'No data in trading hours'}

        # Use first available data as entry
        entry_price = df['Open'].iloc[0]

        # Check minute by minute
        for idx, row in df.iterrows():
            high = row['High']
            low = row['Low']

            if low <= stop:
                return {
                    'status': 'LOSS',
                    'entry_price': entry_price,
                    'exit_price': stop,
                    'time': idx.strftime('%H:%M'),
                    'reason': f'Stop {stop} hit at {idx.strftime("%H:%M")}'
                }

            if high >= target:
                return {
                    'status': 'GAIN',
                    'entry_price': entry_price,
                    'exit_price': target,
                    'time': idx.strftime('%H:%M'),
                    'reason': f'Target {target} hit at {idx.strftime("%H:%M")}'
                }

        # Neither hit - pending
        last_price = df['Close'].iloc[-1]
        return {
            'status': 'PENDING',
            'entry_price': entry_price,
            'exit_price': last_price,
            'time': df.index[-1].strftime('%H:%M'),
            'reason': f'Neither hit. Last: {last_price:.2f}'
        }

    except Exception as e:
        return {'status': 'ERROR', 'reason': str(e)}


def load_buy_recommendations(portfolio_files: list) -> list:
    """
    Load all BUY recommendations from portfolio JSON files.

    Returns list of dicts with: code, entry, stop, target, timestamp
    """
    buy_recs = []

    for filepath in portfolio_files:
        try:
            with open(filepath) as f:
                data = json.load(f)

            for r in data.get('results', []):
                if r.get('recommendation') == 'BUY':
                    code = r.get('code', '')

                    # Normalize HK stock codes
                    # e.g., "3690" -> "3690.HK", "100" -> "100.HK"
                    if code.isdigit():
                        code = f"{code}.HK"
                    # Already has .HK or is US stock
                    elif not code.endswith('.HK') and not any(c.isalpha() for c in code):
                        code = f"{code}.HK"

                    buy_recs.append({
                        'code': code,
                        'entry': r.get('entry', 0),
                        'stop': r.get('stop', 0),
                        'target': r.get('target', 0),
                        'timestamp': r.get('timestamp', ''),
                        'confidence': r.get('confidence', 'LOW'),
                        'stock_name': r.get('stock_name', ''),
                    })
        except Exception as e:
            print(f"Error loading {filepath}: {e}")

    return buy_recs


def verify_trades(buy_recs: list, verbose: bool = True) -> pd.DataFrame:
    """
    Verify all trades and return results as DataFrame
    """
    results = []

    for i, rec in enumerate(buy_recs, 1):
        result = check_trade_result(
            rec['code'],
            rec['entry'],
            rec['stop'],
            rec['target'],
            rec['timestamp']
        )

        # Calculate Gain/Loss % based on RECOMMENDED entry price
        gl_pct = None
        rec_entry = rec.get('entry', 0)
        if rec_entry and result.get('exit_price'):
            if result['status'] == 'GAIN':
                # Target was hit - profit = target - recommended entry
                gl_pct = ((result['exit_price'] - rec_entry) / rec_entry) * 100
            elif result['status'] == 'LOSS':
                # Stop was hit - loss = stop - recommended entry
                gl_pct = ((result['exit_price'] - rec_entry) / rec_entry) * 100

        # Extract date from timestamp
        date = rec['timestamp'].split()[0] if rec['timestamp'] else ''

        results.append({
            'index': i,
            'code': rec['code'],
            'name': rec['stock_name'],
            'entry_rec': rec['entry'],
            'stop': rec['stop'],
            'target': rec['target'],
            'entry_actual': result.get('entry_price'),
            'exit_price': result.get('exit_price'),
            'status': result.get('status'),
            'gain_loss_pct': gl_pct,
            'time': result.get('time'),
            'entry_time': rec['timestamp'].split()[1] if rec['timestamp'] else '',
            'date': date,
            'timestamp': rec['timestamp'],
            'confidence': rec['confidence'],
            'reason': result.get('reason'),
        })

        if verbose:
            status_symbol = {
                'GAIN': '🎯',
                'LOSS': '❌',
                'PENDING': '⏳',
                'ERROR': '⚠️',
            }.get(result.get('status', '?'), '?')

            gl_str = f"{gl_pct:+.1f}%" if gl_pct is not None else "N/A"

            print(f"{i:2d}. {rec['code']:<12} Entry: ${rec['entry']:>7.2f} "
                  f"Stop: ${rec['stop']:>6.2f} Target: ${rec['target']:>7.2f} "
                  f"→ {status_symbol} {result.get('status', 'ERROR'):<8} "
                  f"({gl_str})")

    return pd.DataFrame(results)


def print_summary(df: pd.DataFrame, detailed: bool = False):
    """Print summary statistics"""
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)

    if detailed:
        print(f"{'#':<3} {'Code':<10} {'Entry':>8} {'Stop':>7} {'Target':>8} {'Act Entry':>10} {'Exit':>8} {'Status':<8} {'G/L %':>8} {'EntryTime':>10} {'TimeHit':>8} {'Date':>12}")
        print("-" * 115)
        for _, row in df.iterrows():
            gl = f"{row['gain_loss_pct']:+.1f}%" if pd.notna(row['gain_loss_pct']) else "N/A"
            act_entry = f"${row['entry_actual']:.2f}" if row['entry_actual'] else "N/A"
            exit_p = f"${row['exit_price']:.2f}" if row['exit_price'] else "N/A"
            print(f"{row['index']:<3} {row['code']:<10} ${row['entry_rec']:>7.2f} ${row['stop']:>6.2f} ${row['target']:>7.2f} {act_entry:>10} {exit_p:>8} {row['status']:<8} {gl:>8} {row['entry_time']:>10} {row['time'] or 'N/A':>8} {row['date']:>12}")
        print("-" * 115)

    # Filter to only closed trades (GAIN or LOSS)
    closed = df[df['status'].isin(['GAIN', 'LOSS'])]
    pending = df[df['status'] == 'PENDING']
    errors = df[~df['status'].isin(['GAIN', 'LOSS', 'PENDING'])]

    gains = len(closed[closed['status'] == 'GAIN'])
    losses = len(closed[closed['status'] == 'LOSS'])

    total_closed = gains + losses
    win_rate = (gains / total_closed * 100) if total_closed > 0 else 0

    # Calculate average gain/loss
    avg_gain = closed[closed['status'] == 'GAIN']['gain_loss_pct'].mean() if gains > 0 else 0
    avg_loss = closed[closed['status'] == 'LOSS']['gain_loss_pct'].mean() if losses > 0 else 0

    print(f"\nResults:")
    print(f"  GAIN (Target hit first):    {gains}")
    print(f"  LOSS (Stop hit first):      {losses}")
    print(f"  PENDING (neither hit):       {len(pending)}")
    print(f"  ERRORS:                     {len(errors)}")
    print(f"\nWin Rate (closed trades): {win_rate:.1f}% ({gains}/{total_closed})")
    print(f"Average GAIN: {avg_gain:+.2f}%")
    print(f"Average LOSS: {avg_loss:+.2f}%")

    # By market
    hk_df = df[df['code'].str.endswith('.HK', na=False)]
    us_df = df[~df['code'].str.endswith('.HK', na=False)]

    hk_closed = hk_df[hk_df['status'].isin(['GAIN', 'LOSS'])]
    us_closed = us_df[us_df['status'].isin(['GAIN', 'LOSS'])]

    print(f"\nBy Market:")
    print(f"  HK Stocks: {len(hk_closed[hk_closed['status']=='GAIN'])}/{len(hk_closed)} wins ({len(hk_closed[hk_closed['status']=='GAIN'])/len(hk_closed)*100 if len(hk_closed)>0 else 0:.1f}%)")
    print(f"  US Stocks: {len(us_closed[us_closed['status']=='GAIN'])}/{len(us_closed)} wins ({len(us_closed[us_closed['status']=='GAIN'])/len(us_closed)*100 if len(us_closed)>0 else 0:.1f}%)")


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Verify trade recommendations')
    parser.add_argument('files', nargs='*', help='Portfolio JSON files to analyze')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
    parser.add_argument('-d', '--detailed', action='store_true', help='Show detailed table')
    parser.add_argument('-o', '--output', help='Output CSV file')
    args = parser.parse_args()

    # Default to today's portfolio files if no files specified
    if not args.files:
        args.files = glob.glob('portfolio_2026-03-*.json')
        if not args.files:
            print("No portfolio files found. Usage: python verify_trades.py <portfolio_json_files>")
            sys.exit(1)

    print(f"Loading BUY recommendations from {len(args.files)} files...")

    buy_recs = load_buy_recommendations(args.files)
    print(f"Found {len(buy_recs)} BUY recommendations\n")

    print("Verifying trades...")
    df = verify_trades(buy_recs, verbose=args.verbose)

    print_summary(df, detailed=args.detailed)

    if args.output:
        df.to_csv(args.output, index=False)
        print(f"\nResults saved to {args.output}")


if __name__ == '__main__':
    main()
