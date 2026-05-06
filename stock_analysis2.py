#!/usr/bin/env python3
"""
Stock Backtest Script
Find historical recommendation and calculate gain/loss until now.
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime

import yfinance as yf


def find_portfolio_file(timestamp_str):
    """Find the portfolio file that matches or is closest to the given timestamp."""
    # Parse input timestamp
    input_ts = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

    # Get all portfolio files
    pattern = os.path.join(os.path.dirname(__file__), "portfolio_*.json")
    files = glob.glob(pattern)

    if not files:
        print(f"Error: No portfolio files found in {os.path.dirname(__file__)}")
        return None

    # Find closest file (by timestamp in filename)
    best_file = None
    best_diff = None

    for f in files:
        basename = os.path.basename(f)
        # Extract timestamp from filename: portfolio_2026-03-04_19-54-36.json
        ts_str = basename.replace("portfolio_", "").replace(".json", "")
        try:
            file_ts = datetime.strptime(ts_str, "%Y-%m-%d_%H-%M-%S")
            diff = abs((file_ts - input_ts).total_seconds())

            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_file = f
        except ValueError:
            continue

    return best_file


def find_stock_recommendation(portfolio_file, stock_code):
    """Find the recommendation for a specific stock in the portfolio file."""
    with open(portfolio_file, 'r') as f:
        data = json.load(f)

    portfolio_timestamp = data.get('timestamp', 'Unknown')

    for result in data.get('results', []):
        code = result.get('code', '').upper()
        if code == stock_code.upper():
            return {
                'portfolio_timestamp': portfolio_timestamp,
                'code': code,
                'stock_name': result.get('stock_name', 'Unknown'),
                'recommendation': result.get('recommendation', 'UNKNOWN'),
                'confidence': result.get('confidence', 'UNKNOWN'),
                'entry': result.get('entry', 0),
                'stop': result.get('stop', 0),
                'target': result.get('target', 0),
                'rr': result.get('rr', 'N/A'),
                'market_bias': result.get('market_bias', 'UNKNOWN'),
                'trend_strength': result.get('trend_strength', 'UNKNOWN'),
                'pattern_type': result.get('pattern_type', 'NONE'),
                'analysis': result.get('analysis', {})
            }

    return None


def get_current_price(stock_code):
    """Get the current price of a stock using yfinance."""
    # Check if it's a Hong Kong stock (numeric code)
    if stock_code.isdigit():
        ticker = yf.Ticker(f"{stock_code}.HK")
    else:
        ticker = yf.Ticker(stock_code)
    info = ticker.info

    # Try different price fields
    price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
    return price


def calculate_pnl(entry_price, current_price, recommendation):
    """Calculate profit/loss percentage."""
    if not entry_price or entry_price == 0:
        return None, None

    if recommendation.upper() == 'BUY':
        pnl_pct = ((current_price - entry_price) / entry_price) * 100
    elif recommendation.upper() == 'SELL':
        pnl_pct = ((entry_price - current_price) / entry_price) * 100
    else:
        # For HOLD, just show price change
        pnl_pct = ((current_price - entry_price) / entry_price) * 100

    pnl_value = current_price - entry_price
    return pnl_pct, pnl_value


def main():
    parser = argparse.ArgumentParser(description='Stock Backtest Tool')
    parser.add_argument('code', help='Stock code (e.g., NFLX)')
    parser.add_argument('timestamp', help='Timestamp (e.g., "2026-03-04 19:54:36")')
    parser.add_argument('--verbose', '-v', action='store_true', help='Show detailed output')

    args = parser.parse_args()

    stock_code = args.code.upper()
    timestamp_str = args.timestamp

    print(f"\n{'='*60}")
    print(f"📊 Stock Backtest Tool")
    print(f"{'='*60}")
    print(f"Stock Code: {stock_code}")
    print(f"Timestamp:  {timestamp_str}")
    print(f"{'='*60}\n")

    # Find the portfolio file
    portfolio_file = find_portfolio_file(timestamp_str)

    if not portfolio_file:
        print("Error: Could not find a matching portfolio file.")
        sys.exit(1)

    print(f"📁 Found portfolio file: {os.path.basename(portfolio_file)}")

    # Find the stock recommendation
    recommendation = find_stock_recommendation(portfolio_file, stock_code)

    if not recommendation:
        print(f"Error: Stock {stock_code} not found in the portfolio file.")
        sys.exit(1)

    # Display recommendation details
    print(f"\n{'='*60}")
    print(f"📋 Historical Recommendation (at {recommendation['portfolio_timestamp']})")
    print(f"{'='*60}")
    print(f"Stock Name:      {recommendation['stock_name']}")
    print(f"Recommendation:  {recommendation['recommendation']}")
    print(f"Confidence:     {recommendation['confidence']}")
    print(f"Entry Price:    ${recommendation['entry']:.2f}")
    print(f"Stop Loss:      ${recommendation['stop']:.2f}" if recommendation['stop'] > 0 else "Stop Loss:      N/A")
    print(f"Target Price:   ${recommendation['target']:.2f}" if recommendation['target'] > 0 else "Target Price:   N/A")
    print(f"Risk:Reward:    {recommendation['rr']}")
    print(f"Market Bias:    {recommendation['market_bias']}")
    print(f"Trend Strength: {recommendation['trend_strength']}")
    print(f"Pattern:        {recommendation['pattern_type']}")

    analysis = recommendation.get('analysis', {})
    if analysis:
        print(f"\n📈 Technical Analysis at Time:")
        print(f"   Price:        ${analysis.get('price', 0):.2f}")
        print(f"   RSI(14):      {analysis.get('rsi', 0):.1f}")
        print(f"   EMA20:        ${analysis.get('ema20', 0):.2f}")
        print(f"   EMA50:        ${analysis.get('ema50', 0):.2f}")
        print(f"   VWAP:         ${analysis.get('vwap', 0):.2f}")
        print(f"   ATR:          {analysis.get('atr', 0):.2f}%")

    # Get current price
    print(f"\n⏳ Fetching current price...")
    current_price = get_current_price(stock_code)

    if not current_price:
        print("Error: Could not fetch current price.")
        sys.exit(1)

    print(f"💵 Current Price: ${current_price:.2f}")

    # Calculate P&L
    entry_price = recommendation['entry']
    rec_type = recommendation['recommendation']

    pnl_pct, pnl_value = calculate_pnl(entry_price, current_price, rec_type)

    print(f"\n{'='*60}")
    print(f"📈 Backtest Result (Now)")
    print(f"{'='*60}")

    if pnl_pct is not None:
        # Determine trade status based on target/stop levels
        target = recommendation.get('target', 0)
        stop = recommendation.get('stop', 0)

        if rec_type.upper() == 'BUY':
            if target > 0 and current_price >= target:
                status = "🎯 GAIN"
            elif stop > 0 and current_price <= stop:
                status = "❌ LOSS"
            else:
                status = "⏳ ON HAND"
        elif rec_type.upper() == 'SELL':
            # For SELL (short), inverse logic
            if target > 0 and current_price <= target:
                status = "🎯 GAIN"
            elif stop > 0 and current_price >= stop:
                status = "❌ LOSS"
            else:
                status = "⏳ ON HAND"
        else:
            if target > 0 and current_price >= target:
                status = "🎯 GAIN (above target)"
            elif stop > 0 and current_price <= stop:
                status = "❌ LOSS (below stop)"
            else:
                status = "⏳ ON HAND"

        print(f"Entry Price:     ${entry_price:.2f}")
        print(f"Current Price:   ${current_price:.2f}")
        print(f"P&L:             ${pnl_value:.2f} ({pnl_pct:+.2f}%)")
        print(f"Status:          {status}")

        if recommendation['stop'] > 0:
            stop_pct = ((entry_price - recommendation['stop']) / entry_price) * 100
            print(f"Stop Loss:       ${recommendation['stop']:.2f} ({stop_pct:+.2f}%)")

        if recommendation['target'] > 0:
            target_pct = ((recommendation['target'] - entry_price) / entry_price) * 100
            print(f"Target Price:    ${recommendation['target']:.2f} ({target_pct:+.2f}%)")
    else:
        print("Could not calculate P&L (no entry price)")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
