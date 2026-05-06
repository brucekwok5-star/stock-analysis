#!/usr/bin/env python3
"""
Backtest Stock Analysis
Analyze historical data at a specific date/time to generate recommendations
and save to portfolio files for later verification.
Uses the same logic AND data sources as the live stock_analysis.py system.
"""

import warnings
warnings.filterwarnings('ignore')
import logging
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

import sys
import os
import json
import argparse
import pytz
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stock_analysis import TechnicalAnalyzer, ITickClient, FutuClient, ITICK_TOKENS, MiniMaxClient, MINIMAX_API_KEY
import yfinance as yf

# Timezone
HKT = pytz.timezone('Asia/Hong_Kong')
US_TZ = pytz.timezone('US/Eastern')

# iTick tokens (same as live system)
ITICK_API_KEYS = ITICK_TOKENS
_itick_token_idx = 0


def get_next_itick_token() -> str:
    """Get next iTick token (rotates through tokens)."""
    global _itick_token_idx
    token = ITICK_API_KEYS[_itick_token_idx]
    _itick_token_idx = (_itick_token_idx + 1) % len(ITICK_API_KEYS)
    return token


def fetch_itick_kline(code: str, region: str, ktype: int = 5, limit: int = 200) -> Optional[List]:
    """Fetch kline data from iTick API."""
    token = get_next_itick_token()
    base_url = "https://api0.itick.org"

    headers = {"token": token}
    # kType: 1=1m, 2=5m, 3=15m, 4=30m, 5=1hour, 8=1day

    params = {"region": region, "code": code, "kType": ktype, "limit": limit}

    try:
        resp = requests.get(f"{base_url}/stock/kline", headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0 and data.get("data"):
                return data.get("data", [])
            elif data.get("msg"):
                print(f"    ⚠️ iTick: {data.get('msg')}")
    except Exception as e:
        print(f"    ⚠️ iTick error: {e}")

    return None


def fetch_itick_index_kline(region: str, code: str, ktype: int = 5, limit: int = 200) -> Optional[List]:
    """Fetch index kline from iTick API."""
    token = get_next_itick_token()
    base_url = "https://api0.itick.org"

    headers = {"token": token}
    params = {"region": region, "code": code, "kType": ktype, "limit": limit}

    try:
        resp = requests.get(f"{base_url}/indices/kline", headers=headers, params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 0 and data.get("data"):
                return data.get("data", [])
    except Exception as e:
        print(f"    ⚠️ iTick index error: {e}")

    return None


def calculate_ema(prices: List[float], period: int) -> List[float]:
    """Calculate EMA."""
    if len(prices) < period:
        return prices
    tech = TechnicalAnalyzer()
    return tech.calculate_ema(prices, period)


def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
    """Calculate RSI."""
    if len(prices) < period + 1:
        return [50] * len(prices)
    tech = TechnicalAnalyzer()
    return tech.calculate_rsi(prices, period)


def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[float]:
    """Calculate ATR."""
    if len(highs) < period + 1:
        return [0] * len(highs)
    tech = TechnicalAnalyzer()
    return tech.calculate_atr(highs, lows, closes, period)


def analyze_trend_1h(kline_1h: List[Dict], price: float, ema20: float, ema50: float) -> tuple:
    """Analyze 1H trend - matches live system logic."""
    trend_direction = "NEUTRAL"
    trend_strength = "WEAK"

    if not kline_1h or len(kline_1h) < 5:
        return trend_direction, trend_strength

    closes_1h = [k["c"] for k in kline_1h]

    # Check for higher highs/lower lows
    higher_highs = 0
    lower_lows = 0
    for i in range(2, len(closes_1h) - 1):
        if closes_1h[i] > closes_1h[i-1] and closes_1h[i] > closes_1h[i+1]:
            higher_highs += 1
        if closes_1h[i] < closes_1h[i-1] and closes_1h[i] < closes_1h[i+1]:
            lower_lows += 1

    # EMA alignment check
    ema_diff = abs(ema20 - ema50) / ema20 * 100 if ema20 > 0 else 0

    if ema20 > 0 and ema50 > 0 and ema_diff > 0.1:
        ema_bullish = price > ema20 > ema50
        ema_bearish = price < ema20 < ema50
    elif ema20 > 0:
        ema_bullish = price > ema20
        ema_bearish = price < ema20
    else:
        ema_bullish = False
        ema_bearish = False

    if ema_bullish and higher_highs >= 2:
        trend_direction = "BULLISH"
        trend_strength = "STRONG_BULLISH"
    elif ema_bearish and lower_lows >= 2:
        trend_direction = "BEARISH"
        trend_strength = "STRONG_BEARISH"
    elif ema_bullish:
        trend_direction = "BULLISH"
        trend_strength = "MODERATE"
    elif ema_bearish:
        trend_direction = "BEARISH"
        trend_strength = "MODERATE"

    return trend_direction, trend_strength


def analyze_mtf_alignment(kline_1h: List[Dict], kline_15m: List[Dict], kline_5m: List[Dict],
                       trend_direction: str) -> tuple:
    """Analyze multi-timeframe alignment."""
    trend_15m = "NEUTRAL"
    momentum_5m = "NEUTRAL"
    mtf_aligned = False

    # 15m trend
    if kline_15m and len(kline_15m) >= 5:
        closes_15m = [k["c"] for k in kline_15m]
        ema5_vals = calculate_ema(closes_15m, 5)
        ema10_vals = calculate_ema(closes_15m, 10)
        if ema5_vals and ema10_vals and ema5_vals[-1] > ema10_vals[-1]:
            trend_15m = "BULLISH"
        elif ema5_vals and ema10_vals and ema5_vals[-1] < ema10_vals[-1]:
            trend_15m = "BEARISH"

    # 5m momentum
    if kline_5m and len(kline_5m) >= 5:
        closes_5m = [k["c"] for k in kline_5m]
        if len(closes_5m) >= 3:
            if closes_5m[-1] > closes_5m[-3]:
                momentum_5m = "BULLISH"
            elif closes_5m[-1] < closes_5m[-3]:
                momentum_5m = "BEARISH"

    # MTF alignment
    if trend_direction == "BULLISH" and trend_15m == "BULLISH" and momentum_5m == "BULLISH":
        mtf_aligned = True
    elif trend_direction == "BEARISH" and trend_15m == "BEARISH" and momentum_5m == "BEARISH":
        mtf_aligned = True

    return trend_15m, momentum_5m, mtf_aligned


def analyze_volume(kline_5m: List[Dict], region: str = "HK") -> tuple:
    """Analyze volume."""
    volume_threshold = 1.5 if region == "US" else 1.0

    has_volume_data = False
    volume_spike = False
    volume_ratio = 0.0

    if kline_5m and len(kline_5m) >= 10:
        volumes = [k.get("v", 0) for k in kline_5m]
        if volumes and sum(volumes[:-1]) > 0:
            avg_volume = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
            last_volume = volumes[-1] if volumes else 0
            if avg_volume > 0:
                volume_ratio = last_volume / avg_volume
                if volume_ratio >= volume_threshold:
                    volume_spike = True
                has_volume_data = True

    return volume_spike, volume_ratio, has_volume_data


def analyze_rsi_confluence(rsi: float, rsi_15m: float, trend_direction: str) -> tuple:
    """Analyze RSI confluence."""
    rsi_ok = False
    rsi_confluence = False

    # RSI zones
    rsi_1h_bullish = 20 <= rsi <= 45
    rsi_15m_bullish = 20 <= rsi_15m <= 45
    rsi_1h_bearish = 55 <= rsi <= 80
    rsi_15m_bearish = 55 <= rsi_15m <= 80

    # Confluence
    if trend_direction == "BULLISH" and rsi_1h_bullish and rsi_15m_bullish:
        rsi_confluence = True
    elif trend_direction == "BEARISH" and rsi_1h_bearish and rsi_15m_bearish:
        rsi_confluence = True
    elif rsi < 20 or rsi > 80 or rsi_15m < 20 or rsi_15m > 80:
        rsi_confluence = True

    # RSI zone check
    if trend_direction == "BULLISH":
        if 30 <= rsi <= 75:
            rsi_ok = True
    elif trend_direction == "BEARISH":
        if 25 <= rsi <= 70:
            rsi_ok = True
    elif rsi < 20 or rsi > 80:
        rsi_ok = True

    return rsi_ok, rsi_confluence


def analyze_breakout_15m(kline_15m: List[Dict], price: float) -> bool:
    """Check for 15m breakout."""
    if not kline_15m or len(kline_15m) < 5:
        return False

    highs_15m = [k["h"] for k in kline_15m]
    closes_15m = [k["c"] for k in kline_15m]

    recent_high_15m = max(highs_15m[-5:-1])
    current_close = closes_15m[-1] if closes_15m else price

    if current_close > recent_high_15m * 1.001:
        return True
    return False


def generate_recommendation(price: float, ema20: float, ema50: float, ema200: float,
                      rsi: float, atr: float, vwap: float,
                      kline_1h: List[Dict], kline_15m: List[Dict], kline_5m: List[Dict],
                      rsi_15m: float, market_bias: str, region: str = "HK") -> Dict:
    """Generate recommendation using same logic as live stock_analysis.py."""
    reasons = []
    analysis_warnings = []
    reject_reasons = []

    # ATR percentage
    atr_pct = (atr / price * 100) if price > 0 else 0

    # STEP 1: Trend detection
    trend_direction, trend_strength = analyze_trend_1h(kline_1h, price, ema20, ema50)

    if trend_strength == "WEAK":
        reject_reasons.append(f"1h trend too weak ({trend_strength})")

    # Market filter
    if market_bias == "BEARISH" and trend_direction == "BULLISH":
        reject_reasons.append("Market is BEARISH, rejecting BUY")

    # ATR check - require minimum volatility
    atr_min = 1.0 if region == "US" else 0.8
    if atr_pct < atr_min:
        reject_reasons.append(f"ATR {atr_pct:.1f}% < {atr_min}% (low volatility)")

    # Volume
    volume_spike, volume_ratio, has_volume_data = analyze_volume(kline_5m, region)

    if not volume_spike and has_volume_data:
        analysis_warnings.append(f"Volume {volume_ratio:.1f}x < threshold")

    # RSI
    rsi_ok, rsi_confluence = analyze_rsi_confluence(rsi, rsi_15m, trend_direction)

    # VWAP
    vwap_dist = abs(price - vwap) / price * 100 if price > 0 else 0
    vwap_threshold = 0.3 if region == "US" else 0.5
    vwap_ok = vwap_dist > vwap_threshold

    if not vwap_ok:
        analysis_warnings.append(f"Price only {vwap_dist:.1f}% from VWAP")

    # Breakout
    breakout_15m = analyze_breakout_15m(kline_15m, price)

    # MTF alignment - REQUIRED for any signal
    trend_15m, momentum_5m, mtf_aligned = analyze_mtf_alignment(
        kline_1h, kline_15m, kline_5m, trend_direction)

    if not mtf_aligned:
        reject_reasons.append("MTF not aligned (1H/15m/5m must agree)")

    # Determine recommendation
    if reject_reasons:
        direction = "HOLD"
        confidence = "LOW"
        reasons.extend(reject_reasons)
    else:
        if trend_direction == "BULLISH" and rsi_ok:
            direction = "BUY"
            # Count confirmations (need 3+ for LOW, 5 for HIGH)
            confirmations = 0
            if trend_strength in ["STRONG_BULLISH"]:
                confirmations += 2
            elif trend_strength == "MODERATE":
                confirmations += 1
            if volume_spike:
                confirmations += 1
            if vwap_ok:
                confirmations += 1
            if rsi_confluence:
                confirmations += 1
            if breakout_15m:
                confirmations += 1

            # HIGH confidence: 5+ confirmations + STRONG trend + volume spike
            is_high = (confirmations >= 5 and trend_strength == "STRONG_BULLISH" and volume_spike)
            confidence = "HIGH" if is_high else "LOW"

            reasons.append(f"{trend_strength} trend on 1h")
            reasons.append(f"RSI in bullish zone: {rsi:.1f}")
            if mtf_aligned:
                reasons.append("MTF aligned")
            if volume_spike:
                reasons.append(f"Volume spike: {volume_ratio:.1f}x")
            reasons.append(f"Confirmations: {confirmations}/5")

        elif trend_direction == "BEARISH" and rsi_ok:
            direction = "SELL"
            confirmations = 0
            if trend_strength in ["STRONG_BEARISH"]:
                confirmations += 2
            elif trend_strength == "MODERATE":
                confirmations += 1
            if volume_spike:
                confirmations += 1
            if vwap_ok:
                confirmations += 1
            if rsi_confluence:
                confirmations += 1
            if breakout_15m:
                confirmations += 1

            is_high = (confirmations >= 5 and trend_strength == "STRONG_BEARISH" and volume_spike)
            confidence = "HIGH" if is_high else "LOW"

            reasons.append(f"{trend_direction} trend on 1h")
            reasons.append(f"RSI in bearish zone: {rsi:.1f}")
            if mtf_aligned:
                reasons.append("MTF aligned")
            if volume_spike:
                reasons.append(f"Volume spike: {volume_ratio:.1f}x")
            reasons.append(f"Confirmations: {confirmations}/5")

        else:
            direction = "HOLD"
            confidence = "LOW"
            reasons.append("Trend too weak or conditions not met")

    # Stop and target
    stop = 0
    target = 0
    rr = "0:1"

    if direction == "BUY" and price > 0 and atr > 0:
        stop = price * 0.97      # 3% stop
        target = price * 1.06    # 6% target = 2:1 R:R
        risk = price - stop
        if target - price < risk * 2.0:
            target = price + (risk * 2.0)
        rr = f"{(target - price) / risk:.1f}:1" if risk > 0 else "0:1"

    elif direction == "SELL" and price > 0 and atr > 0:
        stop = price * 1.03      # 3% stop
        target = price * 0.94    # 6% target = 2:1 R:R
        risk = stop - price
        if price - target < risk * 2.0:
            target = price - (risk * 2.0)
        rr = f"{(price - target) / risk:.1f}:1" if risk > 0 else "0:1"

    return {
        "recommendation": direction,
        "confidence": confidence,
        "entry": round(price, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "rr": rr,
        "reasons": reasons,
        "warnings": analysis_warnings,
        "market_bias": market_bias,
        "trend_direction": trend_direction,
        "trend_strength": trend_strength,
        "atr_pct": round(atr_pct, 2),
        "vwap_distance": round(vwap_dist, 2),
    }


def run_backtest(code: str, target_datetime: str, output_dir: str = "backtest", use_yfinance: bool = False):
    """Run backtest analysis using Futu OpenD for HK, iTick for US."""

    # Parse target datetime
    try:
        target_dt = datetime.strptime(target_datetime, "%Y-%m-%d %H:%M")
        target_dt = HKT.localize(target_dt)
    except ValueError:
        print(f"Invalid datetime format: {target_datetime}. Use 'YYYY-MM-DD HH:MM'")
        return None

    print(f"\n{'='*60}")
    print(f"  BACKTEST: {code} at {target_datetime} HKT")
    print(f"{'='*60}")

    os.makedirs(output_dir, exist_ok=True)

    # Detect region
    is_hk = code.isdigit() or code.endswith('.HK')
    region = "HK" if is_hk else "US"

    if is_hk:
        itick_code = code.replace('.HK', '').zfill(4)
    else:
        itick_code = code.upper()

    print(f"\n📊 Running backtest for {code}...")

    cutoff = target_dt

    # Data containers
    kline_1h = []
    kline_15m = []
    kline_5m = []
    market_kline = []
    analysis_warnings = []  # collected throughout run_backtest
    data_source = "none"

    # Futu client for HK stocks (matches live system)
    futu = FutuClient() if is_hk else None

    # HK stocks: try Futu first, then iTick
    # US stocks: try iTick first, then yfinance
    if is_hk:
        print(f"  📡 Fetching HK stock from Futu OpenD...")
        try:
            futu_1h = futu.get_kline(itick_code, ktype="1h", limit=200)
            if futu_1h:
                for bar in futu_1h:
                    if "t" in bar:
                        ts = bar["t"]
                        if isinstance(ts, str):
                            try:
                                ts = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
                                ts = HKT.localize(ts)
                            except:
                                continue
                        else:
                            if ts > 1e12:
                                ts = ts / 1000
                            ts = datetime.fromtimestamp(ts, HKT)
                        if ts <= cutoff:
                            kline_1h.append(bar)
                print(f"  ✓ Got {len(kline_1h)} 1H bars from Futu")
        except Exception as e:
            print(f"  ⚠️ Futu error: {e}")

        if not kline_1h:
            print(f"  📡 Futu failed, trying iTick fallback...")
            itick_1h = fetch_itick_kline(itick_code, region, ktype=5, limit=200)
            if itick_1h:
                for bar in itick_1h:
                    if "t" in bar:
                        ts = bar["t"]
                        if ts > 1e12:
                            ts = ts / 1000
                        bar_time = datetime.fromtimestamp(ts, HKT)
                        if bar_time <= cutoff:
                            kline_1h.append(bar)

        # 15m kline
        print(f"  📡 Fetching 15m from Futu...")
        try:
            futu_15m = futu.get_kline(itick_code, ktype="15m", limit=200) if futu else None
            if futu_15m:
                for bar in futu_15m:
                    if "t" in bar:
                        ts = bar["t"]
                        if isinstance(ts, str):
                            try:
                                ts = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
                                ts = HKT.localize(ts)
                            except:
                                continue
                        else:
                            if ts > 1e12:
                                ts = ts / 1000
                            ts = datetime.fromtimestamp(ts, HKT)
                        if ts <= cutoff:
                            kline_15m.append(bar)
                print(f"  ✓ Got {len(kline_15m)} 15m bars from Futu")
        except Exception as e:
            print(f"  ⚠️ Futu 15m error: {e}")

        if not kline_15m:
            print(f"  📡 Fetching 15m from iTick fallback...")
            itick_15m = fetch_itick_kline(itick_code, region, ktype=3, limit=200)
            if itick_15m:
                for bar in itick_15m:
                    if "t" in bar:
                        ts = bar["t"]
                        if ts > 1e12:
                            ts = ts / 1000
                        bar_time = datetime.fromtimestamp(ts, HKT)
                        if bar_time <= cutoff:
                            kline_15m.append(bar)

        # 5m kline
        print(f"  📡 Fetching 5m from Futu...")
        try:
            futu_5m = futu.get_kline(itick_code, ktype="5m", limit=200) if futu else None
            if futu_5m:
                for bar in futu_5m:
                    if "t" in bar:
                        ts = bar["t"]
                        if isinstance(ts, str):
                            try:
                                ts = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
                                ts = HKT.localize(ts)
                            except:
                                continue
                        else:
                            if ts > 1e12:
                                ts = ts / 1000
                            ts = datetime.fromtimestamp(ts, HKT)
                        if ts <= cutoff:
                            kline_5m.append(bar)
                print(f"  ✓ Got {len(kline_5m)} 5m bars from Futu")
        except Exception as e:
            print(f"  ⚠️ Futu 5m error: {e}")


        if not kline_5m:
            print(f"  📡 Fetching 5m from iTick fallback...")
            itick_5m = fetch_itick_kline(itick_code, region, ktype=2, limit=200)
            if itick_5m:
                for bar in itick_5m:
                    if "t" in bar:
                        ts = bar["t"]
                        if ts > 1e12:
                            ts = ts / 1000
                        bar_time = datetime.fromtimestamp(ts, HKT)
                        if bar_time <= cutoff:
                            kline_5m.append(bar)

        # Market index - use yfinance with longer lookback (different from stock data)
        if is_hk:
            index_ticker = "2800.HK"
        else:
            # Try different tickers for US market
            index_ticker = "^GSPC"  # S&P 500 index

        print(f"  📡 Fetching market index from yfinance...")
        try:
            # Use 60 days to ensure enough 1H data
            start_date = (target_dt - timedelta(days=60)).strftime('%Y-%m-%d')
            idx_ticker = yf.Ticker(index_ticker)
            idx_df = idx_ticker.history(start=start_date, interval="1h")
            if not idx_df.empty:
                # Try to get timezone - default to none if conversion fails
                try:
                    if idx_df.index.tz:
                        idx_df = idx_df.tz_convert(HKT)
                except Exception as tz_err:
                    analysis_warnings.append(f"Timezone conversion failed: {tz_err}")
                # Filter to before cutoff
                for idx, row in idx_df.iterrows():
                    if idx <= cutoff:
                        market_kline.append({
                            "t": int(idx.timestamp()),
                            "o": row['Open'],
                            "h": row['High'],
                            "l": row['Low'],
                            "c": row['Close'],
                            "v": row['Volume']
                        })
                print(f"  ✓ Market index: {len(market_kline)} 1H bars")
        except Exception as e:
            print(f"  ⚠️ Market index error: {e}")

        if kline_1h:
            if is_hk:
                data_source = "futu+itick"
                print(f"  ✓ Got {len(kline_1h)} 1H bars")
            else:
                data_source = "itick"
                print(f"  ✓ Got {len(kline_1h)} 1H bars from iTick")

    # US stocks fallback to yfinance (matches live system: HK→Futu/iTick, US→iTick/yfinance)
    if not is_hk and (not kline_1h or use_yfinance):
        print(f"  📡 Fetching from yfinance...")

        if is_hk:
            yahoo_code = f"{itick_code.zfill(4)}.HK"
        else:
            yahoo_code = itick_code.upper()

        start_date = (target_dt - timedelta(days=30)).strftime('%Y-%m-%d')
        ticker = yf.Ticker(yahoo_code)

        try:
            df_1h = ticker.history(start=start_date, interval="1h")
            if not df_1h.empty:
                df_1h = df_1h.tz_convert(HKT)
                df_1h_before = df_1h[df_1h.index <= cutoff]
                if not df_1h_before.empty:
                    for idx, row in df_1h_before.tail(200).iterrows():
                        kline_1h.append({
                            "t": int(idx.timestamp()),
                            "o": row['Open'],
                            "h": row['High'],
                            "l": row['Low'],
                            "c": row['Close'],
                            "v": row['Volume']
                        })

            df_15m = ticker.history(start=start_date, interval="15m")
            if not df_15m.empty:
                df_15m = df_15m.tz_convert(HKT)
                df_15m_before = df_15m[df_15m.index <= cutoff]
                if not df_15m_before.empty:
                    for idx, row in df_15m_before.tail(200).iterrows():
                        kline_15m.append({
                            "t": int(idx.timestamp()),
                            "o": row['Open'],
                            "h": row['High'],
                            "l": row['Low'],
                            "c": row['Close'],
                            "v": row['Volume']
                        })

            df_5m = ticker.history(start=start_date, interval="5m")
            if not df_5m.empty:
                df_5m = df_5m.tz_convert(HKT)
                df_5m_before = df_5m[df_5m.index <= cutoff]
                if not df_5m_before.empty:
                    for idx, row in df_5m_before.tail(200).iterrows():
                        kline_5m.append({
                            "t": int(idx.timestamp()),
                            "o": row['Open'],
                            "h": row['High'],
                            "l": row['Low'],
                            "c": row['Close'],
                            "v": row['Volume']
                        })

            # Market index
            if is_hk:
                idx_ticker = yf.Ticker("2800.HK")
            else:
                idx_ticker = yf.Ticker("SPY")

            idx_df = idx_ticker.history(start=start_date, interval="1h")
            if not idx_df.empty:
                tz = HKT if is_hk else US_TZ
                idx_df = idx_df.tz_convert(tz)
                idx_before = idx_df[idx_df.index <= cutoff]
                if not idx_before.empty:
                    for idx, row in idx_before.tail(100).iterrows():
                        market_kline.append({
                            "t": int(idx.timestamp()),
                            "o": row['Open'],
                            "h": row['High'],
                            "l": row['Low'],
                            "c": row['Close'],
                            "v": row['Volume']
                        })

            if kline_1h:
                data_source = "yfinance"
                print(f"  ✓ Got {len(kline_1h)} 1H bars from yfinance")

        except Exception as e:
            print(f"  ⚠️ yfinance error: {e}")

    if not kline_1h:
        print(f"  ❌ No data available for {code}")
        return None

    # Convert format
    def convert_kline(kline: List[Dict]) -> List[Dict]:
        result = []
        for bar in kline:
            if "t" in bar:
                result.append({
                    "o": bar["o"],
                    "h": bar["h"],
                    "l": bar["l"],
                    "c": bar["c"],
                    "v": bar["v"]
                })
            else:
                result.append(bar)
        return result

    kline_1h = convert_kline(kline_1h)
    kline_15m = convert_kline(kline_15m)
    kline_5m = convert_kline(kline_5m)

    current_price = kline_1h[-1]["c"]
    print(f"  ✓ Price at {target_datetime}: ${current_price:.2f}")
    print(f"  📊 Data source: {data_source}")

    # EMAs
    tech = TechnicalAnalyzer()
    closes = [k["c"] for k in kline_1h]
    highs = [k["h"] for k in kline_1h]
    lows = [k["l"] for k in kline_1h]
    volumes = [k["v"] for k in kline_1h]

    # EMAs
    ema20_period = min(20, len(closes))
    if ema20_period < 20:
        analysis_warnings.append(f"EMA20 capped at {ema20_period} bars (only {len(closes)} available)")
    ema20_vals = calculate_ema(closes, ema20_period) if ema20_period >= 2 else [current_price]
    ema20 = ema20_vals[-1] if ema20_vals else current_price

    ema50_period = min(50, len(closes))
    if ema50_period < 50:
        analysis_warnings.append(f"EMA50 capped at {ema50_period} bars (only {len(closes)} available)")
    ema50_vals = calculate_ema(closes, ema50_period) if ema50_period >= 2 else ema20_vals
    ema50 = ema50_vals[-1] if ema50_vals else ema20

    ema200_period = min(200, len(closes))
    if ema200_period < 200 and len(closes) >= 2:
        analysis_warnings.append(f"EMA200 capped at {ema200_period} bars (only {len(closes)} available)")
    ema200_vals = calculate_ema(closes, ema200_period) if ema200_period >= 2 else ema50_vals
    ema200 = ema200_vals[-1] if ema200_vals else ema50

    # RSI
    rsi_vals = calculate_rsi(closes, 14)
    rsi = rsi_vals[-1] if rsi_vals else 50

    # RSI 15m
    rsi_15m = 50
    if kline_15m:
        closes_15m = [k["c"] for k in kline_15m]
        rsi_15m_vals = calculate_rsi(closes_15m, 14)
        rsi_15m = rsi_15m_vals[-1] if rsi_15m_vals else 50
    elif len(kline_5m) >= 5:
        closes_5m = [k["c"] for k in kline_5m]
        rsi_5m_vals = calculate_rsi(closes_5m, 14)
        rsi_15m = rsi_5m_vals[-1] if rsi_5m_vals else 50
        analysis_warnings.append("15m kline missing — using 5m RSI as MTF proxy")
    else:
        analysis_warnings.append("15m kline missing — RSI confluence degraded to 1H only")

    # ATR
    atr_vals = calculate_atr(highs, lows, closes, 14)
    atr = atr_vals[-1] if atr_vals else 0

    # VWAP
    try:
        vwap_vals = tech.calculate_vwap(highs, lows, closes, volumes)
        vwap = vwap_vals[-1] if isinstance(vwap_vals, list) else vwap_vals
    except Exception as vwap_err:
        vwap = current_price
        analysis_warnings.append(f"VWAP calculation failed ({vwap_err}), using current price")

    # Market bias - matches live system logic
    market_bias = "NEUTRAL"
    if market_kline and len(market_kline) >= 20:
        market_closes = [k["c"] for k in market_kline if "c" in k]
        if len(market_closes) >= 20:
            # Calculate EMA20 and EMA50
            mkt_ema20 = calculate_ema(market_closes, 20)
            mkt_ema50 = calculate_ema(market_closes, 50)

            if mkt_ema20 and mkt_ema50 and len(mkt_ema20) >= 1 and len(mkt_ema50) >= 1:
                price = market_closes[-1]
                e20 = mkt_ema20[-1]
                e50 = mkt_ema50[-1]

                # Same logic as live system:
                # BULLISH: price > EMA20 > EMA50
                # BEARISH: price < EMA20 < EMA50
                # NEUTRAL: otherwise
                if price > e20 and e20 > e50:
                    market_bias = "BULLISH"
                elif price < e20 and e20 < e50:
                    market_bias = "BEARISH"
                else:
                    market_bias = "NEUTRAL"

    # Print analysis
    print(f"\n  Technical Analysis (at {target_datetime}):")
    print(f"    Price: ${current_price:.2f}")
    print(f"    EMA20: ${ema20:.2f}, EMA50: ${ema50:.2f}, EMA200: ${ema200:.2f}")
    print(f"    RSI(14): {rsi:.1f}, RSI(15m): {rsi_15m:.1f}")
    print(f"    ATR(14): {atr:.2f} ({atr/current_price*100:.1f}%)")
    print(f"    VWAP: ${vwap:.2f}")
    print(f"    Market Bias: {market_bias}")

    # Generate technical recommendation
    recommendation = generate_recommendation(
        price=current_price,
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        rsi=rsi,
        atr=atr,
        vwap=vwap,
        kline_1h=kline_1h,
        kline_15m=kline_15m,
        kline_5m=kline_5m,
        rsi_15m=rsi_15m,
        market_bias=market_bias,
        region=region
    )

    # Merge warnings from run_backtest scope (EMA/RSI/VWAP warnings)
    if analysis_warnings:
        recommendation["warnings"] = analysis_warnings + recommendation.get("warnings", [])

    # ============================================================
    # AI Recommendation (matches live system)
    # ============================================================
    print(f"\n    🤖 Generating AI recommendation...")
    news_sentiment = 0.0  # No news for backtest

    try:
        ai_client = MiniMaxClient()  # Same as live system
        # Prepare analysis dict similar to live
        analysis_dict = {
            "price": current_price,
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "rsi": rsi,
            "rsi_15m": rsi_15m,
            "atr": atr,
            "vwap": vwap,
            "trend": recommendation['trend_direction'],
            "strength": recommendation['trend_strength'],
            "market": market_bias
        }
        ai_rec = ai_client.generate_recommendation(
            code,
            code,
            analysis_dict,
            [],  # No news articles
            news_sentiment
        )

        if ai_rec and isinstance(ai_rec, dict):
            ai_rec_type = ai_rec.get("recommendation", "HOLD")
            print(f"    🤖 AI Recommendation: {ai_rec_type} ({ai_rec.get('confidence', 'N/A')})")

            # Use AI as final decision (same as live)
            if ai_rec_type in ["BUY", "SELL", "HOLD", "AVOID"]:
                recommendation["recommendation"] = ai_rec_type
                recommendation["confidence"] = ai_rec.get("confidence", recommendation["confidence"])
                recommendation["stop"] = ai_rec.get("stop_loss", recommendation["stop"])
                recommendation["target"] = ai_rec.get("target_price", recommendation["target"])
                recommendation["rr"] = ai_rec.get("risk_reward", recommendation["rr"])
                if ai_rec.get("reasons"):
                    recommendation["reasons"] = ai_rec["reasons"]
                if ai_rec.get("warnings"):
                    recommendation["warnings"] = ai_rec["warnings"]

            recommendation["ai_recommendation"] = ai_rec
            recommendation["sentiment"] = news_sentiment
        else:
            print(f"    ⚠️ AI returned invalid response, using technical")
    except Exception as e:
        print(f"    ⚠️ AI error: {e}, using technical recommendation")

    print(f"\n  📊 Recommendation: {recommendation['recommendation']}")
    print(f"    Confidence: {recommendation['confidence']}")
    print(f"    Trend: {recommendation['trend_direction']} ({recommendation['trend_strength']})")
    print(f"    Entry: ${recommendation['entry']:.2f}")
    print(f"    Stop: ${recommendation['stop']:.2f}")
    print(f"    Target: ${recommendation['target']:.2f}")
    print(f"    R:R = {recommendation['rr']}")

    if recommendation['reasons']:
        print(f"\n  Reasons:")
        for r in recommendation['reasons']:
            print(f"    - {r}")

    if recommendation['warnings']:
        print(f"\n  Warnings:")
        for w in recommendation['warnings']:
            print(f"    - {w}")

    # Save portfolio file
    if recommendation['recommendation'] in ["BUY", "SELL"]:
        timestamp = target_dt.strftime('%Y-%m-%d %H:%M:%S')
        portfolio = {
            "timestamp": timestamp,
            "data_source": data_source,
            "results": [{
                "code": code,
                "stock_name": code,
                "recommendation": recommendation['recommendation'],
                "entry": recommendation['entry'],
                "stop": recommendation['stop'],
                "target": recommendation['target'],
                "confidence": recommendation['confidence'],
                "timestamp": timestamp,
                "analysis": {
                    "price": current_price,
                    "ema20": ema20,
                    "ema50": ema50,
                    "rsi": rsi,
                    "atr": atr,
                    "vwap": vwap,
                    "atr_pct": recommendation['atr_pct'],
                    "vwap_distance": recommendation['vwap_distance'],
                    "trend_direction": recommendation['trend_direction'],
                    "trend_strength": recommendation['trend_strength'],
                    "market_bias": market_bias,
                }
            }]
        }

        timestamp_short = target_dt.strftime('%Y-%m-%d_%H-%M-%S')
        filename = f"portfolio_{code.upper()}_{timestamp_short}.json"
        filepath = os.path.join(output_dir, filename)

        with open(filepath, 'w') as f:
            json.dump(portfolio, f, indent=2)

        print(f"\n  ✅ Saved to {filepath}")

    return recommendation


def main():
    parser = argparse.ArgumentParser(description='Backtest stock analysis (matches live system)')
    parser.add_argument('code', help='Stock code (e.g., nvda, 700)')
    parser.add_argument('datetime', help='Target datetime (YYYY-MM-DD HH:MM HKT)')
    parser.add_argument('-o', '--output', default='.', help='Output directory')
    parser.add_argument('-y', '--yfinance', action='store_true', help='Use yfinance instead of iTick')

    args = parser.parse_args()

    run_backtest(args.code, args.datetime, args.output, use_yfinance=args.yfinance)


if __name__ == '__main__':
    main()