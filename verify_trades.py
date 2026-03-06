#!/usr/bin/env python3
"""
Trade Verification Script
Analyzes BUY recommendations from portfolio JSON files and verifies
whether target or stop was hit first using minute-by-minute historical data.
"""

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import pytz
import glob
import json
import sys

# Timezones
HK_TZ = pytz.timezone('Asia/Hong_Kong')
US_TZ = pytz.timezone('US/Eastern')


def is_hk_stock(code: str) -> bool:
    """Check if stock code is HK market"""
    # HK stocks have .HK suffix or are pure digits (e.g., "3690", "100")
    return code.endswith('.HK') or (code.isdigit() and len(code) <= 5)


def check_trade_result(code: str, entry: float, stop: float, target: float,
                       timestamp: str) -> dict:
    """
    Check which level was hit first: target (gain) or stop (loss)

    Returns:
        dict with status (GAIN/LOSS/PENDING/ERROR), entry_price, exit_price, time, reason
    """
    try:
        t = yf.Ticker(code)

        if is_hk_stock(code):
            return check_hk_trade(t, entry, stop, target, timestamp)
        else:
            return check_us_trade(t, entry, stop, target, timestamp)

    except Exception as e:
        return {'status': 'ERROR', 'reason': str(e)}


def check_hk_trade(ticker, entry: float, stop: float, target: float,
                    timestamp: str) -> dict:
    """Check HK stock trade result"""
    try:
        # Parse timestamp in HK time
        ts = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        ts = HK_TZ.localize(ts)

        df = ticker.history(period="1d", interval="1m")

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
    """Check US stock trade result"""
    try:
        df = ticker.history(period="1d", interval="1m")

        if df.empty:
            return {'status': 'NO DATA', 'reason': 'No data returned'}

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
            'time': result.get('time'),
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

            print(f"{i:2d}. {rec['code']:<12} Entry: ${rec['entry']:>7.2f} "
                  f"Stop: ${rec['stop']:>6.2f} Target: ${rec['target']:>7.2f} "
                  f"→ {status_symbol} {result.get('status', 'ERROR'):<8} "
                  f"({result.get('reason', '')[:40]})")

    return pd.DataFrame(results)


def print_summary(df: pd.DataFrame):
    """Print summary statistics"""
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    # Filter to only closed trades (GAIN or LOSS)
    closed = df[df['status'].isin(['GAIN', 'LOSS'])]
    pending = df[df['status'] == 'PENDING']
    errors = df[~df['status'].isin(['GAIN', 'LOSS', 'PENDING'])]

    gains = len(closed[closed['status'] == 'GAIN'])
    losses = len(closed[closed['status'] == 'LOSS'])

    total_closed = gains + losses
    win_rate = (gains / total_closed * 100) if total_closed > 0 else 0

    print(f"\nResults:")
    print(f"  GAIN (Target hit first):    {gains}")
    print(f"  LOSS (Stop hit first):      {losses}")
    print(f"  PENDING (neither hit):       {len(pending)}")
    print(f"  ERRORS:                     {len(errors)}")
    print(f"\nWin Rate (closed trades): {win_rate:.1f}% ({gains}/{total_closed})")

    # By market
    hk_df = df[df['code'].str.endswith('.HK')]
    us_df = df[~df['code'].str.endswith('.HK')]

    print(f"\nBy Market:")
    print(f"  HK Stocks: {len(hk_df[hk_df['status']=='GAIN'])}/{len(hk_df[hk_df['status'].isin(['GAIN','LOSS'])])} wins")
    print(f"  US Stocks: {len(us_df[us_df['status']=='GAIN'])}/{len(us_df[us_df['status'].isin(['GAIN','LOSS'])])} wins")


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Verify trade recommendations')
    parser.add_argument('files', nargs='*', help='Portfolio JSON files to analyze')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')
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

    print_summary(df)

    if args.output:
        df.to_csv(args.output, index=False)
        print(f"\nResults saved to {args.output}")


if __name__ == '__main__':
    main()
