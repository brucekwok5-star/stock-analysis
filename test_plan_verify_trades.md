# Test Plan: verify_trades.py

## Overview
This test plan covers all test cases for the trade verification script that analyzes BUY/SELL recommendations from portfolio JSON files and verifies whether target or stop was hit first using minute-by-minute historical data.

---

## Test Categories

### 1. BUY Recommendations - LONG Position

#### Test Case 1.1: BUY-GAIN (Target hit before stop)
| Field | Value |
|-------|-------|
| Description | Stock goes UP, hits target (3%) before stop (2.5%) |
| Recommendation | BUY |
| Entry Price | $100.00 |
| Stop Loss | $97.50 (-2.5%) |
| Target Price | $103.00 (+3.0%) |
| Expected Result | GAIN |
| Expected P&L | +3.0% |

**Setup:** Create portfolio JSON with stock that rises from $100 to $103+ without dropping to $97.50

---

#### Test Case 1.2: BUY-LOSS (Stop hit before target)
| Field | Value |
|-------|-------|
| Description | Stock goes DOWN, hits stop (2.5%) before target (3%) |
| Recommendation | BUY |
| Entry Price | $100.00 |
| Stop Loss | $97.50 (-2.5%) |
| Target Price | $103.00 (+3.0%) |
| Expected Result | LOSS |
| Expected P&L | -2.5% |

**Setup:** Create portfolio JSON with stock that drops from $100 to $97.50 or below without reaching $103

---

#### Test Case 1.3: BUY-PENDING (Neither target nor stop hit)
| Field | Value |
|-------|-------|
| Description | Stock trades in range, neither target nor stop hit |
| Recommendation | BUY |
| Entry Price | $100.00 |
| Stop Loss | $97.50 (-2.5%) |
| Target Price | $103.00 (+3.0%) |
| Expected Result | PENDING |
| Expected P&L | N/A (based on last close) |

**Setup:** Create portfolio JSON with stock that stays between $97.50 and $103

---

### 2. SELL Recommendations - SHORT Position

#### Test Case 2.1: SELL-GAIN (Target hit - price goes DOWN)
| Field | Value |
|-------|-------|
| Description | Stock goes DOWN, hits target (3% gain for short) before stop (2.5% loss) |
| Recommendation | SELL (short) |
| Entry Price | $100.00 |
| Stop Loss | $102.50 (+2.5% - loss for short) |
| Target Price | $97.00 (-3.0% - gain for short) |
| Expected Result | GAIN |
| Expected P&L | +3.0% |

**Setup:** Create portfolio JSON with stock that drops from $100 to $97 or below without rising to $102.50

---

#### Test Case 2.2: SELL-LOSS (Stop hit - price goes UP)
| Field | Value |
|-------|-------|
| Description | Stock goes UP, hits stop (2.5% loss for short) before target (3%) |
| Recommendation | SELL (short) |
| Entry Price | $100.00 |
| Stop Loss | $102.50 (+2.5% - loss for short) |
| Target Price | $97.00 (-3.0% - gain for short) |
| Expected Result | LOSS |
| Expected P&L | -2.5% |

**Setup:** Create portfolio JSON with stock that rises from $100 to $102.50 or above without dropping to $97

---

#### Test Case 2.3: SELL-PENDING (Neither target nor stop hit)
| Field | Value |
|-------|-------|
| Description | Shorted stock trades in range, neither target nor stop hit |
| Recommendation | SELL (short) |
| Entry Price | $100.00 |
| Stop Loss | $102.50 (+2.5%) |
| Target Price | $97.00 (-3.0%) |
| Expected Result | PENDING |
| Expected P&L | N/A |

**Setup:** Create portfolio JSON with stock that stays between $97 and $102.50

---

### 3. Market Type Tests

#### Test Case 3.1: HK Stock - BUY
| Field | Value |
|-------|-------|
| Description | HK stock with .HK suffix |
| Stock Code | 3690.HK (example: Meituan) |
| Recommendation | BUY |
| Expected | Uses check_hk_trade() |

---

#### Test Case 3.2: HK Stock - SELL (Short)
| Field | Value |
|-------|-------|
| Description | HK stock short position |
| Stock Code | 3690.HK |
| Recommendation | SELL |
| Expected | Uses check_hk_trade() with is_short=True |

---

#### Test Case 3.3: US Stock - BUY
| Field | Value |
|-------|-------|
| Description | US stock without .HK suffix |
| Stock Code | AAPL, TSLA |
| Recommendation | BUY |
| Expected | Uses check_us_trade() |

---

#### Test Case 3.4: US Stock - SELL (Short)
| Field | Value |
|-------|-------|
| Description | US stock short position |
| Stock Code | AAPL |
| Recommendation | SELL |
| Expected | Uses check_us_trade() with is_short=True |

---

### 4. Error Handling Tests

#### Test Case 4.1: NO DATA
| Field | Value |
|-------|-------|
| Description | No historical data available from Yahoo |
| Expected Result | ERROR / NO DATA |
| Expected Reason | "No data returned" |

---

#### Test Case 4.2: NO DATA AFTER Entry
| Field | Value |
|-------|-------|
| Description | Data exists but no data after entry timestamp |
| Expected Result | NO DATA AFTER |
| Expected Reason | "No data after entry time" |

---

#### Test Case 4.3: NO TRADING HOURS (US only)
| Field | Value |
|-------|-------|
| Description | US stock data exists but outside trading hours (09:30-16:00) |
| Expected Result | NO TRADING HOURS |
| Expected Reason | "No data in trading hours" |

---

#### Test Case 4.4: API/Rate Limit Error
| Field | Value |
|-------|-------|
| Description | Yahoo API returns error or rate limit |
| Expected Result | ERROR |
| Expected Reason | Contains error message |

---

### 5. Edge Cases

#### Test Case 5.1: Entry at Market Open
| Field | Value |
|-------|-------|
| Description | Entry timestamp at market open (09:30 US ET / 09:30 HK) |
| Expected | Correctly handles first minute of trading |

---

#### Test Case 5.2: Entry at Market Close
| Field | Value |
|-------|-------|
| Description | Entry timestamp at market close |
| Expected | Uses next trading day data appropriately |

---

#### Test Case 5.3: Weekend Entry
| Field | Value |
|-------|-------|
| Description | Entry timestamp falls on weekend |
| Expected | Handles appropriately (uses Monday data) |

---

#### Test Case 5.4: Very Small Position
| Field | Value |
|-------|-------|
| Description | Very small stop/target percentages |
| Expected | Correctly identifies which level was hit |

---

#### Test Case 5.5: Gap Up/Down
| Field | Value |
|-------|-------|
| Description | Stock gaps up/down past both stop and target in first candle |
| Expected | Correctly identifies which level hit first (check order matters) |

---

#### Test Case 5.6: Exact Stop/Target Touch
| Field | Value |
|-------|-------|
| Description | Price exactly touches stop or target |
| Expected | Consistent behavior (should trigger) |

---

### 6. Data Source Tests

#### Test Case 6.1: Yahoo Finance Data (Default)
| Field | Value |
|-------|-------|
| Description | Uses yfinance for both HK and US stocks |
| Expected | check_trade_result() uses yfinance by default |

---

#### Test Case 6.2: iTick Data (HK)
| Field | Value |
|-------|-------|
| Description | Uses iTick API for HK stocks |
| Function | check_hk_trade_itick() |

---

#### Test Case 6.3: iTick Data (US)
| Field | Value |
|-------|-------|
| Description | Uses iTick API for US stocks |
| Function | check_us_trade_itick() |

---

### 7. Timezone Handling Tests

#### Test Case 7.1: HK Timezone
| Field | Value |
|-------|-------|
| Description | Timestamp in HK timezone, data in HK timezone |
| Expected | Correct conversion and filtering |

---

#### Test Case 7.2: US Timezone
| Field | Value |
|-------|-------|
| Description | HK timestamp converted to US Eastern |
| Expected | Correct timezone conversion |

---

#### Test Case 7.3: Timezone Edge Case (Weekend)
| Field | Value |
|-------|-------|
| Description | HK time maps to weekend in US timezone |
| Expected | Uses fallback to last trading day |

---

### 8. Output Verification Tests

#### Test Case 8.1: Summary Statistics
| Field | Value |
|-------|-------|
| Description | Verifies win rate, average gain/loss calculation |
| Expected | Correct percentages |

---

#### Test Case 8.2: CSV Output
| Field | Value |
|-------|-------|
| Description | -o flag saves results to CSV |
| Expected | CSV contains all required columns |

---

#### Test Case 8.3: Detailed Table Output
| Field | Value |
|-------|-------|
| Description | -d flag shows detailed table |
| Expected | All columns displayed correctly |

---

## Test Data Requirements

### Sample Portfolio JSON Structure
```json
{
  "results": [
    {
      "code": "3690",
      "stock_name": "Meituan",
      "recommendation": "BUY",
      "entry": 180.00,
      "stop": 175.50,
      "target": 185.40,
      "timestamp": "2026-04-30 10:00:00",
      "confidence": "HIGH",
      "analysis": {
        "price": 180.00
      }
    }
  ]
}
```

### Test Files to Create
1. `test_buy_gain.json` - BUY recommendation that hits target
2. `test_buy_loss.json` - BUY recommendation that hits stop
3. `test_buy_pending.json` - BUY with no outcome yet
4. `test_sell_gain.json` - SELL (short) that hits target (price down)
5. `test_sell_loss.json` - SELL (short) that hits stop (price up)
6. `test_sell_pending.json` - SELL with no outcome yet
7. `test_hk_stock.json` - HK market stock
8. `test_us_stock.json` - US market stock
9. `test_error_no_data.json` - Stock with no data

---

## Execution Commands

```bash
# Run all tests
python verify_trades.py test_buy_gain.json test_buy_loss.json test_buy_pending.json test_sell_gain.json test_sell_loss.json test_sell_pending.json -v -d

# Run with specific test file
python verify_trades.py test_buy_gain.json -v -d

# Save to CSV
python verify_trades.py *.json -o test_results.csv
```

---

## Acceptance Criteria

| # | Criteria | Test Cases |
|---|----------|------------|
| 1 | BUY-GAIN returns status=GAIN, correct P&L% | 1.1 |
| 2 | BUY-LOSS returns status=LOSS, correct P&L% | 1.2 |
| 3 | BUY-PENDING returns status=PENDING | 1.3 |
| 4 | SELL-GAIN returns status=GAIN, correct P&L% (positive) | 2.1 |
| 5 | SELL-LOSS returns status=LOSS, correct P&L% (negative) | 2.2 |
| 6 | SELL-PENDING returns status=PENDING | 2.3 |
| 7 | HK stocks processed correctly | 3.1, 3.2 |
| 8 | US stocks processed correctly | 3.3, 3.4 |
| 9 | Error cases handled gracefully | 4.1 - 4.4 |
| 10 | Timezone conversions correct | 7.1 - 7.3 |
| 11 | Summary statistics accurate | 8.1 |
| 12 | CSV output complete | 8.2 |
