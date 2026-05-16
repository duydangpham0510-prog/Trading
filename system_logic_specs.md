# SYSTEM LOGIC SPECIFICATIONS
## VN30 Alpha Scanner v10.1 - UNIFIED LOGIC (Database-First Architecture)

**Document Version:** 3.1  
**Last Updated:** 2026-05-16  
**Status:** Unified - Backend is Single Source of Truth  

---

## CHANGES IN v10.1 (2026-05-16)

### Core Logic Engine - `compute_core_logic()`
- **Function Location:** `dashboard/sync_service.py`
- **Pure Function:** Nhận dữ liệu thô, trả về kết quả phân tích đầy đủ
- **Shared:** Dùng chung cho cả Live scan và Backtest

### Fair Value Calculation (UPDATED)
- **FV_Daily:** `(VWAP × 0.4) + (SMA20 × 0.6)` (updated from VWAP×0.6 + SMA10×0.4)
- **FV_Weekly:** Weighted average of Intrinsic Value (fund_score) và Take Profit (tech_score)
- **Intrinsic Value:** `Price × (Industry_PE_Avg / Actual_PE)` hoặc fallback sang `Price × (Industry_Target_PE / Actual_PE)`

### Unified Scoring System
- **Master Score = 70% Technical + 30% Fundamental** (Backend)
- **Market Weight: x1.2** when Market RSI < 25
- **VETO Score Cap: 10** (strict - matches Frontend)

### VETO Rules (10 conditions)
1. CMF < 0
2. ROE < 15%
3. F-Score < 5
4. Market RSI > 80
5. Ichimoku Bearish
6. TK-KJ Bearish (Tenkan < Kijun)
7. R:R < 1.0
8. Inverted SL (Entry <= Stop Loss)
9. ATR = 0
10. Missing Financial Data

### 12-Point Evaluation Criteria
1. RSI Sweet Spot (50-65)
2. ADX Strong (>20)
3. DI Bullish (+DI > -DI)
4. CMF Positive (>0)
5. Volume Active (>1.0x)
6. Above SMA20
7. MACD Bullish
8. R:R >= 2.0
9. F-Score OK (>=2)
10. Fast Holding (<=10 days)
11. **SMA Perfect** (Price > SMA10 > SMA20 > SMA50)
12. **Ichimoku Bullish**

---

## TABLE OF CONTENTS

1. [System Overview](#1-system-overview)
2. [Technical Indicators Group](#2-technical-indicators-group)
3. [Fundamental Indicators Group](#3-fundamental-indicators-group)
4. [Smart Money & Industry Group](#4-smart-money--industry-group)
5. [Fair Value Calculation](#5-fair-value-calculation)
6. [Backend Scoring System (Python)](#6-backend-scoring-system-python)
7. [Frontend Display Only (JavaScript)](#7-frontend-display-only-javascript)
8. [Score Weight Comparison](#8-score-weight-comparison)
9. [VETO Rules](#9-veto-rules)
10. [Stock Classification](#10-stock-classification)
11. [12-Point Evaluation Criteria](#11-12-point-evaluation-criteria)
12. [Market Risk Assessment](#12-market-risk-assessment)
13. [Investment Horizon](#13-investment-horizon)
14. [Trading Levels Calculation](#14-trading-levels-calculation)
15. [Data Flow Architecture](#15-data-flow-architecture)

---

## 1. System Overview

### 1.1 Purpose
The VN30 Alpha Scanner v2 system provides automated stock analysis and recommendation for Vietnamese stock market (HOSE). It combines technical analysis, fundamental analysis, and smart money indicators to generate trading signals.

### 1.2 Components
```
┌─────────────────────────────────────────────────────────────┐
│                    SYSTEM ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌────────────┐│
│  │  vnstock_data │    │   vnstock_ta │    │ vnstock_news││
│  │  (OHLCV)     │    │  (Indicators)│    │  (Sentiment) ││
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘│
│         │                    │                     │        │
│         └────────────────────┴─────────────────────┘        │
│                              │                              │
│                              ▼                              │
│              ┌───────────────────────────────┐              │
│              │    vn30_scanner.py (Backend)  │              │
│              │    - Technical Scoring        │              │
│              │    - Fundamental Scoring      │              │
│              │    - VETO Logic              │              │
│              │    - Classification          │              │
│              └───────────────┬───────────────┘              │
│                              │                              │
│         ┌────────────────────┼────────────────────┐        │
│         │                    │                    │        │
│         ▼                    ▼                    ▼        │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │  SQLite DB  │    │  Django API │    │  Frontend   │  │
│  │  (Storage)  │    │  (Export)   │    │   (JavaScript)│  │
│  └─────────────┘    └─────────────┘    └─────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 1.3 Data Sources
| Source | Library | Data Type | Priority |
|--------|---------|-----------|----------|
| OHLCV | vnstock_data | Price, Volume | Primary |
| OHLCV | vnstock (VCI/KBS) | Price, Volume | Fallback |
| Technical | vnstock_ta | Indicators | Primary |
| Technical | Manual Calculation | Indicators | Fallback |
| Fundamental | vnstock_data | F-Score, ROE, P/E, P/B | Primary |

---

## 2. Technical Indicators Group

### 2.1 RSI (Relative Strength Index)

**Definition:** Momentum oscillator measuring speed and change of price movements.

**Source:** `stock.rsi`  
**Period:** 14  
**Range:** 0-100  

**Thresholds:**
| Value | Status | Signal |
|-------|--------|--------|
| RSI > 80 | Very Overbought | Strong Bearish |
| RSI > 70 | Overbought | Bearish |
| RSI 65-70 | Light Overbought | Light Bearish |
| RSI 35-50 | Neutral | Neutral |
| RSI 30-35 | Light Oversold | Light Bullish |
| RSI < 30 | Oversold | Bullish |
| RSI < 20 | Very Oversold | Strong Bullish |

**Backend Impact (Python):**
```python
# vn30_scanner.py - Technical Scoring
if 50 <= rsi <= 65:
    tech_score += 12 if 55 <= rsi <= 62 else 8
elif rsi > 70:
    tech_score -= 15
elif rsi > 65:
    tech_score -= 8
elif rsi < 50:
    tech_score += 4
```

**Frontend Impact (JavaScript):**
```javascript
// stock_list.html - tScore
if (rsi >= 45 && rsi <= 65) tScore += 10;
else if (rsi >= 40 && rsi <= 75) tScore += 5;
```

---

### 2.2 ADX (Average Directional Index)

**Definition:** Measures trend strength without regard to direction.

**Source:** `stock.adx`  
**Period:** 14  
**Range:** 0-100  

**Thresholds:**
| Value | Status | Signal |
|-------|--------|--------|
| ADX > 40 | Very Strong | Strong Trend |
| ADX 25-40 | Strong | Strong Trend |
| ADX 20-25 | Moderate | Weak Trend |
| ADX < 20 | Weak/None | SIDEWAY (No Trend) |

**CRITICAL RULE:** `ADX < 20 = SIDEWAY regardless of price position`

**Backend Impact (Python):**
```python
if adx > 25:
    tech_score += 12
elif adx > 20:
    tech_score += 8
elif adx > 15:
    tech_score += 4
# Note: ADX < 20 = 0 points (no trend contribution)
```

**Trend Determination:**
```python
# From price vs SMAs
if price > sma_20 > sma_50:
    trend = "strong_uptrend"
elif price > sma_20:
    trend = "uptrend"
elif price < sma_20 < sma_50:
    trend = "strong_downtrend"
elif price < sma_20:
    trend = "downtrend"
else:
    trend = "sideways"

# But if ADX < 20: trend = "sideways"
if adx < 20:
    trend = "sideways"
```

---

### 2.3 CMF (Chaikin Money Flow)

**Definition:** Measures money flow volume over a period. Positive = money flowing in, Negative = money flowing out.

**Source:** `stock.cmf`  
**Period:** 20  
**Range:** -1 to +1  

**Calculation:**
```
Money Flow Multiplier = ((Close - Low) - (High - Close)) / (High - Low)
Money Flow Volume = Money Flow Multiplier × Volume
CMF = Sum(MFV, 20 periods) / Sum(Volume, 20 periods)
```

**Thresholds:**
| Value | Status | Signal |
|-------|--------|--------|
| CMF > 0.2 | Strong Inflow | Strong Bullish |
| CMF > 0.1 | Inflow | Bullish |
| CMF 0 to 0.1 | Slight Inflow | Neutral/Bullish |
| CMF -0.1 to 0 | Slight Outflow | Neutral/Bearish |
| CMF < -0.1 | Outflow | Bearish |
| CMF < -0.2 | Strong Outflow | Strong Bearish |

**Backend Impact (Python):**
```python
if cmf > 0.1:
    tech_score += 12
elif cmf > 0:
    tech_score += 8
else:
    tech_score -= 15  # CRITICAL: CMF negative is bad
```

**Frontend Impact (JavaScript):**
```javascript
if (cmf > 0.1) tScore += 15;
```

**VETO Implication:** `CMF < 0` triggers VETO in Backend

---

### 2.4 MFI (Money Flow Index)

**Definition:** Volume-weighted RSI. Combines price and volume.

**Source:** `stock.mfi`  
**Period:** 14  
**Range:** 0-100  

**Thresholds:**
| Value | Status | Signal |
|-------|--------|--------|
| MFI > 80 | Overbought | Bearish |
| MFI 60-80 | Neutral High | Neutral |
| MFI 40-60 | Neutral | Neutral |
| MFI 20-40 | Neutral Low | Neutral |
| MFI < 20 | Oversold | Bullish |

**Backend Impact (Python):**
```python
# Used in signal calculation, not directly in score
```

**Frontend Impact (JavaScript):**
```javascript
if (mfi > 50) tScore += 10;
else if (mfi > 30) tScore += 5;
```

---

### 2.5 MACD (Moving Average Convergence Divergence)

**Definition:** Trend-following momentum indicator showing relationship between two EMAs.

**Source:** `stock.macd`, `stock.macd_signal`  
**Default Parameters:** Fast=12, Slow=26, Signal=9  
**Output:** MACD Line, Signal Line, Histogram

**Thresholds:**
| MACD | Signal | Status |
|------|--------|--------|
| MACD > 100 | > Signal | Strong Bullish |
| MACD > 0 | > Signal | Bullish |
| MACD < 0 | < Signal | Bearish |
| MACD < -100 | < Signal | Strong Bearish |

**Backend Impact (Python):**
```python
if macd > macd_signal:
    tech_score += 8
elif macd > 0:
    tech_score += 4
```

---

### 2.6 VWAP (Volume Weighted Average Price)

**Definition:** Average price weighted by volume. Shows the "fair" price for the day.

**Source:** `stock.vwap`  
**Calculation:**
```
Typical Price = (High + Low + Close) / 3
VWAP = Sum(Typical × Volume) / Sum(Volume)
```

**Usage:**
| Price vs VWAP | Signal |
|---------------|--------|
| Price > VWAP | Above average (Bullish) |
| Price < VWAP | Below average (Bearish) |
| Price = VWAP | Fair value |

**Frontend Impact (JavaScript):**
```javascript
if (vwapStatus === 'above') tScore += 10;
```

---

### 2.7 SuperTrend

**Definition:** Trend indicator with built-in stop loss based on ATR.

**Source:** `stock.supertrend_signal`, `stock.supertrend_stop`  
**Parameters:** Period=10, Multiplier=3  

**Signals:**
| Signal | Meaning |
|--------|---------|
| `buy` | Price above SuperTrend - Uptrend |
| `sell` | Price below SuperTrend - Downtrend |
| `neutral` | No clear trend |

**Frontend Impact (JavaScript):**
```javascript
if (supertrendSignal === 'buy') tScore += 10;
```

---

### 2.8 SMA (Simple Moving Average)

**Definition:** Average price over a period of time.

**Sources:** `stock.sma_10`, `stock.sma_20`, `stock.sma_50`, `stock.sma_200`  

**Trend Patterns:**
| Pattern | Condition | Signal |
|---------|-----------|--------|
| Perfect Uptrend | Price > SMA10 > SMA20 > SMA50 | Strong Bullish |
| Uptrend | Price > SMA20 > SMA50 | Bullish |
| Perfect Downtrend | Price < SMA10 < SMA20 < SMA50 | Strong Bearish |
| Downtrend | Price < SMA20 < SMA50 | Bearish |
| Sideways | Mixed | Neutral |

**Frontend Impact (JavaScript):**
```javascript
if (smaTrend === 'perfect') tScore += 20;
```

**Backend Impact (Python):**
```python
if price > sma_20 > sma_50:
    tech_score += 10
elif price > sma_20:
    tech_score += 6
else:
    tech_score -= 8
```

---

### 2.9 Bollinger Bands

**Definition:** Price envelope showing volatility. Bands widen when volatile, narrow when calm.

**Sources:** `stock.bb_upper`, `stock.bb_middle`, `stock.bb_lower`, `stock.bb_percent`  
**Parameters:** Period=20, Std=2  

**Position Zones:**
| BB_Position | Zone | Signal |
|-------------|------|--------|
| > 80% | Upper Zone | Overbought |
| 30-70% | Middle Zone | Neutral |
| < 20% | Lower Zone | Oversold |

**Calculation:**
```
BB_Middle = SMA(Close, 20)
BB_Std = StdDev(Close, 20)
BB_Upper = BB_Middle + (2 × BB_Std)
BB_Lower = BB_Middle - (2 × BB_Std)
BB_Position = (Price - BB_Lower) / (BB_Upper - BB_Lower) × 100
```

**Frontend Impact (JavaScript):**
```javascript
if (bbPos >= 30 && bbPos <= 70) tScore += 15;
```

---

### 2.10 Ichimoku Cloud

**Definition:** Multi-component trend system using multiple averages and "cloud" support/resistance.

**Sources:** `ichimoku_tenkan`, `ichimoku_kijun`, `ichimoku_span_a`, `ichimoku_span_b`, `ichimoku_status`  

**Components:**
| Component | Period | Name | Purpose |
|-----------|--------|------|---------|
| Tenkan-sen | 9 | Conversion Line | Short-term trend |
| Kijun-sen | 26 | Base Line | Medium-term trend |
| Senkou Span A | (Tenkan+Kijun)/2 | Leading Span A | Cloud boundary |
| Senkou Span B | 52 | Leading Span B | Cloud boundary |

**Status Determination:**
| Condition | Status |
|-----------|--------|
| Price > Cloud Top | Bullish |
| Price < Cloud Bottom | Bearish |
| Price In Cloud | Mixed |
| Tenkan > Kijun | TK Cross Bullish |
| Tenkan < Kijun | TK Cross Bearish |

**Frontend Impact (JavaScript):**
```javascript
if (ichimoku === 'bullish' || ichimokuTk === 'bullish') tScore += 15;
if (ichimokuTk === 'bullish') tScore += 10;  // tkCross bullish
```

**VETO Implication:** `ichimoku === 'bearish'` triggers VETO in Frontend

---

### 2.11 Volume Ratio

**Definition:** Current volume compared to 20-day average volume.

**Source:** `stock.volume_ratio`  
**Calculation:**
```
Volume Ratio = Current Volume / Average Volume (20 days)
```

**Thresholds:**
| Ratio | Interpretation |
|-------|----------------|
| > 2.0 | Extremely High Volume |
| > 1.5 | High Volume |
| > 1.3 | Above Average |
| 1.0 | Average |
| < 1.0 | Low Volume |

**Backend Impact (Python):**
```python
if volume_ratio > 2:
    tech_score += 8
elif volume_ratio > 1.5:
    tech_score += 5
elif volume_ratio > 1.3:
    tech_score += 3
```

**Frontend Impact (JavaScript):**
```javascript
if (volRatio >= 1.5) tScore += 20;
```

---

### 2.12 ATR (Average True Range)

**Definition:** Measures market volatility. Not directional.

**Source:** `stock.atr`  
**Period:** 14  
**Calculation:**
```
TR = Max(High - Low, |High - Previous Close|, |Low - Previous Close|)
ATR = SMA(TR, 14)
```

**Usage in System:**
- Stop Loss calculation: `SL = Entry - (ATR × 1.5)`
- Take Profit calculation: `TP = Entry + (ATR × 3)`
- Volatility classification

**ATR Status:**
| % of Price | Status |
|------------|--------|
| > 5% | High Volatility |
| 2-5% | Medium Volatility |
| < 2% | Low Volatility |

---

## 3. Fundamental Indicators Group

### 3.1 F-Score (Piotroski Score)

**Definition:** 9-point scoring system measuring profitability, leverage, and operating efficiency.

**Source:** `stock.f_score`  
**Range:** 0-9  

**9 Criteria:**
| # | Criteria | Condition | Points |
|---|----------|-----------|--------|
| 1 | ROA > 0 | Net Income / Total Assets > 0 | 1 |
| 2 | Operating Cash Flow > 0 | CFO > 0 | 1 |
| 3 | ROA Increase YoY | Current ROA > Previous ROA | 1 |
| 4 | CFO > Net Income | Accruals quality | 1 |
| 5 | D/E Ratio < 1.5 | Leverage acceptable | 1 |
| 6 | Current Ratio > 1 | Liquidity | 1 |
| 7 | Gross Margin Stable | Not declining | 1 |
| 8 | Asset Turnover > 0.05 | Efficiency | 1 |
| 9 | Revenue Growth | YoY increase | 1 |

**Grade System:**
| F-Score | Grade |
|---------|-------|
| 8-9 | A+ |
| 7 | A |
| 5-6 | B |
| 3-4 | C |
| 0-2 | D |

**Frontend Impact (JavaScript):**
```javascript
if (fScore >= 7) fundScore += 25;
else if (fScore >= 5) fundScore += 15;
else if (fScore >= 3) fundScore += 10;
```

---

### 3.2 ROE (Return on Equity)

**Definition:** Net profit as percentage of shareholder equity.

**Source:** `stock.roe`  
**Calculation:**
```
ROE = Net Income / Shareholder Equity × 100
```

**Thresholds:**
| ROE | Interpretation |
|-----|----------------|
| > 20% | Excellent |
| 15-20% | Good |
| 10-15% | Acceptable |
| 5-10% | Weak |
| < 5% | Poor |

**Backend Impact (Python):**
```python
if roe > 20:
    fund_score += 10
elif roe > 15:
    fund_score += 7
elif roe > 10:
    fund_score += 4
elif roe > 0:
    fund_score += 1
```

**Frontend Impact (JavaScript):**
```javascript
if (roe >= 20) fundScore += 25;
else if (roe >= 15) fundScore += 20;
else if (roe >= 10) fundScore += 10;
else if (roe >= 5) fundScore += 5;
```

**VETO Implication:** `ROE < 15` triggers VETO

---

### 3.3 P/E (Price to Earnings Ratio)

**Definition:** Price relative to earnings per share.

**Source:** `stock.pe`  
**Calculation:**
```
P/E = Current Price / Earnings Per Share
```

**Thresholds:**
| P/E | Interpretation |
|-----|----------------|
| < 10 | Very Cheap |
| 10-15 | Cheap/Value |
| 15-20 | Fair |
| 20-25 | Expensive |
| > 25 | Very Expensive |
| < 0 | Loss (N/A) |

**Backend Impact (Python):**
```python
if 0 < pe <= 10:
    fund_score += 10
elif 10 < pe <= 15:
    fund_score += 7
elif 15 < pe <= 20:
    fund_score += 3
elif pe > 25:
    fund_score -= 5
```

**Frontend Impact (JavaScript):**
```javascript
if (pe > 0 && pe <= 10) fundScore += 25;
else if (pe <= 15) fundScore += 20;
else if (pe <= 20) fundScore += 10;
else if (pe <= 30) fundScore += 5;
else fundScore -= 10;  // P/E > 30
```

---

### 3.4 P/B (Price to Book Ratio)

**Definition:** Price relative to book value per share.

**Source:** `stock.pb`  
**Calculation:**
```
P/B = Current Price / Book Value Per Share
```

**Thresholds:**
| P/B | Interpretation |
|-----|----------------|
| < 1 | Below Book Value |
| 1-1.5 | Reasonable |
| 1.5-2 | Fair |
| 2-3 | Expensive |
| > 3 | Very Expensive |

**Backend Impact (Python):**
```python
if 0 < pb <= 1:
    fund_score += 5
elif 1 < pb <= 2:
    fund_score += 3
elif pb > 3:
    fund_score -= 3
```

**Frontend Impact (JavaScript):**
```javascript
if (pb > 0 && pb <= 1) fundScore += 25;
else if (pb <= 1.5) fundScore += 20;
else if (pb <= 2) fundScore += 15;
else if (pb <= 3) fundScore += 5;
else fundScore -= 5;  // P/B > 3
```

---

## 4. Smart Money & Industry Group

### 4.1 Market RSI

**Definition:** RSI of VNIndex (market benchmark).

**Source:** `analysis.market_rsi`  
**Calculation:** Same as RSI but for market index  

**Usage:**
| Market RSI | Zone | Action |
|-----------|------|--------|
| > 80 | Extreme Danger | SELL ZONE - Only take profits |
| 75-80 | Overbought | Reduce position, be cautious |
| 70-75 | Warning | Deploy 20-30% cash only |
| 50-70 | Neutral | Normal deployment |
| 40-50 | Neutral Low | Normal deployment |
| < 40 | Oversold | Increase weight (+10) |
| < 25 | Extreme Oversold | Strong boost (+20) |

**Backend Impact (sync_service.py):**
```python
# Market Weight Adjustment
if market_rsi > 85:
    market_weight = -25
elif market_rsi > 80:
    market_weight = -20
elif market_rsi > 70:
    market_weight = -10
elif market_rsi < 25:
    market_weight = 20  # x1.2 boost when Market RSI < 25
elif market_rsi < 40:
    market_weight = +10

# Master Score = 70% Technical + 30% Fundamental
base_master_score = int(tech_score * 0.7 + fund_score * 0.3)
master_score = max(0, min(100, base_master_score + market_weight))
```

---

### 4.2 Industry Configuration

**Definition:** Sector-specific valuation targets for Fair Value calculation.

**Source:** `INDUSTRY_CONFIG` in `views.py`

```python
INDUSTRY_CONFIG = {
    'Banking': {
        'type': 'PB',
        'target': 1.65
    },
    'Real Estate': {
        'type': 'PB',
        'target': 1.8
    },
    'Securities': {
        'type': 'PB',
        'target': 2.0
    },
    'Technology': {
        'type': 'PE',
        'target': 18.0
    },
    'Retail': {
        'type': 'PE',
        'target': 15.0
    },
    'FMCG': {
        'type': 'PE',
        'target': 14.0
    },
    'Oil & Gas': {
        'type': 'PE',
        'target': 9.0
    },
    'Steel': {
        'type': 'PE',
        'target': 8.5
    },
    'Default': {
        'type': 'PE',
        'target': 11.0
    }
}
```

---

### 4.3 Foreign Buy Indicator

**Definition:** Simulated indicator for foreign institutional buying.

**Source:** `row['foreign_buy']`  
**Calculation:**
```python
price_change = df['close'].pct_change(5)
df['foreign_buy'] = (price_change > 0).rolling(3).sum()
```

**Thresholds:**
| Value | Interpretation |
|-------|----------------|
| >= 3 | Strong buying streak |
| 2 | Moderate buying |
| 1 | Slight buying |
| 0 | Neutral |
| < 0 | Selling |

---

## 5. Fair Value Calculation

### 5.1 FV_Daily (Fair Value Daily)

**Purpose:** Short-term fair value based on VWAP and SMA20.

**Formula:**
```python
# Source: sync_service.py - compute_core_logic()
fv_daily = (vwap_val * 0.4) + (sma20_val * 0.6)
```

**Components:**
- 40% VWAP: Reflects intraday sentiment and volume-weighted average
- 60% SMA20: Reflects short-term trend stability

**Example:**
```
If VWAP = 95,000 and SMA20 = 94,500:
FV_Daily = (95000 × 0.4) + (94500 × 0.6)
         = 38000 + 56700
         = 94,700
```

---

### 5.2 FV_Weekly (Fair Value Weekly)

**Purpose:** Medium-term fair value based on intrinsic value and technical targets.

**Formula (from `sync_service.py`):**
```python
# Step 1: Get Industry PE (Priority: API > Config)
pe_industry_avg = fund_data.get('pe_industry_avg', 0) or 0
industry_target_pe = config.get('target', 11.0)

# Use API value if available, else fallback to config
actual_pe = fund_data.get('pe') or 0

# Step 2: Calculate Intrinsic Value
if pe_industry_avg > 0:
    # Use API-provided industry average
    intrinsic = price_val * (pe_industry_avg / actual_pe) if actual_pe > 0 else price_val
elif industry_target_pe > 0:
    # Fallback to INDUSTRY_CONFIG
    intrinsic = price_val * (industry_target_pe / actual_pe) if actual_pe > 0 else price_val
else:
    intrinsic = price_val

# Step 3: Calculate FV_Weekly
fv_weekly = (intrinsic * fund_score + take_profit * tech_score) / (fund_score + tech_score)

# Step 4: Market Risk Adjustment
if market_rsi > 75:
    fv_weekly = fv_weekly * 0.9  # Reduce 10% in overbought market
```

**Example:**
```
If:
- price = 95,000
- actual_PE = 12
- pe_industry_avg = 14 (from API)
- fund_score = 70
- take_profit = 100,000
- tech_score = 75
- market_rsi = 65

intrinsic = 95000 × (14 / 12) = 110,833
fv_weekly = (110833 × 70 + 100000 × 75) / (70 + 75) = 105,217
# No adjustment since market_rsi = 65 < 75
```

**Industry Config (for fallback):**
```python
INDUSTRY_CONFIG = {
    'Banking': {'type': 'PB', 'target': 1.65},
    'Real Estate': {'type': 'PB', 'target': 1.8},
    'Securities': {'type': 'PB', 'target': 2.0},
    'Technology': {'type': 'PE', 'target': 18.0},
    'Retail': {'type': 'PE', 'target': 15.0},
    'FMCG': {'type': 'PE', 'target': 14.0},
    'Oil & Gas': {'type': 'PE', 'target': 9.0},
    'Steel': {'type': 'PE', 'target': 8.5},
    'Default': {'type': 'PE', 'target': 11.0}
}
```

---

### 5.3 Valuation Status

**Definition:** Whether current price is above or below fair value.

```python
valuation_status = "Rẻ" if price_val < fv_weekly else "Đắt"
```

---

## 6. Backend Scoring System (Python)

### 6.1 Technical Score Calculation

**Location:** `dashboard/sync_service.py` - `compute_core_logic()`  
**Base Score:** 50  
**Max Score:** 100  

```python
def compute_core_logic(symbol, tech, fund_data, market_rsi=50.0, ...):
    tech_score = 50
    fund_score = 50
    
    if not is_vetoed:
        # ===== RSI (max +12/-15) =====
        if 50 <= rsi_val <= 65:
            tech_score += 12 if 55 <= rsi_val <= 62 else 8
        elif rsi_val > 70:
            tech_score -= 15
        elif rsi_val > 65:
            tech_score -= 8
        elif rsi_val < 40:
            tech_score += 5
        
        # ===== ADX (max +12) =====
        if adx_val > 25:
            tech_score += 12
        elif adx_val > 20:
            tech_score += 8
        
        # ===== CMF (max +12/-15) =====
        if cmf_val > 0.1:
            tech_score += 12
        elif cmf_val > 0:
            tech_score += 8
        else:
            tech_score -= 15  # CRITICAL: CMF negative
        
        # ===== Volume (max +8) =====
        if volume_ratio_val > 1.5:
            tech_score += 8
        elif volume_ratio_val > 1.0:
            tech_score += 5
        
        # ===== R:R (max +10/-10) =====
        if rr_ratio >= 2.0:
            tech_score += 10
        elif rr_ratio >= 1.5:
            tech_score += 6
        elif rr_ratio < 1.0:
            tech_score -= 10
        
        # ===== Safe Entry (+10) =====
        if is_safe_entry:
            tech_score += 10
        
        # ===== High Resistance Penalty (-15) =====
        if bb_upper_val > 0 and take_profit > bb_upper_val:
            tech_score -= 15
            has_high_resistance = True
        
        # ===== VWAP Below (-8) =====
        if vwap_status_val == "below":
            tech_score -= 8
        
        # ===== Inverted SL (-10) =====
        if has_inverted_sl:
            tech_score -= 10
        
        # ===== FAST PICK =====
        is_fast_pick = adx_val > 18 and volume_ratio_val > 0.8
    else:
        tech_score = max(25, tech_score - 30)
        is_fast_pick = False
    
    tech_score = max(0, min(100, tech_score))
```

---

### 6.2 Fundamental Score Calculation

**Location:** `dashboard/sync_service.py` - `compute_core_logic()`  
**Base Score:** 50  
**Max Score:** 100  

```python
# ===== F-Score (0-9) =====
if f_score_val >= 8:
    fund_score = 85
elif f_score_val >= 7:
    fund_score = 78
elif f_score_val >= 6:
    fund_score = 70
elif f_score_val >= 5:
    fund_score = 55
else:
    fund_score = 40

# ===== ROE Bonus =====
if roe_val is not None:
    if roe_val > 25:
        fund_score = min(100, fund_score + 12)
    elif roe_val > 20:
        fund_score = min(100, fund_score + 10)
    elif roe_val > 15:
        fund_score = min(100, fund_score + 8)
    elif roe_val < 5:
        fund_score = max(0, fund_score - 15)

# ===== Smart Money & Industry Bonus =====
foreign_streak = fund_data.get('foreign_buy_streak', 0)
foreign_bonus = 0
if foreign_streak >= 5:
    foreign_bonus = 20
elif foreign_streak >= 3:
    foreign_bonus = 15

industry_perf = fund_data.get('industry_performance', 0)
industry_bonus = 0
if industry_perf > 5:
    industry_bonus = 15
elif industry_perf > 0:
    industry_bonus = 10

fund_score = min(100, fund_score + foreign_bonus + industry_bonus)
```

---

### 6.3 Master Score & Signal

**Formula:**
```python
# Master Score = 70% Technical + 30% Fundamental (per spec v10)
base_master_score = int(tech_score * 0.7 + fund_score * 0.3)

# VETO: Set master_score = 10 (strict per spec)
if is_vetoed:
    master_score = 10
    base_master_score = 10
else:
    master_score = max(0, min(100, base_master_score + market_weight))
```

**Signal Determination:**
```python
is_sell_zone = market_rsi > 70

# If VETO, always signal WAIT
if is_vetoed:
    signal = "WAIT"
    tech_score = max(25, tech_score - 30) if tech_score > 25 else 25
    is_fast_pick = False
elif criteria_met >= 9:
    if is_sell_zone:
        signal = "STRONG_BUY" if (adx_val > 25 and volume_ratio_val > 1.0) else "WATCH"
    else:
        signal = "STRONG_BUY"
elif tech_score >= 75:
    signal = "STRONG_BUY" if not is_sell_zone else "BUY"
elif tech_score >= 65:
    signal = "BUY" if not is_sell_zone else "ACCUMULATE"
elif tech_score >= 55:
    signal = "ACCUMULATE"
else:
    signal = "WAIT"
```

---

## 7. Frontend Scoring System (JavaScript)

### 7.1 tScore (Technical Score) Calculation

**Location:** `dashboard/templates/dashboard/stock_list.html`  
**Function:** `calculateWealthGuardScore()`  
**Max Score:** 125  

```javascript
function calculateWealthGuardScore(stock) {
    let tScore = 0;
    
    // ===== Status Indicators (max +65) =====
    
    // Ichimoku
    if (ichimoku === 'bullish' || ichimokuTk === 'bullish') tScore += 15;
    
    // SuperTrend
    if (supertrendSignal === 'buy') tScore += 10;
    
    // VWAP
    if (vwapStatus === 'above') tScore += 10;
    
    // SMA Trend
    if (smaTrend === 'perfect') tScore += 20;
    
    // TK Cross
    if (ichimokuTk === 'bullish') tScore += 10;
    
    // ===== Momentum Indicators (max +60) =====
    
    // RSI Zones
    if (rsi >= 45 && rsi <= 65) tScore += 10;
    else if (rsi >= 40 && rsi <= 75) tScore += 5;
    
    // MFI
    if (mfi > 50) tScore += 10;
    else if (mfi > 30) tScore += 5;
    
    // CMF
    if (cmf > 0.1) tScore += 15;
    
    // Volume Ratio
    if (volRatio >= 1.5) tScore += 20;
    
    // Bollinger Position
    if (bbPos >= 30 && bbPos <= 70) tScore += 15;
    
    return tScore;  // Max = 125
}
```

---

### 7.2 fScore (Fundamental Score) Calculation

**Location:** `dashboard/templates/dashboard/stock_list.html`  
**Function:** `calculateWealthGuardScore()`  
**Max Score:** 100  

```javascript
function calculateFundScore(stock) {
    let fundScore = 0;
    
    // ===== ROE (max +25) =====
    if (roe >= 20) fundScore += 25;
    else if (roe >= 15) fundScore += 20;
    else if (roe >= 10) fundScore += 10;
    else if (roe >= 5) fundScore += 5;
    
    // ===== F-Score (max +25) =====
    if (fScore >= 7) fundScore += 25;
    else if (fScore >= 5) fundScore += 15;
    else if (fScore >= 3) fundScore += 10;
    
    // ===== P/E (max +25/-10) =====
    if (pe > 0 && pe <= 10) fundScore += 25;
    else if (pe <= 15) fundScore += 20;
    else if (pe <= 20) fundScore += 10;
    else if (pe <= 30) fundScore += 5;
    else fundScore -= 10;  // pe > 30
    
    // ===== P/B (max +25/-5) =====
    if (pb > 0 && pb <= 1) fundScore += 25;
    else if (pb <= 1.5) fundScore += 20;
    else if (pb <= 2) fundScore += 15;
    else if (pb <= 3) fundScore += 5;
    else fundScore -= 5;  // pb > 3
    
    return fundScore;  // Max = 100
}
```

---

### 7.3 Final Score Calculation

**Location:** `dashboard/templates/dashboard/stock_list.html`  
**Function:** `calculateWealthGuardScore()`  

```javascript
function calculateWealthGuardScore(stock) {
    // ... calculate tScore and fScore ...
    
    // Market Weight Adjustment
    let marketWeight = 1.0;
    if (marketRsi <= 25) {
        marketWeight = 1.2;  // Thị trường quá bán -> tăng trọng số
    }
    
    // Final Score = 40% Fund + 60% Tech
    let masterScore = (fScore * 0.4 + tScore * 0.6) * marketWeight;
    masterScore = Math.min(masterScore, 100);
    
    // VETO Effect: Cap at 10
    if (isVeto) {
        masterScore = Math.min(masterScore, 10);
    }
    
    return {
        masterScore: Math.round(masterScore),
        tScore: Math.round(tScore),
        fScore: Math.round(fScore),
        isVeto: isVeto,
        vetoReasons: vetoReasons,
        group: determineGroup(masterScore, isVeto, criteria, isFast)
    };
}
```

---

## 8. Score Weight Comparison

### 8.1 Weight Distribution

| Component | Backend (Python) | Frontend (JavaScript) | Difference |
|-----------|-----------------|----------------------|------------|
| Technical | **70%** | **60%** | **-10%** |
| Fundamental | **30%** | **40%** | **+10%** |
| Market Weight | ❌ None | ✅ 1.2x when RSI < 25 | New in Frontend |

### 8.2 Scoring Range

| Metric | Backend | Frontend |
|--------|---------|----------|
| Technical Score | 0-100 | 0-125 |
| Fund Score | 0-100 | 0-100 |
| Master Score | 0-100 | 0-100 |

### 8.3 VETO Effect

| Behavior | Backend | Frontend |
|----------|---------|----------|
| Score when VETO | = 37 | ≤ 10 |
| Impact | Moderate cap | Strict cap |

### 8.4 Detailed Component Comparison

| Indicator | Backend Contribution | Frontend Contribution |
|-----------|---------------------|----------------------|
| **RSI** | ±12 | +10 |
| **ADX** | +12 | 0 |
| **+DI vs -DI** | ±10 | 0 |
| **MACD** | +8 | 0 |
| **CMF** | ±12/-15 | +15 |
| **SMA** | ±10/-8 | +20 (perfect) |
| **Volume** | +8 | +20 |
| **R:R** | ±10/-10 | 0 |
| **VWAP** | 0 | +10 |
| **SuperTrend** | 0 | +10 |
| **Ichimoku** | 0 | +25 |
| **MFI** | 0 | +10 |
| **BB Position** | 0 | +15 |

---

## 9. VETO Rules

### 9.1 Backend VETO (sync_service.py)

**Location:** `dashboard/sync_service.py` - `compute_core_logic()`  
**10 VETO Conditions:**

```python
# Veto 1: CMF < 0 (spec)
if cmf_val < 0:
    is_vetoed = True
    veto_reason = f"CMF < 0 ({cmf_val:.2f})"
    veto_count += 1

# Veto 2: ROE < 15% (spec)
elif roe_val is not None and roe_val < 15:
    is_vetoed = True
    veto_reason = f"ROE < 15% ({roe_val:.1f}%)"
    veto_count += 1

# Veto 3: F-Score < 5/9 (spec)
elif f_score_val < 5:
    is_vetoed = True
    veto_reason = f"F-Score < 5 ({f_score_val}/9)"
    veto_count += 1

# Veto 4: Market RSI > 80 (spec)
elif market_rsi > 80:
    is_vetoed = True
    veto_reason = f"Market RSI > 80 ({market_rsi:.1f})"
    veto_count += 1

# Veto 5: Ichimoku Bearish (spec)
elif ichimoku_status_val == "bearish":
    is_vetoed = True
    veto_reason = "Ichimoku Bearish"
    veto_count += 1

# Veto 6: TK-KJ Bearish (Tenkan < Kijun) (spec)
elif tech.get("ichimoku_tenkan", 0) < tech.get("ichimoku_kijun", 0) and tech.get("ichimoku_tenkan", 0) > 0:
    is_vetoed = True
    veto_reason = "TK < KJ (Bearish)"
    veto_count += 1

# Veto 7: R:R < 1.0 (spec)
elif rr_ratio < 1.0:
    is_vetoed = True
    veto_reason = f"R:R < 1.0 ({rr_ratio:.2f})"
    veto_count += 1

# Veto 8: Inverted SL (Entry <= Stop Loss) (spec)
elif has_inverted_sl:
    is_vetoed = True
    veto_reason = "Inverted SL (Entry <= SL)"
    veto_count += 1

# Veto 9: ATR = 0 (spec)
elif atr_value <= 0:
    is_vetoed = True
    veto_reason = "ATR = 0"
    veto_count += 1

# Veto 10: Missing Financial Data (spec) - NO FALLBACK DATA
elif roe_val is None or fund_data.get('pe') is None or fund_data.get('pb') is None:
    is_vetoed = True
    veto_reason = "Missing Financial Data"
    veto_count += 1
```

**VETO Effect:**
- `master_score` = 10 (strict cap)
- `tech_score` = max(25, tech_score - 30)
- `is_fast_pick` = False
- `signal` = "WAIT"

---

### 9.3 Frontend VETO (JavaScript)

**Location:** `dashboard/templates/dashboard/stock_list.html`  
**Function:** `calculateWealthGuardScore()`  

```javascript
function calculateWealthGuardScore(stock) {
    let isVeto = false;
    let vetoReasons = [];
    
    // 1. ROE < 15%
    if (roe < 15) {
        isVeto = true;
        vetoReasons.push('ROE < 15%');
    }
    
    // 2. F-Score < 5
    if (fScore < 5) {
        isVeto = true;
        vetoReasons.push('F-Score < 5');
    }
    
    // 3. Market RSI > 80
    if (marketRsi > 80) {
        isVeto = true;
        vetoReasons.push('Market RSI > 80');
    }
    
    // 4. Ichimoku Bearish
    if (ichimoku === 'bearish') {
        isVeto = true;
        vetoReasons.push('Ichimoku Bearish');
    }
    
    // 5. TK-KJ giảm
    if (ichimokuTk === 'bearish') {
        isVeto = true;
        vetoReasons.push('TK-KJ giảm');
    }
    
    return { isVeto, vetoReasons };
}
```

---

### 9.4 Complete VETO Matrix

| # | Condition | Scanner | Export | Frontend |
|---|-----------|---------|--------|----------|
| 1 | CMF < 0 | ✅ | ❌ | ❌ |
| 2 | R:R < 1.0 | ✅ | ❌ | ❌ |
| 3 | R:R = 0 | ✅ | ❌ | ❌ |
| 4 | Inverted SL | ✅ | ❌ | ❌ |
| 5 | ATR = 0 | ✅ | ❌ | ❌ |
| 6 | ROE < 15% | ❌ | ✅ | ✅ |
| 7 | F-Score < 5 | ❌ | ✅ | ✅ |
| 8 | Market RSI > 80 | ❌ | ✅ | ✅ |
| 9 | Ichimoku Bearish | ❌ | ❌ | ✅ |
| 10 | TK-KJ Bearish | ❌ | ❌ | ✅ |

---

## 10. Stock Classification

### 10.1 Classification Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                    CLASSIFICATION TREE                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌───────────┐                                              │
│  │   VETO   │──▶ Bị loại, Score ≤ 10 (Frontend)           │
│  └─────┬─────┘                                              │
│        │ Score ≤ 37 (Backend)                              │
│        ▼                                                    │
│  ┌───────────┐                                              │
│  │   GOLD    │──▶ Master ≥ 70, Criteria ≥ 9, Không VETO   │
│  └─────┬─────┘     Không SLOW                             │
│        │                                                    │
│        ▼                                                    │
│  ┌─────────────┐                                            │
│  │ GUERRILLA  │──▶ Master 50-69, Có FAST PICK              │
│  └──────┬──────┘     Không VETO                            │
│         │                                                   │
│         ▼                                                   │
│  ┌───────────┐                                              │
│  │   RISK    │──▶ Mặc định, Không VETO                    │
│  └───────────┘                                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 10.2 GOLD Classification

**Requirements:**
```python
# From JavaScript
if (masterScore >= 70 && criteriaMet >= 9 && !isVeto && !isSlowMode) {
    group = "GOLD";
}
```

**Characteristics:**
- ✅ Master Score >= 70
- ✅ Criteria Met >= 9/12
- ✅ Not VETO'd
- ✅ Not in SLOW mode
- ✅ Strong Uptrend (SMA Perfect)
- ✅ Bullish Ichimoku

**Score Breakdown (Target):**
| Component | Target | Notes |
|-----------|--------|-------|
| Technical | 70-80 | Strong trend signals |
| Fundamental | 60-80 | Solid financials |
| Master | 70+ | Combined strength |

---

### 10.3 GUERRILLA Classification

**Requirements:**
```python
# From JavaScript
if (masterScore >= 50 && masterScore < 70 && isFastPick && !isVeto) {
    group = "GUERRILLA";
}
```

**Characteristics:**
- 🎯 Master Score: 50-69
- 🎯 Has FAST PICK signals (R:R >= 2.0)
- 🎯 Not VETO'd
- 🎯 Expected Hold <= 10 days

**FAST PICK Requirements:**
```python
# From vn30_scanner.py
if (criteria_met >= 9
    and risk_reward_ratio >= 2.0
    and cmf > 0
    and not is_vetoed
    and not is_slow_mode
    and estimated_days <= 10):
    is_fast_pick = True
```

---

### 10.4 FAST PICK Conditions

**Complete FAST PICK Logic:**
```python
# From _check_fast_pick() in vn30_scanner.py

# Must pass ALL conditions:
conditions = [
    criteria_met >= 9,                    # Strong criteria
    risk_reward_ratio >= 2.0,            # Excellent R:R
    cmf > 0,                             # Money flowing in
    not is_vetoed,                       # Pass VETO
    not is_slow_mode,                    # Not slow
    current_price > sma_20 if sma_20 > 0 else False  # Above SMA20
]

is_fast_pick = all(conditions)
```

---

### 10.5 RISK Classification

**Requirements:**
```javascript
// Default when not VETO
if (!isVeto) {
    group = "RISK";
}
```

**Characteristics:**
- ⚠️ Not VETO'd
- ⚠️ Not GOLD
- ⚠️ Not GUERRILLA
- ⚠️ May have moderate scores

---

### 10.6 VETO Classification

**Requirements:** Any VETO condition triggered

**Behavior:**
- Backend: Score capped at 37
- Frontend: Score capped at 10
- Signal set to "WAIT"

---

## 11. 12-Point Evaluation Criteria

### 11.1 Criteria List (Backend)

**Location:** `dashboard/analyzers/vn30_scanner.py`  
**Method:** `_evaluate_criteria()`  

```python
def _evaluate_criteria(self, pick: StockPick):
    """12 tiêu chí - chỉ đánh giá khi không bị VETO"""
    criteria = []
    
    # Skip if vetoed
    if pick.is_vetoed:
        pick.criteria_met = 0
        pick.criteria_list = []
        return
    
    # ===== CRITERIA 1: RSI Sweet Spot =====
    if 50 <= pick.rsi <= 65:
        criteria.append("RSI Sweet Spot (50-65)")
    
    # ===== CRITERIA 2: ADX Strong =====
    if pick.adx > 20:
        criteria.append("ADX Strong (>20)")
    
    # ===== CRITERIA 3: +DI > -DI =====
    if pick.plus_di > pick.minus_di:
        criteria.append("DI Bullish")
    
    # ===== CRITERIA 4: CMF Positive =====
    if pick.cmf > 0:
        criteria.append("CMF Positive")
    
    # ===== CRITERIA 5: Volume Active =====
    if pick.volume_ratio > 1.0:
        criteria.append("Volume Active")
    
    # ===== CRITERIA 6: Above SMA20 =====
    if pick.sma_20 > 0 and pick.current_price > pick.sma_20:
        criteria.append("Above SMA20")
    
    # ===== CRITERIA 7: MACD Bullish =====
    if pick.macd > pick.macd_signal:
        criteria.append("MACD Bullish")
    
    # ===== CRITERIA 8: R:R Good/Excellent =====
    if pick.risk_reward_ratio >= 2.0:
        criteria.append("R:R Excellent (>=2.0)")
    elif pick.risk_reward_ratio >= 1.5:
        criteria.append("R:R Good (>=1.5)")
    elif pick.risk_reward_ratio >= 1.0:
        criteria.append("R:R OK (>=1.0)")
    
    # ===== CRITERIA 9: F-Score OK =====
    if pick.has_fundamental_data and pick.f_score >= 2:
        criteria.append("F-Score OK (>=2)")
    
    # ===== CRITERIA 10: Fast Holding =====
    if 0 < pick.estimated_days_to_target <= 10:
        criteria.append("Fast Holding (<=10d)")
    
    # ===== CRITERIA 11: SMA Perfect (Frontend only) =====
    # if smaTrend === 'perfect':
    #     criteria.push("SMA Perfect");
    
    # ===== CRITERIA 12: Ichimoku Bullish (Frontend only) =====
    # if ichimoku === 'bullish':
    #     criteria.push("Ichimoku Bullish");
    
    pick.criteria_met = len(criteria)
    pick.criteria_list = criteria
```

---

### 11.2 Criteria Summary Table

| # | Criteria | Threshold | Points |
|---|----------|-----------|--------|
| 1 | RSI Sweet Spot | 50-65 | 🎯 |
| 2 | ADX Strong | > 20 | 💪 |
| 3 | DI Bullish | +DI > -DI | 📈 |
| 4 | CMF Positive | > 0 | 💰 |
| 5 | Volume Active | > 1.0x | 📊 |
| 6 | Above SMA20 | Price > SMA20 | ⬆️ |
| 7 | MACD Bullish | MACD > Signal | 📉 |
| 8 | R:R Excellent | >= 2.0 | 🎯 |
| 9 | F-Score OK | >= 2 | 📋 |
| 10 | Fast Holding | <= 10 days | ⏱️ |

---

### 11.3 Criteria Usage in Signals

```python
# From signal determination
if pick.criteria_met >= 9 and not pick.is_slow_mode:
    # In SELL ZONE (RSI > 70), require extra conditions
    if is_sell_zone:
        if pick.adx > 25 and pick.volume_ratio > 1.0:
            pick.signal = "STRONG_BUY"
        elif pick.adx > 20:
            pick.signal = "BUY"
        else:
            pick.signal = "WATCH"
    else:
        pick.signal = "STRONG_BUY"
```

---

## 12. Market Risk Assessment

### 12.1 Market RSI Zones

**Location:** `dashboard/sync_service.py` - `compute_core_logic()`  

```python
# Risk Assessment
is_market_high_risk = market_rsi > 80

sl_distance_pct = ((entry - stop_loss) / entry) * 100 if entry > 0 else 0

if sl_distance_pct > 7:
    stock_risk_level = "High"
    stock_risk_reason = f"SL cách xa {sl_distance_pct:.1f}%"
elif sl_distance_pct > 5:
    stock_risk_level = "Medium"
    stock_risk_reason = f"SL cách xa {sl_distance_pct:.1f}%"
elif sl_distance_pct > 3:
    stock_risk_level = "Low"
    stock_risk_reason = f"SL cách xa {sl_distance_pct:.1f}%"
else:
    stock_risk_level = "Very Low"
    stock_risk_reason = f"SL gần {sl_distance_pct:.1f}%"

if sma_50_val > 0 and price_val < sma_50_val:
    stock_risk_level = "High"
    stock_risk_reason = "Giá dưới SMA50 (xu hướng dài hạn giảm)"

is_high_risk = stock_risk_level == "High"
```

---

### 12.2 Market Weight Adjustment

**Location:** `dashboard/sync_service.py` - `compute_core_logic()`  

```python
# Market Weight Adjustment
market_weight = 0
if market_rsi > 85:
    market_weight = -25
elif market_rsi > 80:
    market_weight = -20
elif market_rsi > 70:
    market_weight = -10
elif market_rsi < 25:
    market_weight = 20  # x1.2 boost when Market RSI < 25
elif market_rsi < 40:
    market_weight = +10

# Master Score = 70% Technical + 30% Fundamental
base_master_score = int(tech_score * 0.7 + fund_score * 0.3)
master_score = max(0, min(100, base_master_score + market_weight))
```

---

### 12.3 Market Status Zones

| Zone | Market RSI | Color | Action |
|------|------------|-------|--------|
| EXTREME DANGER | > 85 | Red | Heavy penalty, no new buys |
| DANGER | > 80 | Red | VETO applies, only take profit |
| OVERBOUGHT | > 75 | Orange | Reduce position, FV adjustment -10% |
| WARNING | > 70 | Yellow | 20-30% cash only |
| NEUTRAL | 40-70 | Green | Normal deployment |
| OVERSOLD | < 40 | Blue | +10 market weight |
| EXTREME OVERSOLD | < 25 | Purple | +20 market weight (1.2x boost) |

---

## 13. Investment Horizon

### 13.1 Timeframe Labels

**Location:** `dashboard/sync_service.py` - `compute_core_logic()`  

```python
# Trend Factor dựa trên ADX
adx_val = tech.get("adx", 25)
if adx_val > 25:
    trend_factor = 0.8
elif adx_val < 20:
    trend_factor = 0.4
else:
    trend_factor = 0.6

# Est. Days với Trend Factor
price_diff = take_profit - entry
if atr_value > 0 and atr_value < entry:
    est_days = price_diff / (atr_value * trend_factor)
elif atr_value > 0:
    est_days = price_diff / (atr_value * trend_factor)
else:
    est_days = price_diff / (entry * 0.02 * trend_factor) if entry > 0 else 10

est_days = min(max(est_days, 1), 30)

# Timeframe Label
if est_days <= 5:
    timeframe_label = "Fast T+"
    timeframe_color = "emerald"
elif est_days <= 15:
    timeframe_label = "Swing Pick"
    timeframe_color = "sky"
else:
    timeframe_label = "Position"
    timeframe_color = "amber"
```

---

### 13.2 Estimated Days Calculation

**Location:** `dashboard/analyzers/vn30_scanner.py`  
**Method:** `_calculate_trading_levels()`  

```python
def _calculate_estimated_days(self, pick: StockPick, market_rsi: float):
    """Calculate estimated days to reach target"""
    
    if pick.atr > 0:
        price_diff = pick.take_profit - pick.entry_price
        if price_diff > 0:
            # Base calculation: ATR-based
            raw_days = price_diff / pick.atr
            
            # RSI adjustment: Market overbought = longer wait
            if market_rsi > 80:
                raw_days += 3  # Add 3 days for overbought market
            
            # Apply constraints
            pick.estimated_days_to_target = max(raw_days, self.MIN_HOLDING_DAYS)
            pick.estimated_days_to_target = round(pick.estimated_days_to_target, 1)
    
    # Mark as SLOW if exceeds threshold
    if pick.estimated_days_to_target > self.SLOW_THRESHOLD_DAYS:
        pick.is_slow_mode = True
```

**Constants:**
```python
MIN_HOLDING_DAYS = 3      # Minimum hold period
SLOW_THRESHOLD_DAYS = 10  # Mark as SLOW if > 10 days
```

---

### 13.3 Timeframe Summary

| Timeframe | ADX | Expected Days | Strategy |
|-----------|-----|--------------|----------|
| SWING | >= 25 | 5-20 days | Trend following |
| SHORT-TERM | 20-25 | 3-10 days | Quick trades |
| WAIT | < 20 | N/A | No position |

---

## 14. Trading Levels Calculation

### 14.1 Entry Price

```python
# Entry = Current Price (market order assumption)
entry_price = current_price
```

---

### 14.2 Stop Loss Calculation

**Location:** `dashboard/analyzers/vn30_scanner.py`  
**Method:** `_calculate_trading_levels()`  

```python
def _calculate_stop_loss(self, pick: StockPick):
    """
    Stop Loss = FV_Daily - (ATR × 1.5)
    Must be at least 3% below entry
    """
    min_sl_distance = pick.current_price * 0.03  # 3% minimum
    
    # Find natural support levels
    bb_lower_support = pick.bb_lower if pick.bb_lower > 0 else 0
    sma20_support = pick.sma_20 if pick.sma_20 > 0 else 0
    atr_support = pick.current_price - (pick.atr * 2) if pick.atr > 0 else 0
    
    supports = [s for s in [bb_lower_support, sma20_support, atr_support] if s > 0]
    
    if supports:
        raw_sl = max(supports)
        # Ensure at least 3% from entry
        if pick.current_price - raw_sl < min_sl_distance:
            raw_sl = pick.current_price - min_sl_distance
    else:
        # No support -> use 5% below entry
        raw_sl = pick.current_price * 0.95
        pick.has_inverted_sl = True
    
    # Final check: SL must be < Entry
    if raw_sl >= pick.current_price:
        pick.has_inverted_sl = True
        raw_sl = pick.current_price * 0.95
    
    pick.stop_loss = round(raw_sl, 2)
```

---

### 14.3 Take Profit Calculation

```python
def _calculate_take_profit(self, pick: StockPick):
    """
    Take Profit = min(BB_Upper, Entry + 10%)
    """
    bb_upper_tp = pick.bb_upper if pick.bb_upper > 0 else 0
    target_tp = pick.current_price * 1.10  # 10% target
    
    if bb_upper_tp > 0:
        pick.take_profit = round(min(bb_upper_tp, target_tp), 2)
    else:
        pick.take_profit = round(target_tp, 2)
```

---

### 14.4 Risk:Reward Ratio

```python
def _calculate_rr_ratio(self, pick: StockPick):
    """
    R:R = (TP - Entry) / (Entry - SL)
    """
    risk = pick.entry_price - pick.stop_loss
    reward = pick.take_profit - pick.entry_price
    
    if risk >= min_sl_distance:  # Ensure risk >= 3%
        pick.risk_reward_ratio = round(reward / risk, 2)
    else:
        pick.risk_reward_ratio = 0  # Invalid
```

---

### 14.5 Complete Trading Levels Example

```
Given:
- Current Price: 95,000
- ATR: 2,000 (2.1% of price)
- BB_Lower: 91,000
- SMA20: 92,500
- BB_Upper: 99,000

Calculations:
- Min SL Distance: 95,000 × 0.03 = 2,850
- Supports: [91,000, 92,500, 91,000] (ATR-based)
- Raw SL: max(91,000, 92,500, 91,000) = 92,500
- Check: 95,000 - 92,500 = 2,500 < 2,850 ❌
- Adjusted SL: 95,000 - 2,850 = 92,150

- TP Options: BB_Upper = 99,000, 10% Target = 104,500
- Take Profit: min(99,000, 104,500) = 99,000

- Entry: 95,000
- Stop Loss: 92,150
- Take Profit: 99,000

- Risk: 95,000 - 92,150 = 2,850
- Reward: 99,000 - 95,000 = 4,000
- R:R Ratio: 4,000 / 2,850 = 1.40
```

---

## 15. Data Flow Architecture

### 15.1 Data Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                         DATA PIPELINE                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                  │
│  │ vnstock │    │ vnstock_ │    │ vnstock_ │                  │
│  │   _data │    │    _ta   │    │  _news   │                  │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘                  │
│       │               │               │                         │
│       ▼               ▼               ▼                         │
│  ┌─────────────────────────────────────────────┐                │
│  │           StockData + OHLCV                │                │
│  └─────────────────────┬───────────────────────┘                │
│                        │                                        │
│                        ▼                                        │
│  ┌─────────────────────────────────────────────┐                │
│  │         Technical Indicators                │                │
│  │  RSI, ADX, CMF, MFI, MACD, VWAP, etc.     │                │
│  └─────────────────────┬───────────────────────┘                │
│                        │                                        │
│                        ▼                                        │
│  ┌─────────────────────────────────────────────┐                │
│  │         Fundamental Data                    │                │
│  │  F-Score, ROE, P/E, P/B                    │                │
│  └─────────────────────┬───────────────────────┘                │
│                        │                                        │
│                        ▼                                        │
│  ┌─────────────────────────────────────────────┐                │
│  │       VN30 Scanner / Stock Analyzer        │                │
│  │  - Trading Levels (Entry, SL, TP)          │                │
│  │  - VETO Check                              │                │
│  │  - Criteria Evaluation                      │                │
│  │  - Scoring (Tech + Fund)                    │                │
│  │  - Classification (GOLD, GUERRILLA, etc.)  │                │
│  └─────────────────────┬───────────────────────┘                │
│                        │                                        │
│           ┌────────────┴────────────┐                           │
│           │                         │                           │
│           ▼                         ▼                           │
│  ┌─────────────────┐    ┌─────────────────────┐              │
│  │    SQLite DB    │    │    JSON Response     │              │
│  │   (Storage)     │    │    (API/Frontend)    │              │
│  └─────────────────┘    └─────────────────────┘              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

### 15.2 Key Files

| File | Purpose | Language |
|------|---------|----------|
| `dashboard/analyzers/vn30_scanner.py` | Main scanner logic | Python |
| `dashboard/analyzers/stock_analyzer.py` | Stock analysis module | Python |
| `dashboard/analyzers/signals.py` | Signal definitions | Python |
| `dashboard/views.py` | API endpoints, FV calculation | Python |
| `dashboard/templates/dashboard/stock_list.html` | Frontend UI + JS scoring | JavaScript/HTML |
| `dashboard/models.py` | Database models | Python |

---

## 16. Known Issues & Conflicts

### 16.1 Weight Inconsistency

| Component | Python | JavaScript | Recommended |
|-----------|--------|------------|-------------|
| Technical | 70% | 60% | Sync to one |
| Fundamental | 30% | 40% | Sync to one |

**Recommendation:** Add configuration option for weight preference.

---

### 16.2 VETO Condition Gaps

**Backend Scanner has 5 exclusive VETO conditions:**
1. CMF < 0
2. R:R < 1.0
3. R:R = 0
4. Inverted SL
5. ATR = 0

**Frontend has 3 exclusive VETO conditions:**
1. Ichimoku Bearish
2. TK-KJ Bearish
3. (ROE/F-Score/Market RSI are shared)

**Recommendation:** Implement unified VETO system in both.

---

### 16.3 Score Cap Difference ✅ RESOLVED

| System | VETO Score Cap | Status |
|--------|----------------|--------|
| Backend (v10) | 10 | ✅ Unified |
| Frontend | 10 | ✅ Unified |

### 16.4 Market Weight Only in Frontend ✅ RESOLVED

Implemented Market Weight (x1.2 when Market RSI < 25) in Backend v10.

### 16.5 Criteria Count Difference ✅ RESOLVED

Both Backend and Frontend now use **12 criteria**.

---

## APPENDIX A: Configuration Constants

```python
# sync_service.py (v10)
WEIGHT_TECHNICAL = 0.70       # 70% Technical
WEIGHT_FUNDAMENTAL = 0.30      # 30% Fundamental
MARKET_WEIGHT_BULL = 1.2      # Market oversold bonus
MARKET_RSI_OVERSOLD = 25     # Threshold for oversold market
VETO_SCORE_CAP = 10           # Score when VETO'd (strict)
SLOW_THRESHOLD_DAYS = 10      # Mark as SLOW if > 10 days
```

```javascript
// Frontend (DISPLAY ONLY - no scoring)
VETO_SCORE_MAX = 10;         // Score cap when VETO'd
MARKET_WEIGHT_BULL = 1.2;    // Weight when market oversold (reference only)
MARKET_RSI_OVERSOLD = 25;    // Threshold for oversold market (reference only)
```

---

## APPENDIX B: Signal Types

| Signal | Meaning | Color |
|--------|---------|-------|
| STRONG_BUY | Excellent opportunity | 🟢🟢 |
| BUY | Good opportunity | 🟢 |
| ACCUMULATE | Consider adding | 🟢🟡 |
| NEUTRAL | Hold/Neutral | 🟡 |
| WATCH | Wait for better entry | 🟡🟠 |
| WAIT | Do not buy | 🟠🔴 |
| SELL | Exit position | 🔴 |

---

## APPENDIX C: Classification Colors

| Group | Color Code | HTML Color |
|-------|------------|------------|
| GOLD | ⭐ Gold | `#f59e0b` |
| GUERRILLA | 🎯 Green | `#22c55e` |
| RISK | ⚠️ Gray | `#94a3b8` |
| VETO | 🚫 Red | `#ef4444` |

---

## APPENDIX D: Glossary

| Term | Definition |
|------|------------|
| ATR | Average True Range - Volatility measure |
| CMF | Chaikin Money Flow - Money flow indicator |
| FV | Fair Value - Estimated intrinsic price |
| MFI | Money Flow Index - Volume-weighted RSI |
| R:R | Risk:Reward Ratio |
| SMA | Simple Moving Average |
| VWAP | Volume Weighted Average Price |

---

**Document End**

*This specification document was generated from source code analysis of the VN30 Alpha Scanner v2 system.*
