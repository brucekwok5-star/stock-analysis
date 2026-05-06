# Stock Analysis System Flowchart

## Overall Flow
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         STOCK ANALYSIS SYSTEM                               │
└─────────────────────────────────────────────────────────────────────────────┘

                              ┌──────────────────┐
                              │  Start (Cron/    │
                              │  Manual Trigger) │
                              └────────┬─────────┘
                                       │
                                       ▼
                    ┌────────────────────────────────┐
                    │  1. FETCH ACTIVE STOCKS        │
                    │  - iTick API (HK stocks)       │
                    │  - Top gainers/losers          │
                    │  - High volume stocks          │
                    └───────────────┬────────────────┘
                                    │
                                    ▼
                    ┌────────────────────────────────┐
                    │  2. RATE LIMITING              │
                    │  - 3 second delay between      │
                    │    each stock analysis         │
                    │  - Prevents API rate limits    │
                    └───────────────┬────────────────┘
                                    │
                                    ▼
                    ┌────────────────────────────────┐
                    │  3. ANALYZE EACH STOCK         │
                    │  (See Detailed Flow Below)      │
                    └───────────────┬────────────────┘
                                    │
                                    ▼
                    ┌────────────────────────────────┐
                    │  4. APPLY MARKET FILTERS       │
                    │  - BUY only in BULLISH         │
                    │  - SELL only in BEARISH        │
                    │  - HOLD in NEUTRAL             │
                    └───────────────┬────────────────┘
                                    │
                                    ▼
                    ┌────────────────────────────────┐
                    │  5. SAVE RECOMMENDATIONS      │
                    │  - Portfolio JSON file         │
                    │  - With entry/stop/target      │
                    └────────────────────────────────┘
```

## Data Sources
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATA SOURCES                                   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐     ┌─────────────────┐     ┌─────────────────────────────┐
│   iTick API    │     │  Yahoo Finance  │     │   MiniMax AI (API)         │
│   (itick.io)   │     │   (yfinance)    │     │   (minimax.chat)            │
├─────────────────┤     ├─────────────────┤     ├─────────────────────────────┤
│ HK Stock Data  │     │ Historical     │     │ News Analysis              │
│ - Price        │     │ Price Data      │     │ - Sentiment                │
│ - Volume       │     │ - 1h/5m/15m     │     │ - Catalysts                │
│ - News         │     │ - EMA/RSI/ATR   │     │ - Recommendations           │
│ - iTick tokens │     │ - SPY/2800.HK   │     │ Fallback when rules fail   │
│   required     │     │   (Index)       │     │                             │
└─────────────────┘     └─────────────────┘     └─────────────────────────────┘
```

## Detailed Stock Analysis Flow
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        ANALYZE STOCK DETAILED                               │
└─────────────────────────────────────────────────────────────────────────────┘

                              ┌──────────────────┐
                              │  Receive Stock   │
                              │  Code (e.g.,700) │
                              └────────┬─────────┘
                                       │
                                       ▼
        ┌─────────────────────────────────────────────────────────────┐
        │  FETCH PRICE DATA (yfinance)                               │
        │  - 1h klines: last 20 days                                  │
        │  - 5m klines: last 1 day                                    │
        │  - 15m klines: last 1 day                                   │
        └─────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
        ┌─────────────────────────────────────────────────────────────┐
        │  CALCULATE TECHNICAL INDICATORS                             │
        │  - EMA20 (20-period exponential moving average)            │
        │  - EMA50 (50-period exponential moving average)            │
        │  - RSI(14) (Relative Strength Index)                        │
        │  - ATR(14) (Average True Range)                             │
        │  - VWAP (Volume Weighted Average Price)                    │
        └─────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
        ┌─────────────────────────────────────────────────────────────┐
        │  DETERMINE TREND                                            │
        │                                                             │
        │  IF price > EMA20 > EMA50  → BULLISH                       │
        │  IF price < EMA20 < EMA50  → BEARISH                      │
        │  ELSE → NEUTRAL                                             │
        │                                                             │
        │  RSI > 70 → OVERBOUGHT (strong bullish)                    │
        │  RSI < 30 → OVERSOLD (strong bearish)                      │
        └─────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
        ┌─────────────────────────────────────────────────────────────┐
        │  GET MARKET BIAS (Index Analysis)                           │
        │                                                             │
        │  HK Market: Use 2800.HK (HSI)                               │
        │  US Market: Use SPY (S&P 500)                               │
        │                                                             │
        │  IF index price > EMA50 → BULLISH market                   │
        │  IF index price < EMA50 → BEARISH market                   │
        │  ELSE → NEUTRAL market                                      │
        └─────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
        ┌─────────────────────────────────────────────────────────────┐
        │  FETCH NEWS (iTick API for HK, or skip for US)            │
        │  - Latest 3-5 news items                                   │
        │  - Check for earnings, split, merger                       │
        └─────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
        ┌─────────────────────────────────────────────────────────────┐
        │  AI ANALYSIS (MiniMax API - Optional Fallback)             │
        │                                                             │
        │  IF rules unclear OR conflicting signals:                  │
        │    - Send price + news + indicators to AI                  │
        │    - Get AI recommendation + confidence                    │
        │  ELSE:                                                      │
        │    - Use rule-based decision                                │
        └─────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
        ┌─────────────────────────────────────────────────────────────┐
        │  DETERMINE RECOMMENDATION                                   │
        └─────────────────────────────────────────────────────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    │                                         │
                    ▼                                         ▼
    ┌──────────────────────────┐             ┌──────────────────────────┐
    │      BUY CRITERIA       │             │      SELL CRITERIA       │
    │  (Long - Profit from    │             │  (Short - Profit from    │
    │   price going up)       │             │   price going down)      │
    ├──────────────────────────┤             ├──────────────────────────┤
    │ 1. Trend = BULLISH      │             │ 1. Trend = BEARISH       │
    │ 2. RSI < 70             │             │ 2. RSI > 30              │
    │ 3. Market = BULLISH     │             │ 3. Market = BEARISH       │
    │ 4. Conf = MEDIUM/HIGH   │             │ 4. Conf = MEDIUM/HIGH    │
    │                         │             │                          │
    │ OR (Strong Signal)      │             │ OR (Strong Signal)       │
    │ - RSI > 70 (breakout)   │             │ - RSI < 30 (breakdown)  │
    │ - Price > EMA20 + ATR   │             │ - Price < EMA20 - ATR   │
    └──────────────────────────┘             └──────────────────────────┘
                    │                                         │
                    └──────────────────┬──────────────────────┘
                                         │
                                         ▼
        ┌─────────────────────────────────────────────────────────────┐
        │  CALCULATE ENTRY / STOP / TARGET                           │
        │                                                             │
        │  BUY:                          SELL:                       │
        │  - Entry = Current Price      - Entry = Current Price     │
        │  - Stop = Entry × 0.97         - Stop = Entry × 1.03       │
        │    (3% below)                   (3% above)                │
        │  - Target = Entry × 1.03       - Target = Entry × 0.97     │
        │    (3% above)                   (3% below)                │
        │                                                             │
        │  Risk:Reward = 1:1 (3%:3%)                                 │
        └─────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
        ┌─────────────────────────────────────────────────────────────┐
        │  APPLY MARKET FILTER                                       │
        │                                                             │
        │  IF recommendation = BUY AND market = BEARISH → HOLD       │
        │  IF recommendation = SELL AND market = BULLISH → HOLD      │
        │  IF recommendation in [BUY,SELL] AND confidence = LOW     │
        │     AND market = NEUTRAL → HOLD                            │
        └─────────────────────────────────────────────────────────────┘
                                         │
                                         ▼
                              ┌──────────────────┐
                              │  RETURN          │
                              │  RECOMMENDATION  │
                              │  (BUY/SELL/HOLD) │
                              └──────────────────┘
```

## Rate Limiting Flow
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         RATE LIMITING                                       │
└─────────────────────────────────────────────────────────────────────────────┘

     ┌────────────────────────────────────────────────────────────┐
     │                    BEFORE EACH STOCK                       │
     └────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                          ┌────────────────┐
                          │ Sleep 3 sec    │ ◄── Rate limit delay
                          └───────┬────────┘
                                  │
                                  ▼
                          ┌────────────────┐
                          │ Process Stock  │
                          └───────┬────────┘
                                  │
                                  ▼
                          ┌────────────────┐
                          │ Sleep 3 sec    │ ◄── Between each stock
                          └───────┬────────┘
                                  │
                                  ▼
                          ┌────────────────┐
                          │ Next Stock     │
                          └────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  WHY 3 SECONDS?                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  - iTick API: Varies by plan (free tier ~60 req/min)                       │
│  - Yahoo Finance: Can block if too many requests                          │
│  - MiniMax API: 60 calls/minute for free tier                              │
│  - 3 seconds = 20 stocks/minute = safe margin                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Verify Trades Flow
```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      VERIFY TRADES (Verification)                           │
└─────────────────────────────────────────────────────────────────────────────┘

     ┌────────────────────────────────────────────────────────────┐
     │  Load Portfolio JSON Files                                │
     │  (Contains: code, entry, stop, target, timestamp)         │
     └────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
     ┌────────────────────────────────────────────────────────────┐
     │  For EACH recommendation:                                  │
     │    - Get price data AFTER timestamp                       │
     │    - Check if target OR stop was hit                      │
     │    - Only check current + next trading day                │
     └────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
        ┌──────────────────┐           ┌──────────────────┐
        │  BUY (Long)      │           │  SELL (Short)    │
        │  - GAIN: price   │           │  - GAIN: price   │
        │      >= target   │           │      <= target   │
        │  - LOSS: price   │           │  - LOSS: price   │
        │      <= stop     │           │      >= stop     │
        └──────────────────┘           └──────────────────┘
                    │                               │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
     ┌────────────────────────────────────────────────────────────┐
     │  Calculate Win Rate & P/L                                  │
     │  - Win Rate = Wins / (Wins + Losses)                       │
     │  - P/L = (Wins × 3%) - (Losses × 3%)                       │
     └────────────────────────────────────────────────────────────┘
```

## API Details Summary

| API/Source | Purpose | Rate Limit | Auth |
|------------|---------|------------|------|
| iTick | HK stock data, news | ~60 req/min | Token (config.json) |
| Yahoo Finance (yfinance) | Historical prices, indicators | 2000 req/day | None |
| MiniMax API | AI analysis fallback | 60 req/min | API Key (config.json) |
| 2800.HK | HSI index for market bias | Via yfinance | None |
| SPY | S&P 500 for market bias | Via yfinance | None |

## Configuration Files
```
config.json:
  - itick_tokens: [token1, token2, ...]
  - minimax_api_key: "your-key"
  - us_stocks: ["NVDA", "TSLA", ...]
  - hk_stocks: ["700", "9988", ...]

portfolio_YYYY-MM-DD_HH-MM-SS.json:
  - timestamp: "2026-03-25 10:00:00"
  - results: [{code, recommendation, entry, stop, target, confidence, ...}]
```