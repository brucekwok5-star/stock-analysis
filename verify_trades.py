#!/usr/bin/env python3
"""
Trade Verification Script
Analyzes BUY recommendations from portfolio JSON files and verifies
whether target or stop was hit first using minute-by-minute historical data.
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
import time
import requests
import threading
import signal

# Timezones
HK_TZ = pytz.timezone('Asia/Hong_Kong')
US_TZ = pytz.timezone('US/Eastern')

# iTick API
ITICK_TOKEN = "b63d866df7a44fd69d61c6df5a6ab1d728402fe7488445609861fa428efbda79"
ITICK_BASE_URL = "https://api0.itick.org"

# Futu API
FUTU_AVAILABLE = False
try:
    from futu import OpenQuoteContext, SubType, KLType, RET_OK
    FUTU_AVAILABLE = True
except ImportError:
    pass


# ============================================================
# Futu Client
# ============================================================
class FutuClient:
    """Futu OpenD API client for HK stocks."""

    _quote_ctx = None
    _ctx_lock = threading.Lock()

    @classmethod
    def get_quote_context(cls):
        """Get or create shared quote context."""
        with cls._ctx_lock:
            if cls._quote_ctx is None:
                cls._quote_ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
            return cls._quote_ctx

    @classmethod
    def close(cls):
        """Close the quote context."""
        with cls._ctx_lock:
            if cls._quote_ctx:
                cls._quote_ctx.close()
                cls._quote_ctx = None

    def _convert_code(self, code: str) -> str:
        """Convert stock code to Futu format. HK: 1810 -> HK.01810"""
        if code.isdigit():
            return f"HK.{code.zfill(5)}"
        else:
            return f"US.{code.upper()}"

    def get_klines(self, code: str, ktype: str = "5m", limit: int = 500) -> pd.DataFrame:
        """Fetch kline data from Futu and convert to DataFrame with timeout."""
        if not FUTU_AVAILABLE:
            return pd.DataFrame()

        kl_type_map = {
            "1m": KLType.K_1M,
            "5m": KLType.K_5M,
            "15m": KLType.K_15M,
            "30m": KLType.K_30M,
            "1h": KLType.K_60M,
            "1d": KLType.K_DAY,
        }
        kl_type = kl_type_map.get(ktype, KLType.K_5M)

        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=8)).strftime('%Y-%m-%d')

        futu_code = self._convert_code(code)

        # Use a thread with timeout to avoid hanging
        result = {'df': pd.DataFrame(), 'error': None}

        def fetch_klines():
            try:
                quote_ctx = self.get_quote_context()
                ret, data, _ = quote_ctx.request_history_kline(
                    code=futu_code,
                    start=start_date,
                    end=end_date,
                    ktype=kl_type,
                    max_count=limit
                )

                if ret == RET_OK and data is not None and len(data) > 0:
                    df = pd.DataFrame()
                    df['datetime'] = pd.to_datetime(data['time_key'].values)
                    df.set_index('datetime', inplace=True)
                    df['Open'] = data['open'].values
                    df['High'] = data['high'].values
                    df['Low'] = data['low'].values
                    df['Close'] = data['close'].values
                    df['Volume'] = data['volume'].values
                    df.index = df.index.tz_localize(HK_TZ)
                    result['df'] = df
            except Exception as e:
                result['error'] = str(e)

        # Run with 15-second timeout
        fetch_thread = threading.Thread(target=fetch_klines)
        fetch_thread.daemon = True
        fetch_thread.start()
        fetch_thread.join(timeout=15)

        if fetch_thread.is_alive():
            # Thread is still running - timed out
            return pd.DataFrame()

        if result['error']:
            return pd.DataFrame()

        return result['df']


# Global futu client
_futu_client = None


def get_futu_client() -> FutuClient:
    """Get or create Futu client."""
    global _futu_client
    if _futu_client is None and FUTU_AVAILABLE:
        _futu_client = FutuClient()
    return _futu_client


def is_hk_stock(code: str) -> bool:
    """Check if stock code is HK market"""
    # HK stocks have .HK suffix or are pure digits (e.g., "3690", "100")
    return code.endswith('.HK') or (code.isdigit() and len(code) <= 5)


def itick_request(endpoint: str, params: dict, delay: float = 1.0) -> dict:
    """Make request to iTick API with rate limiting"""
    time.sleep(delay)
    url = f"{ITICK_BASE_URL}{endpoint}"
    headers = {"token": ITICK_TOKEN, "accept": "application/json"}
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
    data = itick_request("/stock/kline", {"region": region, "code": code, "kType": ktype, "limit": limit})

    # Response format: {"code": 0, "data": [...]} - data is now a list directly
    if not data or data.get('code') != 0 or 'data' not in data:
        return pd.DataFrame()

    klines = data.get('data', [])
    if isinstance(klines, dict):
        # Legacy format: {"CODE": [...]} - try to get the code key
        klines = klines.get(code.upper(), []) or klines.get(code.lower(), [])

    if not klines or not isinstance(klines, list):
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
                       timestamp: str, recommendation: str = 'BUY',
                       use_itick: bool = False, use_futu: bool = True) -> dict:
    """
    Check which level was hit first: target (gain) or stop (loss)

    Args:
        code: Stock code
        entry: Entry price
        stop: Stop loss price
        target: Target price
        timestamp: Entry timestamp
        recommendation: 'BUY' or 'SELL' (for short positions)
        use_itick: Use iTick API for HK stocks (instead of Yahoo)
        use_futu: Use Futu API for HK stocks (default True, takes priority over itick)

    Returns:
        dict with status (GAIN/LOSS/PENDING/ERROR), entry_price, exit_price, time, reason, actual_high, actual_low
    """
    try:
        import yfinance as yf

        if is_hk_stock(code):
            # Extract HK code without suffix
            hk_code = code.replace('.HK', '') if code.endswith('.HK') else code
            hk_code = str(int(hk_code))  # Strip leading zeros

            # Retry statuses that should trigger next provider
            retry_statuses = ['NO DATA', 'NO DATA AFTER', 'ERROR']

            if use_futu and FUTU_AVAILABLE:
                # Try Futu first (best for HK) but don't hang
                try:
                    result = check_hk_trade_futu(hk_code, entry, stop, target, timestamp, recommendation)
                    if result.get('status') not in retry_statuses:
                        return result
                except Exception as e:
                    # Futu failed, will fall through to next provider
                    pass

            if use_itick:
                # Try iTick next
                result = check_hk_trade_itick(hk_code, entry, stop, target, timestamp)
                if result.get('status') not in retry_statuses:
                    return result

            # Last resort: try Yahoo - normalize HK stock code for Yahoo Finance
            # Yahoo uses 4-digit codes with leading zeros for 4-digit codes (0700.HK = Tencent)
            # But 5-digit codes need leading zeros stripped (09988.HK -> 9988.HK)
            hk_for_yahoo = code.replace('.HK', '') if code.endswith('.HK') else code
            # Only strip leading zeros if code is > 4 digits
            if len(hk_for_yahoo) > 4:
                hk_for_yahoo = hk_for_yahoo.lstrip('0') or '0'
            if code.endswith('.HK'):
                hk_for_yahoo = f"{hk_for_yahoo}.HK"
            ticker = yf.Ticker(hk_for_yahoo)
            return check_hk_trade(ticker, entry, stop, target, timestamp, recommendation)
        else:
            # US stock - use Yahoo
            ticker = yf.Ticker(code)
            return check_us_trade(ticker, entry, stop, target, timestamp, recommendation)

    except Exception as e:
        return {'status': 'ERROR', 'reason': str(e), 'actual_high': None, 'actual_low': None, 'exit_date': None}


def check_hk_trade_futu(code: str, entry: float, stop: float, target: float,
                     timestamp: str, recommendation: str = 'BUY') -> dict:
    """Check HK stock trade result using Futu API."""
    futu = get_futu_client()
    if not futu or not FUTU_AVAILABLE:
        return {'status': 'ERROR', 'reason': 'Futu not available'}

    try:
        # Parse timestamp in HK time
        ts = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        ts = HK_TZ.localize(ts)

        # Get 5-minute klines from Futu
        df = futu.get_klines(code, ktype="5m", limit=500)

        if df.empty:
            return {'status': 'NO DATA', 'reason': 'No data from Futu'}

        # Get the entry date (not datetime) for filtering
        entry_date = ts.date()

        # Filter to only same-day data (from entry time onwards on the SAME day)
        df = df[df.index >= ts]

        # Track if we're using fallback data
        using_fallback = False

        if df.empty:
            # Fallback: try previous trading day (no data after entry time)
            using_fallback = True

        # Filter to same calendar day
        # Note: pandas dt accessor needs .date (not .date())
        df_dates = pd.Series([d.date() for d in df.index], index=df.index)
        df_same_day = df[df_dates == entry_date]
        if df_same_day.empty:
            # Fallback: use last available trading day
            if not df.empty:
                using_fallback = True
            else:
                # Need to re-fetch all data
                df = futu.get_klines(code, ktype="5m", limit=500)
                if df.empty:
                    return {'status': 'NO DATA', 'reason': 'No data from Futu'}
                df_dates = pd.Series([d.date() for d in df.index], index=df.index)

            # Use the last available trading day
            latest_date = df.index[-1].date()
            df = df[df_dates == latest_date]

        # Use first available data as entry
        entry_price = df['Open'].iloc[0]

        # Get actual high/low
        actual_high = df['High'].max()
        actual_low = df['Low'].min()

        is_short = recommendation == 'SELL'

        # Check candle by candle
        for idx, row in df.iterrows():
            high = row['High']
            low = row['Low']

            if is_short:
                if high >= stop:
                    return {
                        'status': 'LOSS', 'entry_price': entry_price, 'exit_price': stop,
                        'time': idx.strftime('%H:%M'), 'exit_date': idx.strftime('%Y-%m-%d'),
                        'reason': f'Stop {stop} hit', 'actual_high': actual_high, 'actual_low': actual_low
                    }
                if low <= target:
                    return {
                        'status': 'GAIN', 'entry_price': entry_price, 'exit_price': target,
                        'time': idx.strftime('%H:%M'), 'exit_date': idx.strftime('%Y-%m-%d'),
                        'reason': f'Target {target} hit', 'actual_high': actual_high, 'actual_low': actual_low
                    }
            else:
                if low <= stop:
                    return {
                        'status': 'LOSS', 'entry_price': entry_price, 'exit_price': stop,
                        'time': idx.strftime('%H:%M'), 'exit_date': idx.strftime('%Y-%m-%d'),
                        'reason': f'Stop {stop} hit', 'actual_high': actual_high, 'actual_low': actual_low
                    }
                if high >= target:
                    return {
                        'status': 'GAIN', 'entry_price': entry_price, 'exit_price': target,
                        'time': idx.strftime('%H:%M'), 'exit_date': idx.strftime('%Y-%m-%d'),
                        'reason': f'Target {target} hit', 'actual_high': actual_high, 'actual_low': actual_low
                    }

        # Pending
        last_price = df['Close'].iloc[-1]
        return {
            'status': 'PENDING', 'entry_price': entry_price, 'exit_price': last_price,
            'time': df.index[-1].strftime('%H:%M'), 'exit_date': df.index[-1].strftime('%Y-%m-%d'),
            'reason': f'Neither hit. Last: {last_price:.2f}', 'actual_high': actual_high, 'actual_low': actual_low
        }

    except Exception as e:
        return {'status': 'ERROR', 'reason': str(e)}


def check_hk_trade_itick(code: str, entry: float, stop: float, target: float,
                          timestamp: str) -> dict:
    """Check HK stock trade result using iTick"""
    try:
        # Parse timestamp in HK time
        ts = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        ts = HK_TZ.localize(ts)

        # Get the entry date for filtering
        entry_date = ts.date()

        # Get 5-minute klines from iTick (use larger limit for more history)
        df = get_itick_klines(code, "HK", ktype=2, limit=500)

        if df.empty:
            return {'status': 'NO DATA', 'reason': 'No data from iTick'}

        # Filter from entry time onwards
        df = df[df.index >= ts]

        # Track if we're using fallback data
        using_fallback = False

        if df.empty:
            using_fallback = True

        # Also filter: only same calendar day - use pd Series for .date accessor
        df_dates = pd.Series([d.date() for d in df.index], index=df.index)
        df_same_day = df[df_dates == entry_date]
        if df_same_day.empty:
            # Fallback: use last available trading day
            if not df.empty:
                using_fallback = True
                latest_date = df.index[-1].date()
                df = df[df_dates == latest_date]
            else:
                return {'status': 'NO DATA AFTER', 'reason': 'No data available'}
        df = df_same_day if not using_fallback else df

        # Recreate dates for non-empty df
        if not df.empty:
            df_dates = pd.Series([d.date() for d in df.index], index=df.index)
            # Determine exit date
            rec_date = timestamp.split()[0]  # YYYY-MM-DD
            if using_fallback:
                exit_dt = rec_date
            else:
                exit_dt = df.index[-1].strftime('%Y-%m-%d')

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
                    timestamp: str, recommendation: str = 'BUY') -> dict:
    """Check HK stock trade result"""
    try:
        # Parse timestamp in HK time
        ts = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        ts = HK_TZ.localize(ts)

        df = ticker.history(period="8d", interval="1m")

        if df.empty:
            return {'status': 'NO DATA', 'reason': 'No data returned', 'actual_high': None, 'actual_low': None, 'exit_date': None}

        # Filter to only include data from entry time onwards
        df_after = df[df.index >= ts]

        if df_after.empty:
            # Fallback: If no data after entry time, use the last available data
            df = ticker.history(period="8d", interval="1m")
            if df.empty:
                return {'status': 'NO DATA', 'reason': 'No data returned', 'actual_high': None, 'actual_low': None, 'exit_date': None}
            # Use last available trading day - use pd Series for .date accessor
            df_dates = pd.Series([d.date() for d in df.index], index=df.index)
            latest_date = df.index[-1].date()
            df = df[df_dates == latest_date]
            if df.empty:
                return {'status': 'NO DATA AFTER', 'reason': 'No data on latest day', 'actual_high': None, 'actual_low': None, 'exit_date': None}
        else:
            df = df_after

        # Get actual high/low for the period
        actual_high = df['High'].max()
        actual_low = df['Low'].min()

        # Get entry price
        entry_price = df['Open'].iloc[0]

        # For SELL (short): stop is ABOVE entry, target is BELOW entry
        # For BUY: stop is BELOW entry, target is ABOVE entry
        is_short = recommendation == 'SELL'

        # Check candle by candle
        for idx, row in df.iterrows():
            high = row['High']
            low = row['Low']

            if is_short:
                # Short position: stop above = loss, target below = gain
                if high >= stop:
                    return {
                        'status': 'LOSS',
                        'entry_price': entry_price,
                        'exit_price': stop,
                        'time': idx.strftime('%H:%M'),
                        'exit_date': idx.strftime('%Y-%m-%d'),
                        'reason': f'Stop {stop} hit at {idx.strftime("%H:%M")}',
                        'actual_high': actual_high,
                        'actual_low': actual_low
                    }

                if low <= target:
                    return {
                        'status': 'GAIN',
                        'entry_price': entry_price,
                        'exit_price': target,
                        'time': idx.strftime('%H:%M'),
                        'exit_date': idx.strftime('%Y-%m-%d'),
                        'reason': f'Target {target} hit at {idx.strftime("%H:%M")}',
                        'actual_high': actual_high,
                        'actual_low': actual_low
                    }
            else:
                # Long position (BUY): stop below = loss, target above = gain
                if low <= stop:
                    return {
                        'status': 'LOSS',
                        'entry_price': entry_price,
                        'exit_price': stop,
                        'time': idx.strftime('%H:%M'),
                        'exit_date': idx.strftime('%Y-%m-%d'),
                        'reason': f'Stop {stop} hit at {idx.strftime("%H:%M")}',
                        'actual_high': actual_high,
                        'actual_low': actual_low
                    }

                if high >= target:
                    return {
                        'status': 'GAIN',
                        'entry_price': entry_price,
                        'exit_price': target,
                        'time': idx.strftime('%H:%M'),
                        'exit_date': idx.strftime('%Y-%m-%d'),
                        'reason': f'Target {target} hit at {idx.strftime("%H:%M")}',
                        'actual_high': actual_high,
                        'actual_low': actual_low
                    }

        # Neither hit - pending
        last_price = df['Close'].iloc[-1]
        return {
            'status': 'PENDING',
            'entry_price': entry_price,
            'exit_price': last_price,
            'time': df.index[-1].strftime('%H:%M'),
            'exit_date': df.index[-1].strftime('%Y-%m-%d'),
            'reason': f'Neither hit. Last: {last_price:.2f}',
            'actual_high': actual_high,
            'actual_low': actual_low
        }

    except Exception as e:
        return {'status': 'ERROR', 'reason': str(e), 'actual_high': None, 'actual_low': None, 'exit_date': None}


def check_us_trade(ticker, entry: float, stop: float, target: float,
                    timestamp: str, recommendation: str = 'BUY') -> dict:
    """Check US stock trade result - check from entry time onwards"""
    try:
        # Parse timestamp in HK time and convert to US Eastern
        ts = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        ts = HK_TZ.localize(ts)
        # Convert to US/Eastern for filtering
        ts_us = ts.astimezone(US_TZ)
        # Get rec date (in HK) for use as fallback exit date
        rec_date = timestamp.split()[0]  # YYYY-MM-DD format from HK timezone

        df = ticker.history(period="8d", interval="1m")

        if df.empty:
            return {'status': 'NO DATA', 'reason': 'No data returned', 'actual_high': None, 'actual_low': None, 'exit_date': rec_date}

        # Filter for regular trading hours (09:30-16:00 US ET) first
        df = df[(df.index.hour >= 9) & (df.index.hour <= 16)]

        if df.empty:
            return {'status': 'NO TRADING HOURS', 'reason': 'No data in trading hours', 'actual_high': None, 'actual_low': None, 'exit_date': rec_date}

        # Filter from entry time onwards within available data
        df_after = df[df.index >= ts_us]

        # Track if we're using fallback data
        using_fallback = df_after.empty

        if using_fallback:
            # If no data after entry time, try the previous trading day
            # This handles timezone conversion issues where HK time maps to weekend
            # Get all available trading data
            df = ticker.history(period="8d", interval="1m")
            df = df[(df.index.hour >= 9) & (df.index.hour <= 16)]
            if df.empty:
                return {'status': 'NO DATA', 'reason': 'No trading hours data', 'actual_high': None, 'actual_low': None, 'exit_date': rec_date}

            # Use the last available trading day
            latest_date = df.index.date[-1]
            df = df[df.index.date == latest_date]

            if df.empty:
                return {'status': 'NO DATA AFTER', 'reason': 'No data after entry time', 'actual_high': None, 'actual_low': None, 'exit_date': rec_date}
        else:
            df = df_after

        # Get actual high/low for the period
        actual_high = df['High'].max()
        actual_low = df['Low'].min()

        # Use first available data as entry
        entry_price = df['Open'].iloc[0]

        # For SELL (short): stop is ABOVE entry, target is BELOW entry
        # For BUY: stop is BELOW entry, target is ABOVE entry
        is_short = recommendation == 'SELL'

        # Check minute by minute
        for idx, row in df.iterrows():
            high = row['High']
            low = row['Low']

            # Convert to HK time for display
            idx_hk = idx.astimezone(HK_TZ)

            # Determine exit date: use rec_date if using fallback, otherwise use actual date
            if using_fallback:
                exit_dt = rec_date
            else:
                exit_dt = idx_hk.strftime('%Y-%m-%d')

            if is_short:
                # Short position: stop above = loss, target below = gain
                if high >= stop:
                    return {
                        'status': 'LOSS',
                        'entry_price': entry_price,
                        'exit_price': stop,
                        'time': idx_hk.strftime('%H:%M'),
                        'exit_date': exit_dt,
                        'reason': f'Stop {stop} hit at {idx_hk.strftime("%H:%M")} HK',
                        'actual_high': actual_high,
                        'actual_low': actual_low
                    }

                if low <= target:
                    return {
                        'status': 'GAIN',
                        'entry_price': entry_price,
                        'exit_price': target,
                        'time': idx_hk.strftime('%H:%M'),
                        'exit_date': exit_dt,
                        'reason': f'Target {target} hit at {idx_hk.strftime("%H:%M")} HK',
                        'actual_high': actual_high,
                        'actual_low': actual_low
                    }
            else:
                # Long position (BUY): stop below = loss, target above = gain
                if low <= stop:
                    return {
                        'status': 'LOSS',
                        'entry_price': entry_price,
                        'exit_price': stop,
                        'time': idx_hk.strftime('%H:%M'),
                        'exit_date': exit_dt,
                        'reason': f'Stop {stop} hit at {idx_hk.strftime("%H:%M")} HK',
                        'actual_high': actual_high,
                        'actual_low': actual_low
                    }

                if high >= target:
                    return {
                        'status': 'GAIN',
                        'entry_price': entry_price,
                        'exit_price': target,
                        'time': idx_hk.strftime('%H:%M'),
                        'exit_date': exit_dt,
                        'reason': f'Target {target} hit at {idx_hk.strftime("%H:%M")} HK',
                        'actual_high': actual_high,
                        'actual_low': actual_low
                    }

        # Neither hit - pending
        last_price = df['Close'].iloc[-1]
        last_time_hk = df.index[-1].astimezone(HK_TZ)
        # Determine exit date for pending
        if using_fallback:
            exit_dt = rec_date
        else:
            exit_dt = last_time_hk.strftime('%Y-%m-%d')
        return {
            'status': 'PENDING',
            'entry_price': entry_price,
            'exit_price': last_price,
            'time': last_time_hk.strftime('%H:%M'),
            'exit_date': exit_dt,
            'reason': f'Neither hit. Last: {last_price:.2f}',
            'actual_high': actual_high,
            'actual_low': actual_low
        }

    except Exception as e:
        return {'status': 'ERROR', 'reason': str(e), 'actual_high': None, 'actual_low': None, 'exit_date': None}


def load_all_recommendations(portfolio_files: list) -> list:
    """
    Load all BUY and SELL recommendations from portfolio JSON files.

    Returns list of dicts with: code, entry, stop, target, timestamp, recommendation
    """
    recs = []

    for filepath in portfolio_files:
        try:
            with open(filepath) as f:
                data = json.load(f)

            for r in data.get('results', []):
                # Load all recommendations (BUY/SELL)
                recommendation = r.get('recommendation', '')
                if recommendation in ['BUY', 'SELL']:
                    code = r.get('code', '')

                    # Normalize HK stock codes
                    # e.g., "3690" -> "03690.HK" (5 digits with leading zero for Yahoo)
                    # "100" -> "00100.HK"
                    if code.isdigit():
                        code = f"{int(code):05d}.HK"
                    # Already has .HK or is US stock
                    elif not code.endswith('.HK') and not any(c.isalpha() for c in code):
                        # Try to detect if it's a short HK code and pad
                        if len(code) <= 4:  # Likely HK code missing .HK
                            code = f"{int(code):05d}.HK"

                    # Get analysis data for rec_price
                    analysis = r.get('analysis', {})
                    recs.append({
                        'code': code,
                        'recommendation': recommendation,
                        'entry': r.get('entry', 0),
                        'stop': r.get('stop', 0),
                        'target': r.get('target', 0),
                        'timestamp': r.get('timestamp', ''),
                        'confidence': r.get('confidence', 'LOW'),
                        'stock_name': r.get('stock_name', ''),
                        'rec_price': analysis.get('price', 0),
                    })
        except Exception as e:
            print(f"Error loading {filepath}: {e}")

    return recs


# Backwards compatibility alias
def load_buy_recommendations(portfolio_files: list) -> list:
    """Deprecated: Use load_all_recommendations instead"""
    return load_all_recommendations(portfolio_files)


def verify_trades(buy_recs: list, verbose: bool = True, use_itick: bool = True, use_futu: bool = True) -> pd.DataFrame:
    """
    Verify all trades and return results as DataFrame

    Args:
        buy_recs: List of trade recommendations
        verbose: Print progress
        use_itick: Use iTick API for HK stocks instead of Yahoo
        use_futu: Use Futu API for HK stocks (default True)
    """
    results = []

    for i, rec in enumerate(buy_recs, 1):
        result = check_trade_result(
            rec['code'],
            rec['entry'],
            rec['stop'],
            rec['target'],
            rec['timestamp'],
            rec.get('recommendation', 'BUY',),  # Pass recommendation (BUY or SELL)
            use_itick=use_itick,
            use_futu=use_futu
        )

        # Calculate Gain/Loss % based on ACTUAL entry price (first available candle open), not recommended entry
        gl_pct = None
        rec_entry = rec.get('entry', 0)  # recommended entry price
        rec_type = rec.get('recommendation', 'BUY')
        actual_entry = result.get('entry_price', rec_entry)  # actual entry from first candle
        
        if result['status'] == 'GAIN':
            exit_price = result.get('exit_price', 0)
            if actual_entry > 0 and exit_price > 0:
                if rec_type.upper() == 'SELL':
                    gl_pct = ((actual_entry - exit_price) / actual_entry) * 100
                else:
                    gl_pct = ((exit_price - actual_entry) / actual_entry) * 100
        elif result['status'] == 'LOSS':
            exit_price = result.get('exit_price', 0)
            if actual_entry > 0 and exit_price > 0:
                if rec_type.upper() == 'SELL':
                    gl_pct = ((actual_entry - exit_price) / actual_entry) * 100
                else:
                    gl_pct = ((exit_price - actual_entry) / actual_entry) * 100
        # PENDING and ERROR have gl_pct = None (not NaN)

        # Extract date from timestamp
        date = rec['timestamp'].split()[0] if rec['timestamp'] else ''

        results.append({
            'index': i,
            'code': rec['code'],
            'recommendation': rec.get('recommendation', 'BUY'),
            'name': rec['stock_name'],
            'rec_price': rec.get('rec_price', 0),
            'entry_rec': rec['entry'],
            'stop': rec['stop'],
            'target': rec['target'],
            'entry_actual': result.get('entry_price'),
            'exit_price': result.get('exit_price'),
            'actual_high': result.get('actual_high'),
            'actual_low': result.get('actual_low'),
            'status': result.get('status'),
            'gain_loss_pct': gl_pct,
            'time': result.get('time'),
            'exit_date': result.get('exit_date'),
            'entry_time': rec['timestamp'].split()[1] if rec['timestamp'] else '',
            'entry_full': rec['timestamp'] if rec['timestamp'] else '',
            'date': date,
            'timestamp': rec['timestamp'],
            'entry_datetime': rec['timestamp'] if rec['timestamp'] else '',
            'exit_datetime': f"{result.get('exit_date', '')} {result.get('time', '')}" if result.get('exit_date') or result.get('time') else '',
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

            gl_str = f"gain {int(round(gl_pct))}%" if gl_pct is not None and gl_pct > 0 else (f"loss {int(round(abs(gl_pct)))}%" if gl_pct is not None and gl_pct < 0 else "N/A")

            # Entry and exit times
            entry_t = rec['timestamp'].split()[1] if rec['timestamp'] else ''
            exit_t = result.get('time', '')
            exit_d = result.get('exit_date', '')
            exit_dt_str = f"{exit_d} {exit_t}" if exit_d and exit_t else (exit_t if exit_t else 'N/A')

            print(f"{i:2d}. {rec['code']:<12} Entry: ${rec['entry']:>7.2f} @ {entry_t} "
                  f"Stop: ${rec['stop']:>6.2f} Target: ${rec['target']:>7.2f} "
                  f"→ {status_symbol} {result.get('status', 'ERROR'):<8} {exit_dt_str} ({gl_str})")

    return pd.DataFrame(results)


def print_summary(df: pd.DataFrame, detailed: bool = False):
    """Print summary statistics"""
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)

    if detailed:
        # Print header with specified columns including recommendation
        print(f"{'#':<3} {'Code':<8} {'buy-hold-sell':<12} {'Rec datetime (HK)':<20} {'Exit datetime (HK)':<20} {'RecPrice':>9} {'Entry':<8} {'Stop':<8} {'Target':<8} {'Confidence':<8} {'Status':<8} {'gain/loss%':>10}")
        print("-" * 167)
        # Validate exit times and update status in dataframe
        for idx, row in df.iterrows():
            # Exit datetime - use stored exit_date or derive from rec date
            exit_date = row.get('exit_date', '')
            exit_time_val = None
            if exit_date and row.get('time'):
                exit_time_val = f"{exit_date} {row['time']}"
            elif row.get('time'):
                rec_date = row.get('date', '2026-03-08')
                exit_time_val = f"{rec_date} {row['time']}"

            # Validate: exit datetime must be AFTER rec datetime and NOT in the future
            if exit_time_val and row.get('entry_full'):
                try:
                    rec_dt = datetime.strptime(row['entry_full'], '%Y-%m-%d %H:%M:%S')
                    exit_dt = datetime.strptime(exit_time_val, '%Y-%m-%d %H:%M')
                    if exit_dt < rec_dt:
                        # Exit is before entry - mark as INVALID
                        df.at[idx, 'status'] = 'INVALID'
                    else:
                        now = datetime.now()
                        if exit_dt > now:
                            # Exit time is in the future - mark as PENDING
                            df.at[idx, 'status'] = 'PENDING'
                except:
                    pass

        # Now print the table
        for _, row in df.iterrows():
            rec_price = f"${row['rec_price']:.2f}" if row.get('rec_price') and row['rec_price'] > 0 else "N/A"
            entry = f"${row['entry_rec']:.2f}" if row['entry_rec'] > 0 else "N/A"
            stop = f"${row['stop']:.2f}" if row['stop'] > 0 else "N/A"
            target = f"${row['target']:.2f}" if row['target'] > 0 else "N/A"

            exit_date = row.get('exit_date', '')
            if exit_date and row.get('time'):
                exit_time = f"{exit_date} {row['time']}"
            elif row['time']:
                rec_date = row.get('date', '2026-03-08')
                exit_time = f"{rec_date} {row['time']}"
            else:
                exit_time = "N/A"

            # Override exit_time display if status is INVALID
            status = row['status']
            if status == 'INVALID':
                exit_time = "INVALID"
            # PENDING shows last data time (not N/A)

            # Rule 5 fix: Force-close PENDING trades held > 3 trading days
            MAX_TRADING_DAYS = 3
            if status == 'PENDING' and row.get('entry_full'):
                try:
                    entry_dt = datetime.strptime(row['entry_full'], '%Y-%m-%d %H:%M:%S')
                    now_dt = datetime.now()
                    trading_days = (now_dt.date() - entry_dt.date()).days
                    # Count only trading days (exclude weekends roughly by checking business days)
                    # Simple approximation: count calendar days but skip sat/sun
                    calendar_days = (now_dt - entry_dt).days
                    # Rough trading day estimate: 5/7 of calendar days
                    est_trading_days = int(calendar_days * 5 / 7)
                    if est_trading_days >= MAX_TRADING_DAYS:
                        df.at[idx, 'status'] = 'EXPIRED'
                        df.at[idx, 'gain_loss_pct'] = None
                        status = 'EXPIRED'
                except:
                    pass

            conf = row.get('confidence', 'N/A')
            rec_type = row.get('recommendation', 'BUY')
            gl_pct = f"{row['gain_loss_pct']:+.1f}%" if row.get('gain_loss_pct') is not None else "N/A"
            print(f"{row['index']:<3} {row['code']:<8} {rec_type:<12} {row['entry_full']:<20} {exit_time:<20} {rec_price:>9} {entry:<8} {stop:<8} {target:<8} {conf:<8} {status:<8} {gl_pct:>10}")
        print("-" * 167)

    # Filter to only closed trades (GAIN or LOSS)
    closed = df[df['status'].isin(['GAIN', 'LOSS'])]
    # Filter to only closed trades (GAIN or LOSS); PENDING may have been reclassified as EXPIRED above
    pending = df[df['status'] == 'PENDING']
    expired = df[df['status'] == 'EXPIRED']
    invalid = df[df['status'] == 'INVALID']
    errors = df[~df['status'].isin(['GAIN', 'LOSS', 'PENDING', 'INVALID', 'EXPIRED'])]

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
    print(f"  EXPIRED (>3 trading days):   {len(expired)}")
    print(f"  INVALID (exit<rec):          {len(invalid)}")
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
    parser.add_argument('--itick', action='store_true', help='Use iTick API for HK stocks (instead of Yahoo)')
    parser.add_argument('--no-futu', action='store_true', help='Disable Futu API for HK stocks')
    args = parser.parse_args()

    # Default to today's portfolio files if no files specified
    if not args.files:
        args.files = glob.glob('portfolio_2026-03-*.json')
        if not args.files:
            print("No portfolio files found. Usage: python verify_trades.py <portfolio_json_files>")
            sys.exit(1)

    print(f"Loading BUY and SELL recommendations from {len(args.files)} files...")

    recs = load_all_recommendations(args.files)
    print(f"Found {len(recs)} recommendations (BUY + SELL)\n")

    print("Verifying trades...")
    use_futu = not args.no_futu
    df = verify_trades(recs, verbose=args.verbose, use_itick=args.itick, use_futu=use_futu)

    print_summary(df, detailed=args.detailed)

    if args.output:
        df.to_csv(args.output, index=False)
        print(f"\nResults saved to {args.output}")


if __name__ == '__main__':
    main()
