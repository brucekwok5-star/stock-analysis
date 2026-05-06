#!/usr/bin/env python3
"""
Batch Backtest Runner
Run backtest across a date/time range to generate statistical sample of recommendations.
Usage:
    python run_backtest_batch.py 700 2026-05-01 2026-05-06 -o backtest/batch-results
    python run_backtest_batch.py nvda 2026-05-01 2026-05-06 --interval 1h -o backtest/batch-results
"""

import warnings
warnings.filterwarnings('ignore')
import logging
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

import sys
import os
import argparse
import json
from datetime import datetime, timedelta
import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backtest.stock_analysis_backtest import run_backtest

HKT = pytz.timezone('Asia/Hong_Kong')


def parse_args():
    parser = argparse.ArgumentParser(description='Batch backtest runner')
    parser.add_argument('code', help='Stock code (e.g., 700, nvda)')
    parser.add_argument('start', help='Start date YYYY-MM-DD')
    parser.add_argument('end', help='End date YYYY-MM-DD (inclusive)')
    parser.add_argument('-o', '--output', default='backtest/batch-results', help='Output dir')
    parser.add_argument('--interval', default='1h', choices=['1h', '30m', '15m', '5m'],
                        help='Check interval (default: 1h)')
    parser.add_argument('--hours', default='9:30-16:00', help='Trading hours window (default: 9:30-16:00 HKT)')
    parser.add_argument('-y', '--yfinance', action='store_true', help='Use yfinance for data')
    return parser.parse_args()


def parse_trading_hours(hours_str: str) -> tuple:
    """Parse '9:30-16:00' into (start_h, start_m, end_h, end_m)."""
    start_str, end_str = hours_str.split('-')
    sh, sm = map(int, start_str.split(':'))
    eh, em = map(int, end_str.split(':'))
    return (sh, sm), (eh, em)


def gen_check_times(start_date: str, end_date: str, interval_hours: float,
                    trading_hours: tuple) -> list:
    """Generate checkpoint datetimes within trading hours."""
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    times = []
    (sh, sm), (eh, em) = trading_hours

    cur = start_dt
    while cur <= end_dt:
        for h in range(sh, eh):
            for m in [0, 60 - int(interval_hours * 60)] if interval_hours >= 1 else [0]:
                dt = HKT.localize(datetime(cur.year, cur.month, cur.day, h, m))
                if dt.hour == h and (interval_hours < 1 or dt.minute == 0):
                    if interval_hours >= 1:
                        for minute in range(0, 60, int(interval_hours * 60)):
                            dt = HKT.localize(datetime(cur.year, cur.month, cur.day, h, minute))
                            times.append(dt)
                    else:
                        times.append(dt)
        cur += timedelta(days=1)
    return times


def main():
    args = parse_args()

    # Parse interval
    interval_map = {'1h': 1, '30m': 0.5, '15m': 0.25, '5m': 5/60}
    interval_h = interval_map[args.interval]

    (sh, sm), (eh, em) = parse_trading_hours(args.hours)

    # Generate times: every `interval` hours during trading session
    times = []
    start_dt = datetime.strptime(args.start, '%Y-%m-%d')
    end_dt = datetime.strptime(args.end, '%Y-%m-%d')
    cur = start_dt

    while cur <= end_dt:
        for h in range(sh, eh + 1):
            minute_step = int(interval_h * 60)
            for minute in range(0, 60, minute_step):
                dt = HKT.localize(datetime(cur.year, cur.month, cur.day, h, minute))
                if h == eh and minute > em:
                    break
                if dt.hour >= sh and dt.hour <= eh:
                    times.append(dt)
        cur += timedelta(days=1)

    if not times:
        print("No times generated — check date range and interval.")
        return

    print(f"\n📊 Batch backtest: {args.code}")
    print(f"   Period: {args.start} → {args.end}")
    print(f"   Interval: every {args.interval}")
    print(f"   Trading hours: {args.hours} HKT")
    print(f"   Total checkpoints: {len(times)}")
    print(f"   Output: {args.output}")
    print(f"\n{'='*60}")

    os.makedirs(args.output, exist_ok=True)

    results = []
    for i, dt in enumerate(times):
        ts_str = dt.strftime('%Y-%m-%d %H:%M')
        print(f"\n[{i+1}/{len(times)}] {ts_str}", end='', flush=True)

        rec = run_backtest(args.code, ts_str, args.output, use_yfinance=args.yfinance)

        if rec:
            rec['_checkpoint'] = ts_str
            results.append(rec)
            print(f" → {rec.get('recommendation', '?')}", end='')
        else:
            print(f" → NO DATA", end='')

    # Summary
    if not results:
        print("\n\n❌ No results generated.")
        return

    print(f"\n\n{'='*60}")
    print(f"  BATCH SUMMARY: {args.code}")
    print(f"{'='*60}")

    total = len(results)
    buys = sum(1 for r in results if r.get('recommendation') == 'BUY')
    sells = sum(1 for r in results if r.get('recommendation') == 'SELL')
    holds = sum(1 for r in results if r.get('recommendation') == 'HOLD')
    highs = sum(1 for r in results if r.get('confidence') == 'HIGH')

    print(f"  Total checkpoints:  {total}")
    print(f"  BUY:  {buys} ({buys/total*100:.0f}%)")
    print(f"  SELL: {sells} ({sells/total*100:.0f}%)")
    print(f"  HOLD: {holds} ({holds/total*100:.0f}%)")
    print(f"  HIGH confidence:   {highs} ({highs/total*100:.0f}%)")

    # Save summary
    summary_file = os.path.join(args.output, f"batch_summary_{args.code}_{args.start}_{args.end}.json")
    with open(summary_file, 'w') as f:
        json.dump({
            'code': args.code,
            'start': args.start,
            'end': args.end,
            'interval': args.interval,
            'total_checkpoints': total,
            'BUY': buys,
            'SELL': sells,
            'HOLD': holds,
            'HIGH_confidence': highs,
            'BUY_pct': round(buys/total*100, 1),
            'SELL_pct': round(sells/total*100, 1),
            'results': results
        }, f, indent=2, default=str)
    print(f"\n  ✅ Summary saved: {summary_file}")


if __name__ == '__main__':
    main()
