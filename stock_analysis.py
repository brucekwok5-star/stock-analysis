#!/usr/bin/env python3
"""
Stock Trading v4 HK Final - Advanced HK stock analysis
Combines technical data, news sentiment, and AI trading recommendations.
"""
import warnings
warnings.filterwarnings("ignore")

import requests
import xml.etree.ElementTree as ET
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple, Any
import urllib.parse

# ============================================================================
# CONFIGURATION
# ============================================================================

ITICK_TOKEN = "a782c443a2a5493d873850758154e14876bfd88dfb89470b8b97dff36e7938e3"
HEADERS = {"token": ITICK_TOKEN}

# Rate limiting
API_SLEEP_SECONDS = 15
MAX_RETRIES = 3

# Market
HS50_CODE = "11031"  # Hang Seng Index ETF
HKT = timezone(timedelta(hours=8))

# ============================================================================
# API CLIENT
# ============================================================================

class ITickClient:
    """iTick API client with rate limiting."""

    def __init__(self, token: str, region: str = "HK"):
        self.token = token
        self.base_url = "https://api.itick.org"
        self.headers = {"token": token, "accept": "application/json"}
        self.last_request_time = 0
        self.region = region

    def _rate_limit(self):
        """Enforce 15-second rate limit between API calls."""
        elapsed = time.time() - self.last_request_time
        if elapsed < API_SLEEP_SECONDS:
            sleep_time = API_SLEEP_SECONDS - elapsed
            print(f"  ⏳ Rate limiting: sleeping {sleep_time:.1f}s...")
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def _request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make API request with retry logic."""
        url = f"{self.base_url}{endpoint}"
        params = params or {}

        for attempt in range(MAX_RETRIES):
            try:
                self._rate_limit()
                response = requests.get(url, headers=self.headers, params=params, timeout=30)

                if response.status_code == 429:
                    print(f"  ⚠️ Rate limited (429), doubling sleep to 30s...")
                    time.sleep(30)
                    continue

                if response.status_code != 200:
                    print(f"  ❌ API error: {response.status_code}")
                    return None

                data = response.json()
                if data.get("code") != 0:
                    print(f"  ❌ API error: {data.get('msg', 'Unknown error')}")
                    return None

                return data.get("data")

            except requests.exceptions.RequestException as e:
                print(f"  ❌ Request error (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(5)
                else:
                    return None

        return None

    # Cache for stock list
    _stock_list_cache = None
    _stock_list_time = 0

    def get_stock_info(self, code: str) -> Optional[Dict]:
        """Fetch stock info for HK stock using stock list."""
        # Use cached stock list to get name
        current_time = time.time()

        # Refresh cache every hour
        if not ITickClient._stock_list_cache or (current_time - ITickClient._stock_list_time) > 3600:
            ITickClient._stock_list_cache = self._request("/stock/list", {"region": self.region, "limit": 5000})
            ITickClient._stock_list_time = current_time

        # Also get quote for current price
        quote = self.get_quote(code)

        # _stock_list_cache is a list (from data.get("data"))
        if ITickClient._stock_list_cache and isinstance(ITickClient._stock_list_cache, list):
            for stock in ITickClient._stock_list_cache:
                if stock.get("c") == code:
                    info = {
                        "n": stock.get("n", ""),  # Name
                        "lotSize": stock.get("ls", 100),  # Lot size
                    }
                    if quote:
                        info["p"] = quote.get("p", 0)  # Current price
                        info["o"] = quote.get("o", 0)
                        info["h"] = quote.get("h", 0)
                        info["l"] = quote.get("l", 0)
                        info["v"] = quote.get("v", 0)
                    return info

        return {"n": "Unknown", "lotSize": 100, "p": quote.get("p", 0) if quote else 0} if quote else None

    def get_quote(self, code: str) -> Optional[Dict]:
        """Fetch current quote for a stock."""
        return self._request("/stock/quote", {"region": self.region, "code": code})

    def get_kline(self, code: str, ktype: int = 1, limit: int = 200) -> Optional[List]:
        """Fetch Kline data. kType: 1=1m, 2=5m, 3=15m, 4=30m, 5=60m, 6=24h"""
        # Use /stock/klines (plural) endpoint with 'codes' parameter
        data = self._request("/stock/klines", {"region": self.region, "codes": code, "kType": ktype, "limit": limit})
        if data and code in data:
            return data[code]
        return None


# ============================================================================
# NEWS CLIENT
# ============================================================================

class NewsClient:
    """Google News RSS client."""

    def search(self, query: str, hours: int = 48) -> List[Dict]:
        """Search Google News RSS for query."""
        url = "https://news.google.com/rss/search"
        params = {
            "q": f"{query} stock target price OR rating",
            "after": f"{hours}h" if hours else None,
            "hl": "en-US",
            "gl": "US"
        }
        params = {k: v for k, v in params.items() if v}

        try:
            response = requests.get(url, params=params, timeout=30)
            if response.status_code != 200:
                return []

            return self._parse_rss(response.text)
        except Exception as e:
            print(f"  ❌ News search error: {e}")
            return []

    def _parse_rss(self, xml_content: str) -> List[Dict]:
        """Parse RSS feed and extract headlines."""
        try:
            root = ET.fromstring(xml_content)
            articles = []

            for item in root.findall(".//item")[:5]:  # Top 5 headlines
                title = item.find("title")
                link = item.find("link")
                pub_date = item.find("pubDate")

                articles.append({
                    "title": title.text if title is not None else "",
                    "link": link.text if link is not None else "",
                    "pubDate": pub_date.text if pub_date is not None else ""
                })

            return articles
        except Exception as e:
            print(f"  ❌ RSS parse error: {e}")
            return []


# ============================================================================
# TECHNICAL ANALYSIS
# ============================================================================

class TechnicalAnalyzer:
    """Technical analysis calculations."""

    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> List[float]:
        """Calculate Exponential Moving Average. Uses shorter period if insufficient data."""
        if len(prices) < 2:
            return []

        # If not enough data for requested period, use what's available
        actual_period = min(period, len(prices))
        multiplier = 2 / (actual_period + 1)

        # Start with SMA
        sma = sum(prices[:actual_period]) / actual_period
        ema = [sma] * actual_period

        for price in prices[actual_period:]:
            ema.append((price - ema[-1]) * multiplier + ema[-1])

        return ema

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> List[float]:
        """Calculate Relative Strength Index. Uses shorter period if insufficient data."""
        if len(prices) < 3:
            return [50.0]  # Neutral RSI if insufficient data

        rsi = []
        gains = []
        losses = []

        for i in range(1, len(prices)):
            change = prices[i] - prices[i-1]
            gains.append(change if change > 0 else 0)
            losses.append(abs(change) if change < 0 else 0)

        # Use shorter period if insufficient data
        actual_period = min(period, len(gains))

        for i in range(actual_period, len(gains) + 1):
            avg_gain = sum(gains[i-actual_period:i]) / actual_period
            avg_loss = sum(losses[i-actual_period:i]) / actual_period

            if avg_loss == 0:
                rsi.append(100)
            else:
                rs = avg_gain / avg_loss
                rsi.append(100 - (100 / (1 + rs)))

        return rsi

    @staticmethod
    def calculate_atr(high: List[float], low: List[float], close: List[float], period: int = 14) -> List[float]:
        """Calculate Average True Range. Uses shorter period if insufficient data."""
        if len(high) < 2:
            return []

        true_ranges = []
        for i in range(1, len(close)):
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i-1]),
                abs(low[i] - close[i-1])
            )
            true_ranges.append(tr)

        # Use shorter period if insufficient data
        actual_period = min(period, len(true_ranges))

        atr = []
        for i in range(actual_period, len(true_ranges) + 1):
            avg_tr = sum(true_ranges[i-actual_period:i]) / actual_period
            atr.append(avg_tr)

        return atr

    @staticmethod
    def calculate_vwap(high: List[float], low: List[float], close: List[float], volume: List[float]) -> float:
        """Calculate Volume Weighted Average Price."""
        if not all([high, low, close, volume]) or len(high) != len(volume):
            return 0.0

        typical_price = [(h + l + c) / 3 for h, l, c in zip(high, low, close)]
        pv = [tp * v for tp, v in zip(typical_price, volume)]

        if sum(volume) == 0:
            return typical_price[-1] if typical_price else 0.0

        return sum(pv) / sum(volume)

    @staticmethod
    def calculate_macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict:
        """Calculate MACD (Moving Average Convergence Divergence)."""
        if len(prices) < slow + signal:
            return {"macd": 0, "signal": 0, "histogram": 0, "trend": "NEUTRAL"}

        # Calculate EMAs
        ema_fast = TechnicalAnalyzer._ema(prices, fast)
        ema_slow = TechnicalAnalyzer._ema(prices, slow)

        if len(ema_fast) < signal or len(ema_slow) < signal:
            return {"macd": 0, "signal": 0, "histogram": 0, "trend": "NEUTRAL"}

        # MACD line = EMA_fast - EMA_slow
        macd_line = [f - s for f, s in zip(ema_fast[-len(ema_slow):], ema_slow)]

        # Signal line = EMA of MACD
        signal_line = TechnicalAnalyzer._ema(macd_line, signal)

        if not signal_line:
            return {"macd": 0, "signal": 0, "histogram": 0, "trend": "NEUTRAL"}

        macd = macd_line[-1]
        sig = signal_line[-1]
        histogram = macd - sig

        # Determine trend
        if histogram > 0 and histogram > histogram * 0.1:
            trend = "BULLISH"
        elif histogram < 0 and abs(histogram) > abs(macd) * 0.1:
            trend = "BEARISH"
        else:
            trend = "NEUTRAL"

        return {"macd": macd, "signal": sig, "histogram": histogram, "trend": trend}

    @staticmethod
    def _ema(prices: List[float], period: int) -> List[float]:
        """Helper for MACD calculation."""
        if len(prices) < period:
            return []
        multiplier = 2 / (period + 1)
        ema = [sum(prices[:period]) / period]
        for price in prices[period:]:
            ema.append((price - ema[-1]) * multiplier + ema[-1])
        return ema

    @staticmethod
    def calculate_bollinger_bands(prices: List[float], period: int = 20, std_dev: int = 2) -> Dict:
        """Calculate Bollinger Bands."""
        if len(prices) < period:
            return {"upper": 0, "middle": 0, "lower": 0, "bandwidth": 0, "position": 0}

        # Middle band = SMA
        recent = prices[-period:]
        middle = sum(recent) / period

        # Standard deviation
        variance = sum((p - middle) ** 2 for p in recent) / period
        std = variance ** 0.5

        upper = middle + (std_dev * std)
        lower = middle - (std_dev * std)

        # Bandwidth
        bandwidth = (upper - lower) / middle if middle > 0 else 0

        # Current position (0 = at lower band, 100 = at upper band)
        current = prices[-1]
        if upper != lower:
            position = ((current - lower) / (upper - lower)) * 100
        else:
            position = 50

        return {"upper": upper, "middle": middle, "lower": lower, "bandwidth": bandwidth, "position": position}

    @staticmethod
    def calculate_stochastic(high: List[float], low: List[float], close: List[float], period: int = 14) -> Dict:
        """Calculate Stochastic Oscillator."""
        if len(high) < period or len(low) < period or len(close) < period + 1:
            return {"k": 50, "d": 50, "zone": "NEUTRAL"}

        recent_high = max(high[-period:])
        recent_low = min(low[-period:])

        if recent_high == recent_low:
            return {"k": 50, "d": 50, "zone": "NEUTRAL"}

        # %K = (Current Close - Lowest Low) / (Highest High - Lowest Low) * 100
        k = ((close[-1] - recent_low) / (recent_high - recent_low)) * 100

        # %D = SMA of %K
        k_values = []
        for i in range(period, len(close)):
            h = max(high[i-period:i])
            l = min(low[i-period:i])
            if h != l:
                k_val = ((close[i] - l) / (h - l)) * 100
                k_values.append(k_val)

        d = sum(k_values[-3:]) / 3 if len(k_values) >= 3 else k

        # Zone
        if k > 80:
            zone = "OVERBOUGHT"
        elif k < 20:
            zone = "OVERSOLD"
        else:
            zone = "NEUTRAL"

        return {"k": k, "d": d, "zone": zone}

    @staticmethod
    def detect_patterns(candles: List[Dict]) -> Dict[str, Any]:
        """Analyze last 5 candles for patterns."""
        if len(candles) < 5:
            return {"pattern": "UNKNOWN", "signal": "NEUTRAL"}

        last_5 = candles[-5:]

        # Extract data
        closes = [c["c"] for c in last_5]
        opens = [c["o"] for c in last_5]
        highs = [c["h"] for c in last_5]
        lows = [c["l"] for c in last_5]
        volumes = [c.get("v", 0) for c in last_5]

        patterns = []
        signal = "NEUTRAL"

        # Current candle
        curr = last_5[-1]
        curr_bullish = curr["c"] > curr["o"]

        # Check for volume spike
        avg_volume = sum(volumes[:-1]) / 4 if len(volumes) > 1 else volumes[0]
        volume_spike = volumes[-1] > avg_volume * 1.5

        # Hammer (bullish reversal)
        body = abs(curr["c"] - curr["o"])
        lower_wick = min(curr["o"], curr["c"]) - curr["l"]
        upper_wick = curr["h"] - max(curr["o"], curr["c"])
        if lower_wick > body * 2 and upper_wick < body:
            patterns.append("HAMMER")
            signal = "BULLISH"

        # Shooting Star (bearish reversal)
        if upper_wick > body * 2 and lower_wick < body:
            patterns.append("SHOOTING_STAR")
            signal = "BEARISH"

        # Bullish Engulfing
        if len(last_5) >= 2:
            prev = last_5[-2]
            if prev["c"] < prev["o"] and curr["c"] > curr["o"]:
                if curr["o"] < prev["c"] and curr["c"] > prev["o"]:
                    patterns.append("BULLISH_ENGULFING")
                    signal = "BULLISH"

            # Bearish Engulfing
            if prev["c"] > prev["o"] and curr["c"] < curr["o"]:
                if curr["o"] > prev["c"] and curr["c"] < prev["o"]:
                    patterns.append("BEARISH_ENGULFING")
                    signal = "BEARISH"

        # Morning Star (3-candle bullish)
        if len(last_5) >= 3:
            c1, c2, c3 = last_5[-3], last_5[-2], last_5[-1]
            if c1["c"] < c1["o"] and c3["c"] > c3["o"] and c3["c"] > (c1["o"] + c1["c"]) / 2:
                patterns.append("MORNING_STAR")
                signal = "BULLISH"

        # Evening Star (3-candle bearish)
        if len(last_5) >= 3:
            c1, c2, c3 = last_5[-3], last_5[-2], last_5[-1]
            if c1["c"] > c1["o"] and c3["c"] < c3["o"] and c3["c"] < (c1["o"] + c1["c"]) / 2:
                patterns.append("EVENING_STAR")
                signal = "BEARISH"

        # Volume spike confirmation
        if volume_spike:
            if curr_bullish:
                patterns.append("VOLUME_SPIKE_BULL")
            else:
                patterns.append("VOLUME_SPIKE_BEAR")

        return {
            "pattern": ",".join(patterns) if patterns else "NONE",
            "signal": signal,
            "volume_spike": volume_spike
        }


# ============================================================================
# AI CLIENT (MiniMax)
# ============================================================================

MINIMAX_API_KEY = "sk-cp-Ssq7KhTUX8bJJnroMymIFBn87GWi3K3fmfHpJ2poY4nI5MUUFPeVknVRwI9nCl2SqmfU2kQ-rQwRuRUmZDXUWOuZE_Nvl-voI3yTabGu5C-dK-KhCSA1GbA"
MINIMAX_BASE_URL = "https://api.minimaxi.com/anthropic"

class MiniMaxClient:
    """MiniMax AI client for sentiment and recommendation."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or MINIMAX_API_KEY
        self.base_url = MINIMAX_BASE_URL

    def analyze_sentiment(self, headlines: List[Dict]) -> float:
        """Use AI to analyze news sentiment."""
        if not headlines:
            return 0.0

        headlines_text = "\n".join([f"- {a.get('title', '')}" for a in headlines])

        prompt = f"""Analyze the sentiment of these news headlines for a Hong Kong stock. Return a JSON with:
{{
  "sentiment_score": -1 to +1 (positive is bullish, negative is bearish),
  "summary": "brief explanation"
}}

Headlines:
{headlines_text}

Return ONLY valid JSON."""

        try:
            result = self._call_api(prompt)
            if result:
                import re
                # Extract JSON from response
                json_match = re.search(r'\{[^{}]*\}', result, re.DOTALL)
                if json_match:
                    data = json.loads(json_match.group())
                    return float(data.get("sentiment_score", 0))
        except Exception as e:
            print(f"    ⚠️ AI sentiment error: {e}")

        return 0.0

    def generate_recommendation(self, stock_code: str, stock_name: str, analysis: Dict,
                                 news: List[Dict], sentiment: float) -> Dict:
        """Use AI to generate trading recommendation based on all criteria."""

        # Format technical data
        price = analysis.get("price", 0)
        rsi = analysis.get("rsi", 50)
        ema20 = analysis.get("ema20", 0)
        ema50 = analysis.get("ema50", 0)
        atr = analysis.get("atr", 0)
        atr_pct = (atr / price * 100) if price > 0 else 0
        vwap = analysis.get("vwap", 0)
        vwap_dist = abs(price - vwap) / price * 100 if price > 0 else 0
        trend = analysis.get("patterns", {}).get("signal", "NEUTRAL")

        # New indicators
        macd = analysis.get("macd", {})
        macd_hist = macd.get("histogram", 0)
        macd_trend = macd.get("trend", "NEUTRAL")
        bollinger = analysis.get("bollinger", {})
        bb_position = bollinger.get("position", 50)
        stoch = analysis.get("stochastic", {})
        stoch_k = stoch.get("k", 50)
        stoch_d = stoch.get("d", 50)
        stoch_zone = stoch.get("zone", "NEUTRAL")

        # Format news
        headlines = "\n".join([f"- {a.get('title', '')}" for a in news[:5]]) if news else "No recent news"

        prompt = f"""You are an expert day trader specializing in high-probability setups. Analyze this stock and provide a recommendation.

STOCK: {stock_name} ({stock_code})

TECHNICAL DATA:
- Price: ${price}
- RSI(14): {rsi:.1f} (overbought>70, oversold<30)
- EMA20: {ema20:.2f}, EMA50: {ema50:.2f}
- ATR: {atr:.4f} ({atr_pct:.1f}%)
- VWAP: {vwap:.2f} (distance: {vwap_dist:.1f}%)
- Trend Signal: {trend}

ADVANCED INDICATORS:
- MACD Histogram: {macd_hist:.4f} (trend: {macd_trend})
- Bollinger Bands: {bb_position:.1f}% position (0=lower, 100=upper)
- Stochastic: K={stoch_k:.1f}, D={stoch_d:.1f} ({stoch_zone})

NEWS HEADLINES:
{headlines}

NEWS SENTIMENT: {sentiment:.2f} (-1 bearish, +1 bullish)

STRATEGY RULES:
1. STRONG trend: Price above EMA20 AND EMA20 above EMA50
2. RSI zone: 35-70 bullish zone, <30 oversold, >70 overbought
3. ATR > 1.5% (good volatility for day trading)
4. VWAP distance > 1% (good entry timing)
5. MACD histogram > 0 confirms bullish, < 0 confirms bearish
6. Stochastic: K above D and in oversold zone (<20) = BUY signal
7. Bollinger: Price near lower band = oversold, near upper = overbought
8. Combine multiple confirmations for higher confidence

Return ONLY a JSON object. Example format:
{{"recommendation": "BUY", "confidence": "HIGH", "entry_price": 20.5, "stop_loss": 19.99, "target_price": 21.11, "risk_reward": "3:1", "reasons": ["reason"], "warnings": []}}"""

        try:
            result = self._call_api(prompt)
            if result:
                print(f"    🤖 Raw AI response: {result[:300]}...")

                # Try JSON first
                import re
                json_match = re.search(r'\{[\s\S]*\}', result)
                if json_match:
                    try:
                        return json.loads(json_match.group())
                    except:
                        pass

                # Fallback: extract from text
                rec = {"recommendation": "HOLD", "confidence": "LOW", "reasons": [], "warnings": []}

                # Extract recommendation
                if "BUY" in result.upper() and "HOLD" not in result.upper():
                    rec["recommendation"] = "BUY"
                elif "SELL" in result.upper():
                    rec["recommendation"] = "SELL"

                # Extract confidence
                if "HIGH" in result.upper():
                    rec["confidence"] = "HIGH"
                elif "MEDIUM" in result.upper():
                    rec["confidence"] = "MEDIUM"

                rec["entry_price"] = price
                rec["stop_loss"] = round(price * 0.975, 2)
                rec["target_price"] = round(price * 1.03, 2)
                rec["risk_reward"] = "3:1"
                rec["reasons"] = ["AI analysis (text parse)"]

                return rec
        except Exception as e:
            print(f"    ⚠️ AI recommendation error: {e}")

        return {
            "recommendation": "HOLD",
            "confidence": "LOW",
            "reasons": ["AI analysis failed"],
            "warnings": ["Using rule-based recommendation"]
        }

    def _call_api(self, prompt: str) -> str:
        """Call MiniMax API."""
        url = f"{self.base_url}/v1/messages"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "MiniMax-M2.1",
            "max_tokens": 1024,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
            if response.status_code == 200:
                data = response.json()
                # MiniMax uses different format - content is in a list
                content = data.get("content", [])
                if content and isinstance(content, list):
                    # Get the text from the content array
                    text = content[0].get("text", "") or content[0].get("thinking", "")
                    return text
                return ""
            else:
                print(f"    ⚠️ MiniMax API error: {response.status_code}")
        except Exception as e:
            print(f"    ⚠️ API exception: {e}")

        return None


# ============================================================================
# SENTIMENT ANALYSIS
# ============================================================================

class SentimentAnalyzer:
    """Simple news sentiment scoring."""

    BULLISH_WORDS = ["upgrade", "buy", "target", "bullish", "outperform",
                     "upgrade", "raise", "positive", "growth", "profit",
                     "beat", "surge", "rally", "gain", "higher"]

    BEARISH_WORDS = ["downgrade", "sell", "bearish", "underperform",
                     "cut", "lower", "negative", "loss", "miss",
                     "drop", "fall", "decline", "warning", "risk"]

    @classmethod
    def score_headline(cls, headline: str) -> float:
        """Score headline sentiment from -1 to +1."""
        headline = headline.lower()

        bullish_count = sum(1 for word in cls.BULLISH_WORDS if word in headline)
        bearish_count = sum(1 for word in cls.BEARISH_WORDS if word in headline)

        total = bullish_count + bearish_count
        if total == 0:
            return 0.0

        return (bullish_count - bearish_count) / total

    @classmethod
    def score_articles(cls, articles: List[Dict]) -> Tuple[float, List[Dict]]:
        """Score list of articles and return average sentiment."""
        if not articles:
            return 0.0, []

        scored = []
        for article in articles:
            score = cls.score_headline(article["title"])
            scored.append({**article, "sentiment": score})

        avg_sentiment = sum(a["sentiment"] for a in scored) / len(scored)

        # Clamp to -1 to +1
        avg_sentiment = max(-1.0, min(1.0, avg_sentiment))

        return avg_sentiment, scored


# ============================================================================
# MAIN ANALYZER
# ============================================================================

class HKStockAnalyzer:
    """Main analyzer for HK and US stocks."""

    def __init__(self, code: str, use_ai: bool = True):
        self.code = code

        # Detect region based on ticker format (HK = digits only, US = letters)
        self.region = "HK" if code.isdigit() else "US"
        self.itick = ITickClient(ITICK_TOKEN, region=self.region)

        self.news = NewsClient()
        self.tech = TechnicalAnalyzer()
        self.sentiment = SentimentAnalyzer()
        self.use_ai = use_ai
        self.ai = MiniMaxClient() if use_ai else None

        # Results storage
        self.stock_info = None
        self.market_bias = "NEUTRAL"
        self.klines = {}
        self.news_articles = []
        self.news_sentiment = 0.0
        self.ai_sentiment = 0.0
        self.ai_recommendation = None

    def run(self, stock_index: int = 0, total_stocks: int = 1) -> Dict:
        """Execute full analysis workflow."""
        steps = [
            "Market Context",
            "Stock Info",
            "News Fetch",
            "Klines (1H)",
            "Klines (5m)",
            "Klines (15m)",
            "Tech Analysis",
            "Recommendation",
        ]
        if self.use_ai:
            steps.append("AI Decision")

        self._total_steps = len(steps)
        self._current_step = 0

        def update_progress(step_name: str):
            self._current_step += 1
            bar_width = 30
            filled = int(bar_width * self._current_step / self._total_steps)
            bar = "█" * filled + "░" * (bar_width - filled)
            pct = int(100 * self._current_step / self._total_steps)
            print(f"\r  [{bar}] {pct}% | Stock {stock_index}/{total_stocks} | {step_name}...", end="", flush=True)

        print(f"\n{'='*60}")
        print(f"  📊 {self.region} Stock Analysis: {self.code}")
        print(f"  🕐 {datetime.now(HKT).strftime('%Y-%m-%d %H:%M:%S HKT')}")
        print(f"{'='*60}\n")

        # Progress bar header
        print(f"\r  Progress: ", end="", flush=True)

        # Step 1: Market Context
        update_progress("Market Context")
        self._analyze_market_context()

        # Step 2: Stock Identity & News
        update_progress("Stock Info")
        self._fetch_stock_info()

        update_progress("News Fetch")
        self._fetch_news()

        # Step 3: Multi-Timeframe Fetch
        update_progress("Klines (1H)")
        self._fetch_klines()

        # Step 4 & 5: Technical Analysis & Patterns
        update_progress("Tech Analysis")
        analysis = self._calculate_indicators()

        # Generate rule-based recommendation
        if not self.use_ai or not self.ai:
            update_progress("Recommendation")
        else:
            update_progress("Recommendation")

        recommendation = self._generate_recommendation(analysis)

        # Step 6: AI Recommendation (FINAL DECISION)
        if self.use_ai and self.ai:
            update_progress("AI Decision")
            print(f"\n    🤖 Generating AI recommendation...")
            self.ai_recommendation = self.ai.generate_recommendation(
                self.code,
                self.stock_info.get("n", "") if self.stock_info else "",
                analysis,
                self.news_articles,
                self.news_sentiment
            )
            print(f"    🤖 AI Recommendation: {self.ai_recommendation.get('recommendation', 'N/A')}")
            print(f"    🤖 AI Confidence: {self.ai_recommendation.get('confidence', 'N/A')}")

            # Use AI as FINAL decision
            ai_rec = self.ai_recommendation.get("recommendation", "HOLD")
            if ai_rec in ["BUY", "SELL", "HOLD"]:
                recommendation["recommendation"] = ai_rec
                recommendation["confidence"] = self.ai_recommendation.get("confidence", "LOW")
                recommendation["stop"] = self.ai_recommendation.get("stop_loss", 0)
                recommendation["target"] = self.ai_recommendation.get("target_price", 0)
                recommendation["rr"] = self.ai_recommendation.get("risk_reward", "0:1")

                # Add AI reasons
                ai_reasons = self.ai_recommendation.get("reasons", [])
                if ai_reasons:
                    recommendation["reasons"] = ai_reasons
                ai_warnings = self.ai_recommendation.get("warnings", [])
                if ai_warnings:
                    recommendation["warnings"] = ai_warnings

            recommendation["ai_recommendation"] = self.ai_recommendation
            recommendation["ai_sentiment"] = self.ai_sentiment

        # Complete the progress bar
        bar_width = 30
        print(f"\r  {'█' * bar_width} 100% | Stock {stock_index}/{total_stocks} | Done! ")
        print()

        return recommendation

    def _analyze_market_context(self):
        """Analyze HS50 to determine market bias."""
        print(f"  Fetching HS50 (Hang Seng Index ETF)...")
        kline = self.itick.get_kline(HS50_CODE, ktype=5, limit=100)  # 1H

        if not kline:
            print("  ⚠️ Could not fetch HS50 data, defaulting to NEUTRAL")
            self.market_bias = "NEUTRAL"
            return

        closes = [k["c"] for k in kline]
        ema20 = self.tech.calculate_ema(closes, 20)
        ema50 = self.tech.calculate_ema(closes, 50)

        if not ema20 or not ema50:
            self.market_bias = "NEUTRAL"
            return

        price = closes[-1]
        e20 = ema20[-1]
        e50 = ema50[-1]

        print(f"    Price: {price:.2f}, EMA20: {e20:.2f}, EMA50: {e50:.2f}")

        if price > e20 and e20 > e50:
            self.market_bias = "BULLISH"
            print(f"    🟢 Market Bias: BULLISH")
        elif price < e20 and e20 < e50:
            self.market_bias = "BEARISH"
            print(f"    🔴 Market Bias: BEARISH")
        else:
            self.market_bias = "NEUTRAL"
            print(f"    🟡 Market Bias: NEUTRAL/MIXED")

    def _fetch_stock_info(self):
        """Fetch stock information."""
        print(f"  Fetching stock info...")
        self.stock_info = self.itick.get_stock_info(self.code)

        if not self.stock_info:
            print(f"  ❌ Ticker Unavailable: {self.code}")
            return

        name = self.stock_info.get("n", "Unknown")
        lot_size = self.stock_info.get("lotSize", 0)
        price = self.stock_info.get("p", 0)

        print(f"    Name: {name}")
        print(f"    Lot Size: {lot_size}")
        print(f"    Current Price: {price}")

        self.stock_name = name

    def _fetch_news(self):
        """Fetch and analyze news."""
        # For US stocks, use ticker code if stock_name is not available
        search_term = self.stock_name if (hasattr(self, 'stock_name') and self.stock_name) else self.code

        if not search_term:
            print("  ⚠️ No stock name available for news search")
            return

        print(f"  Searching news for: {search_term}...")
        query = urllib.parse.quote_plus(search_term)

        self.news_articles = self.news.search(query)
        self.news_sentiment, scored = self.sentiment.score_articles(self.news_articles)

        print(f"    Found {len(self.news_articles)} articles")
        print(f"    Sentiment Score: {self.news_sentiment:.2f} (rule-based)")

        for i, article in enumerate(scored, 1):
            emoji = "🟢" if article["sentiment"] > 0 else "🔴" if article["sentiment"] < 0 else "🟡"
            print(f"    {i}. {emoji} {article['title'][:60]}...")

        # AI Sentiment Analysis
        if self.use_ai and self.ai and self.news_articles:
            print(f"    🤖 Running AI sentiment analysis...")
            self.ai_sentiment = self.ai.analyze_sentiment(self.news_articles)
            print(f"    🤖 AI Sentiment Score: {self.ai_sentiment:.2f}")
            # Use AI sentiment if available
            if self.ai_sentiment != 0:
                self.news_sentiment = self.ai_sentiment

    def _fetch_klines(self):
        """Fetch multi-timeframe kline data."""
        # kType: 1=1m, 2=5m, 3=15m, 4=30m, 5=60m, 6=24h, 7=7d, 8=30d
        # 1H for trend, 5m/15m for entry points
        timeframes = [
            (5, "1H", 200),   # 60m = 1 Hour - for trend
            (2, "5m", 200),   # 5m - entry timing
            (3, "15m", 200)  # 15m - entry confirmation
        ]

        for ktype, name, limit in timeframes:
            print(f"  Fetching {name} data...")
            self.klines[name] = self.itick.get_kline(self.code, ktype=ktype, limit=limit)

            if self.klines[name]:
                print(f"    ✓ Got {len(self.klines[name])} candles")
            else:
                print(f"    ⚠️ No {name} data available")
                self.klines[name] = []

    def _calculate_indicators(self) -> Dict:
        """Calculate all technical indicators."""
        analysis = {}

        # Get kline data from all timeframes
        kline_1h = self.klines.get("1H", [])   # Trend
        kline_5m = self.klines.get("5m", [])    # Entry timing
        kline_15m = self.klines.get("15m", [])  # Entry confirmation

        if not kline_1h:
            return analysis

        # Use 1D for longer-term indicators (more historical context)
        # Use 1H for main indicators (trend)
        main_kline = kline_1h

        closes = [k["c"] for k in main_kline]
        highs = [k["h"] for k in main_kline]
        lows = [k["l"] for k in main_kline]
        volumes = [k.get("v", 0) for k in main_kline]

        # Current values - use quote price if available
        current_price = closes[-1] if closes else 0
        if self.stock_info and self.stock_info.get("p"):
            current_price = self.stock_info.get("p", current_price)

        # EMAs - use available data
        ema20 = self.tech.calculate_ema(closes, 20)
        ema50 = self.tech.calculate_ema(closes, 50)
        ema200 = self.tech.calculate_ema(closes, 200)

        analysis["price"] = current_price
        analysis["ema20"] = ema20[-1] if ema20 else 0
        analysis["ema50"] = ema50[-1] if ema50 else 0
        analysis["ema200"] = ema200[-1] if ema200 else 0

        # RSI
        rsi = self.tech.calculate_rsi(closes)
        analysis["rsi"] = rsi[-1] if rsi else 50

        # ATR - estimate from price if not enough data
        atr = self.tech.calculate_atr(highs, lows, closes)
        if not atr and current_price > 0:
            # Estimate ATR as 2% of price if no data
            analysis["atr"] = current_price * 0.02
        else:
            analysis["atr"] = atr[-1] if atr else current_price * 0.02

        # VWAP from 5m (entry timing)
        if kline_5m:
            highs_5m = [k["h"] for k in kline_5m]
            lows_5m = [k["l"] for k in kline_5m]
            closes_5m = [k["c"] for k in kline_5m]
            volumes_5m = [k.get("v", 0) for k in kline_5m]
            analysis["vwap"] = self.tech.calculate_vwap(highs_5m, lows_5m, closes_5m, volumes_5m)
        else:
            analysis["vwap"] = current_price  # Use current price as fallback

        # MACD
        analysis["macd"] = self.tech.calculate_macd(closes)

        # Bollinger Bands
        analysis["bollinger"] = self.tech.calculate_bollinger_bands(closes)

        # Stochastic Oscillator
        analysis["stochastic"] = self.tech.calculate_stochastic(highs, lows, closes)

        # Patterns on 1H (trend) and 5m (entry)
        analysis["patterns"] = self.tech.detect_patterns(kline_1h if kline_1h else main_kline)

        # Price change
        if len(closes) > 1:
            analysis["change_pct"] = ((closes[-1] - closes[-2]) / closes[-2]) * 100
        else:
            analysis["change_pct"] = 0

        # Print summary
        print(f"    Price: {analysis['price']:.2f}")
        print(f"    EMA20: {analysis['ema20']:.2f}, EMA50: {analysis['ema50']:.2f}, EMA200: {analysis['ema200']:.2f}")
        print(f"    RSI(14): {analysis['rsi']:.1f}")
        print(f"    ATR(14): {analysis['atr']:.4f}")
        print(f"    VWAP: {analysis['vwap']:.2f}")
        print(f"    MACD: {analysis['macd'].get('histogram', 0):.4f} ({analysis['macd'].get('trend', 'NEUTRAL')})")
        print(f"    Bollinger: {analysis['bollinger'].get('position', 50):.1f}% (Upper: {analysis['bollinger'].get('upper', 0):.2f})")
        print(f"    Stochastic: K={analysis['stochastic'].get('k', 50):.1f}, D={analysis['stochastic'].get('d', 50):.1f} ({analysis['stochastic'].get('zone', 'NEUTRAL')})")
        print(f"    Pattern: {analysis['patterns']['pattern']} ({analysis['patterns']['signal']})")

        return analysis

    def _generate_recommendation(self, analysis: Dict) -> Dict:
        """Generate trading recommendation using multi-timeframe strategy."""
        stock_name = self.stock_info.get("n", "") if self.stock_info else ""

        if not analysis or analysis.get("price", 0) == 0:
            return {
                "recommendation": "HOLD",
                "confidence": "LOW",
                "entry": 0,
                "stop": 0,
                "target": 0,
                "rr": "0:1",
                "reasons": ["Insufficient data for analysis"],
                "warnings": ["Ticker unavailable or no data"],
                "stock_name": stock_name,
                "market_bias": self.market_bias,
                "analysis": analysis,
                "news": [],
                "sentiment": 0.0,
                "trend_strength": "WEAK",
                "pattern_type": "NONE"
            }

        # Extract data
        price = analysis["price"]
        ema20 = analysis["ema20"]
        ema50 = analysis["ema50"]
        ema200 = analysis["ema200"]
        rsi = analysis["rsi"]
        atr = analysis["atr"]
        vwap = analysis.get("vwap", price)
        pattern_signal = analysis["patterns"]["signal"]
        pattern_name = analysis["patterns"]["pattern"]

        # Get 1H data for trend analysis
        kline_1h = self.klines.get("1H", [])
        kline_5m = self.klines.get("5m", [])
        kline_15m = self.klines.get("15m", [])

        # Calculate ATR as percentage
        atr_pct = (atr / price * 100) if price > 0 else 0

        reasons = []
        warnings = []
        reject_reasons = []

        # ============================================================
        # STEP 1: STRICT TREND IDENTIFICATION (1H)
        # ============================================================
        trend_strength = "WEAK"
        trend_direction = "NEUTRAL"

        if kline_1h and len(kline_1h) >= 5:
            closes_1h = [k["c"] for k in kline_1h]

            # Check for higher highs/lows (strong trend)
            higher_highs = sum(1 for i in range(2, len(closes_1h)-1) if closes_1h[i] > closes_1h[i-1] and closes_1h[i] > closes_1h[i+1])
            lower_lows = sum(1 for i in range(2, len(closes_1h)-1) if closes_1h[i] < closes_1h[i-1] and closes_1h[i] < closes_1h[i+1])

            # EMA alignment check - handle equal EMAs
            ema_diff = abs(ema20 - ema50) / ema20 * 100 if ema20 > 0 else 0

            if ema20 > 0 and ema50 > 0 and ema_diff > 0.1:
                # Normal EMA alignment
                ema_bullish = price > ema20 > ema50
                ema_bearish = price < ema20 < ema50
            elif ema20 > 0:
                # Fallback: use price vs EMA when EMAs are equal
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

        # MANDATORY FILTER: Check 1h trend strength (accept MODERATE or STRONG)
        if trend_strength == "WEAK":
            reject_reasons.append(f"1h trend too weak (current: {trend_strength})")

        # ============================================================
        # STEP 2: ATR CHECK (must be > 1.5%)
        # ============================================================
        if atr_pct < 1.5:
            reject_reasons.append(f"ATR {atr_pct:.1f}% < 1.5% (low volatility)")

        # ============================================================
        # STEP 3: ENTRY CRITERIA (15m & 5m)
        # ============================================================
        # Volume analysis
        has_volume_data = False
        volume_spike = False
        if kline_5m and len(kline_5m) >= 10:
            volumes = [k.get("v", 0) for k in kline_5m]
            avg_volume = sum(volumes[:-1]) / max(len(volumes)-1, 1)
            last_volume = volumes[-1] if volumes else 0
            if avg_volume > 0:
                volume_ratio = last_volume / avg_volume
                if volume_ratio >= 1.2:
                    volume_spike = True
                    has_volume_data = True

        if not volume_spike and has_volume_data:
            warnings.append(f"Volume {volume_ratio:.1f}x < 1.2x average")

        # RSI entry zone (expanded for more flexibility)
        rsi_ok = False
        if trend_direction == "BULLISH" and 35 <= rsi <= 70:
            rsi_ok = True
        elif trend_direction == "BEARISH" and 30 <= rsi <= 65:
            rsi_ok = True
        elif rsi < 25 or rsi > 75:
            reject_reasons.append(f"RSI {rsi:.1f} not in optimal zone")

        # VWAP distance
        vwap_dist = abs(price - vwap) / price * 100 if price > 0 else 0
        vwap_ok = vwap_dist > 1.0

        if not vwap_ok:
            warnings.append(f"Price only {vwap_dist:.1f}% from VWAP")

        # ============================================================
        # STEP 4: PATTERN RECOGNITION
        # ============================================================
        pattern_type = "NONE"
        if pattern_signal == "BULLISH":
            pattern_type = "BREAKOUT" if volume_spike else "MOMENTUM"
        elif pattern_signal == "BEARISH":
            pattern_type = "BREAKOUT" if volume_spike else "MOMENTUM"

        # ============================================================
        # STEP 5: DETERMINE RECOMMENDATION
        # ============================================================

        # Check if we should reject
        if reject_reasons:
            direction = "HOLD"
            confidence = "LOW"
            reasons.extend(reject_reasons)
        else:
            # All criteria met - generate recommendation
            if trend_direction == "BULLISH" and rsi_ok:
                direction = "BUY"
                confidence = "HIGH" if (volume_spike and vwap_ok and trend_strength in ["STRONG_BULLISH", "STRONG_BEARISH"]) else "MEDIUM"
                reasons.append(f"{trend_strength} trend on 1h")
                reasons.append(f"RSI in bullish zone: {rsi:.1f}")
                if volume_spike:
                    reasons.append(f"Volume spike: {volume_ratio:.1f}x")
                if vwap_ok:
                    reasons.append(f"Price {vwap_dist:.1f}% above VWAP")
            elif trend_direction == "BEARISH" and rsi_ok:
                direction = "SELL"
                confidence = "HIGH" if (volume_spike and vwap_ok and trend_strength in ["STRONG_BULLISH", "STRONG_BEARISH"]) else "MEDIUM"
                reasons.append(f"{trend_strength} trend on 1h")
                reasons.append(f"RSI in bearish zone: {rsi:.1f}")
                if volume_spike:
                    reasons.append(f"Volume spike: {volume_ratio:.1f}x")
                if vwap_ok:
                    reasons.append(f"Price {vwap_dist:.1f}% below VWAP")
            else:
                direction = "HOLD"
                confidence = "LOW"
                reasons.append(f"Trend too weak or conditions not met")

        # ============================================================
        # STEP 6: CALCULATE STOP AND TARGET
        # ============================================================

        # Support/Resistance levels
        key_support = ema50 if ema50 > 0 else price * 0.98
        key_resistance = ema20 if ema20 > 0 else price * 1.02

        if direction == "BUY" and atr > 0:
            # Stop: 1.5-2.5% below entry
            stop = price * 0.975  # 2.5% stop
            # Target: 2-3% minimum (using ATR for calculation)
            target = price * 1.03  # 3% target minimum
            # Ensure minimum 1:3 R:R
            risk = price - stop
            if target - price < risk * 3:
                target = price + (risk * 3)
            rr = f"{(target-price)/risk:.1f}:1" if risk > 0 else "0:1"
        elif direction == "SELL" and atr > 0:
            stop = price * 1.025  # 2.5% stop
            target = price * 0.97  # 3% target minimum
            risk = stop - price
            if price - target < risk * 3:
                target = price - (risk * 3)
            rr = f"{(price-target)/risk:.1f}:1" if risk > 0 else "0:1"
        else:
            stop = 0
            target = 0
            rr = "0:1"
            key_support = 0
            key_resistance = 0

        # News sentiment (MANDATORY FILTER - reject if negative)
        if self.news_sentiment > 0.3:
            reasons.append(f"Positive news sentiment: {self.news_sentiment:.2f}")
        elif self.news_sentiment < -0.3:
            # Mandatory filter: reject on negative sentiment
            direction = "HOLD"
            confidence = "LOW"
            reject_reasons.append(f"Negative news sentiment: {self.news_sentiment:.2f}")
            reasons.extend(reject_reasons)

        # Final recommendation mapping
        rec_map = {"BUY": "BUY", "SELL": "SELL", "HOLD": "HOLD"}
        final_rec = rec_map.get(direction, "HOLD")

        return {
            "recommendation": final_rec,
            "confidence": confidence,
            "entry": round(price, 2),
            "stop": round(stop, 2),
            "target": round(target, 2),
            "rr": rr,
            "reasons": reasons,
            "warnings": warnings,
            "stock_name": stock_name,
            "market_bias": trend_direction,
            "trend_strength": trend_strength,
            "pattern_type": pattern_type,
            "key_support": round(key_support, 2),
            "key_resistance": round(key_resistance, 2),
            "analysis": analysis,
            "news": self.news_articles,
            "sentiment": self.news_sentiment,
            "atr_pct": round(atr_pct, 2),
            "vwap_distance": round(vwap_dist, 2)
        }

        return {
            "recommendation": final_rec,
            "confidence": confidence,
            "entry": round(price, 2),
            "stop": round(stop, 2),
            "target": round(target, 2),
            "rr": rr,
            "reasons": reasons,
            "warnings": warnings,
            "analysis": analysis,
            "news": self.news_articles,
            "sentiment": self.news_sentiment,
            "market_bias": self.market_bias,
            "stock_name": stock_name
        }

    def print_report(self, result: Dict):
        """Print formatted analysis report."""
        # Show signal alert banner immediately
        rec = result.get("recommendation", "HOLD")
        if rec in ["BUY", "SELL"]:
            name = self.stock_info.get("n", self.code) if self.stock_info else self.code
            entry = result.get("entry", 0)
            stop = result.get("stop", 0)
            target = result.get("target", 0)
            emoji = "🔔" if rec == "BUY" else "⚠️"
            signal = "BUY" if rec == "BUY" else "SELL"

            print(f"\n" + f"{emoji}"*15)
            print(f"  🚨 {signal} SIGNAL DETECTED!")
            print(f"  📌 {name} ({self.code})")
            print(f"  💰 Entry: ${entry:.2f} | Stop: ${stop:.2f} | Target: ${target:.2f}")
            print(f"  📊 Confidence: {result.get('confidence', 'N/A')}")
            print(f"  🔗 R:R = {result.get('rr', 'N/A')}")
            print(f"  {emoji}"*15 + "\n")

        print(f"\n{'='*65}")
        print("  📊 ANALYSIS REPORT - Multi-Timeframe Day Trading Strategy")
        print(f"{'='*65}")

        name = self.stock_info.get("n", self.code)[:11] if self.stock_info else self.code[:11]
        change = result.get("analysis", {}).get("change_pct", 0)

        # Show AI recommendation if available
        ai_rec = result.get("ai_recommendation", {})
        if ai_rec:
            print(f"\n  🤖 AI Recommendation: {ai_rec.get('recommendation', 'N/A')} ({ai_rec.get('confidence', 'N/A')})")

        # Summary Table
        print(f"\n┌─────────────┬──────┬─────┬───────┬────────┬────────┬────────┬────────┬───────┐")
        print(f"│ Stock       │ Rec  │Confi│ Price │ Today% │ RSI    │ Entry  │ Stop   │ Target│")
        print(f"│ {name:<11} │ {result['recommendation']:<4} │{result['confidence']:^3} │ {result['entry']:>6.2f} │ {change:>5.1f}% │ {result.get('analysis', {}).get('rsi', 0):>5.1f} │ {result['entry']:>6.2f} │ {result['stop']:>6.2f} │ {result['target']:>6.2f} │")
        print(f"└─────────────┴──────┴─────┴───────┴────────┴────────┴────────┴────────┴───────┘")

        # Key Levels
        print(f"\n  📈 Key Levels: Support={result.get('key_support', 0):.2f} | Resistance={result.get('key_resistance', 0):.2f}")
        print(f"  📊 ATR: {result.get('atr_pct', 0):.1f}% | VWAP Dist: {result.get('vwap_distance', 0):.1f}% | R:R = {result['rr']}")

        # Deep Dive
        print(f"\n  🔍 Technical Analysis")
        print(f"  ─" * 25)

        trend_strength = result.get("trend_strength", "WEAK")
        pattern_type = result.get("pattern_type", "NONE")

        print(f"\n  Trend (1H): {result.get('market_bias', 'NEUTRAL')} | Strength: {trend_strength}")
        print(f"  Pattern: {pattern_type}")

        if result.get("analysis"):
            a = result["analysis"]
            print(f"\n  Indicators (1H):")
            print(f"    EMA20:  {a.get('ema20', 0):.2f}")
            print(f"    EMA50:  {a.get('ema50', 0):.2f}")
            print(f"    EMA200: {a.get('ema200', 0):.2f}")
            print(f"    RSI:    {a.get('rsi', 0):.1f}")
            print(f"    ATR:    {a.get('atr', 0):.4f}")
            print(f"    VWAP:   {a.get('vwap', 0):.2f}")

        if result.get("news"):
            print(f"\n  News Headlines:")
            for i, article in enumerate(result["news"], 1):
                print(f"    {i}. {article['title'][:50]}...")

        print(f"\n  Sentiment: {result.get('sentiment', 0):.2f}")

        print(f"\n  ✅ Reasons:")
        for r in result.get("reasons", []):
            print(f"    • {r}")

        if result.get("warnings"):
            print(f"\n  ⚠️ Warnings:")
            for w in result["warnings"]:
                print(f"    • {w}")

        # JSON Output - Full format
        print(f"\n  📋 Recommendation JSON:")
        print(f"  " + "─" * 30)

        json_output = {
            "stock_code": self.code,
            "stock_name": name,
            "technical_recommendation": result["recommendation"],
            "trend_strength": result.get("trend_strength", "WEAK"),
            "confidence_level": result["confidence"],
            "entry_price": result["entry"],
            "stop_loss": result["stop"],
            "target_price": result["target"],
            "risk_reward": result["rr"],
            "key_support": result.get("key_support", 0),
            "key_resistance": result.get("key_resistance", 0),
            "pattern_type": result.get("pattern_type", "NONE"),
            "atr_pct": result.get("atr_pct", 0),
            "vwap_distance": result.get("vwap_distance", 0),
            "reasons": result["reasons"],
            "warnings": result["warnings"]
        }

        print(json.dumps(json_output, indent=2))


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

# Top active stocks lists
TOP_US_STOCKS = [
    "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AMD", "INTC", "NFLX",
    "PLTR", "SOFI", "F", "PLUG", "ONDS", "VG", "SMCI", "GME", "AMC", "BBBY"
]

TOP_HK_STOCKS = [
    "700", "9988", "2318", "3690", "11031", "1211", "1398", "3968", "5", "11",
    "1", "1157", "883", "857", "568", "1919", "2883", "939", "1138", "1921"
]


def main():
    """Main entry point."""
    import sys

    # Get stock codes from command line
    if len(sys.argv) < 2:
        print("Usage: python stock_analysis.py <STOCK_CODES>")
        print("\nExamples:")
        print("  python stock_analysis.py us          # Analyze top US stocks")
        print("  python stock_analysis.py hk          # Analyze top HK stocks")
        print("  python stock_analysis.py nvda,aapl   # Analyze specific US stocks")
        print("  python stock_analysis.py 700,9988    # Analyze specific HK stocks")
        print("  python stock_analysis.py all         # Analyze default HK watchlist")
        print("\nTop US Stocks:", ", ".join(TOP_US_STOCKS[:10]))
        print("Top HK Stocks:", ", ".join(TOP_HK_STOCKS[:10]))
        sys.exit(1)

    # Parse input - support multiple formats:
    # python stock_analysis.py 0700 0001 1157
    # python stock_analysis.py 700 1 1157
    # python stock_analysis.py 700,1,1157
    # python stock_analysis.py "700 1 1157"
    input_arg = sys.argv[1]

    # Check for comma-separated format
    if "," in input_arg:
        codes = [c.strip() for c in input_arg.split(",")]
    else:
        codes = sys.argv[1:]

    # Handle special keywords
    if codes[0].lower() == "us":
        codes = TOP_US_STOCKS[:10]
        print("\n📈 Analyzing Top 10 US Most Active Stocks")
    elif codes[0].lower() == "hk":
        codes = TOP_HK_STOCKS[:10]
        print("\n📈 Analyzing Top 10 HK Most Active Stocks")
    elif codes[0].lower() == "all":
        # Default watchlist - mix of HK stocks
        codes = TOP_HK_STOCKS[:10]
    elif codes[0].lower() == "topus":
        codes = TOP_US_STOCKS
        print("\n📈 Analyzing Top US Most Active Stocks (20)")
    elif codes[0].lower() == "tophk":
        codes = TOP_HK_STOCKS
        print("\n📈 Analyzing Top HK Most Active Stocks (20)")
    else:
        # Keep original code format (don't pad)
        codes = [c for c in codes]

    # Remove duplicates while preserving order
    seen = set()
    unique_codes = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            unique_codes.append(c)
    codes = unique_codes

    print(f"\n🚀 Starting analysis for {len(codes)} stocks: {', '.join(codes)}")

    # Run analysis for each stock
    all_results = []

    for i, code in enumerate(codes):
        print(f"\n{'#'*60}")
        print(f"# Stock {i+1}/{len(codes)}: {code}")
        print(f"{'#'*60}")

        # Run analysis
        analyzer = HKStockAnalyzer(code)

        try:
            result = analyzer.run(stock_index=i+1, total_stocks=len(codes))
            analyzer.print_report(result)
            result["code"] = code
            all_results.append(result)

        except KeyboardInterrupt:
            print("\n\n⚠️ Analysis interrupted by user")
            break
        except Exception as e:
            print(f"\n❌ Analysis failed for {code}: {e}")
            import traceback
            traceback.print_exc()
            all_results.append({"code": code, "error": str(e)})

    # Print summary table for all stocks
    print(f"\n{'='*70}")
    print("  📊 PORTFOLIO SUMMARY")
    print(f"{'='*70}")

    print(f"\n┌─────────────┬──────┬───────┬───────┬────────┬────────┬────────┬────────┬───────┐")
    print(f"│ Stock       │ Rec  │ Conf │ Price │ Today% │ RSI    │ Entry  │ Stop   │ Target│")
    print(f"├─────────────┼──────┼───────┼───────┼────────┼────────┼────────┼────────┼───────┤")

    for result in all_results:
        if "error" in result:
            print(f"│ {result['code']:<11} │ ERR  │   -  │   -   │   -   │   -   │   -   │   -   │   -   │")
            continue

        name = result.get("stock_name", result["code"])[:11]
        change = result.get("analysis", {}).get("change_pct", 0)

        print(f"│ {name:<11} │ {result['recommendation']:<4} │ {result['confidence']}/10 │ {result['entry']:>6.2f} │ {change:>5.1f}% │ {result.get('analysis', {}).get('rsi', 0):>5.1f} │ {result['entry']:>6.2f} │ {result['stop']:>6.2f} │ {result['target']:>6.2f} │")

    print(f"└─────────────┴──────┴───────┴───────┴────────┴────────┴────────┴────────┴───────┘")

    # Save combined results
    output_file = "portfolio_analysis.json"
    with open(output_file, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n✅ Results saved to {output_file}")

    # Print signals summary
    buy_recs = [r for r in all_results if r.get("recommendation") == "BUY"]
    sell_recs = [r for r in all_results if r.get("recommendation") == "SELL"]
    hold_recs = [r for r in all_results if r.get("recommendation") == "HOLD"]

    print(f"\n{'='*50}")
    print("  📊 SIGNALS SUMMARY")
    print(f"{'='*50}")

    if buy_recs:
        print(f"\n  🟢 BUY Signals ({len(buy_recs)}):")
        for r in buy_recs:
            conf = r.get('confidence', 'LOW')
            print(f"     • {r.get('code')}: Entry ${r.get('entry', 0):.2f} → Target ${r.get('target', 0):.2f} (Conf: {conf})")

    if sell_recs:
        print(f"\n  🔴 SELL Signals ({len(sell_recs)}):")
        for r in sell_recs:
            conf = r.get('confidence', 'LOW')
            print(f"     • {r.get('code')}: Entry ${r.get('entry', 0):.2f} → Target ${r.get('target', 0):.2f} (Conf: {conf})")

    if hold_recs:
        print(f"\n  ⚪ HOLD ({len(hold_recs)}): {', '.join([r.get('code') for r in hold_recs])}")

    # Print top pick
    if buy_recs:
        best = max(buy_recs, key=lambda x: x.get("confidence", 0))
        print(f"\n🏆 TOP PICK: {best.get('code')} ({best.get('stock_name', 'N/A')}) - Confidence: {best['confidence']}/10")


if __name__ == "__main__":
    main()
