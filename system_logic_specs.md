# SYSTEM LOGIC SPECIFICATIONS
## VN30 Alpha Scanner v10.2 - UNIFIED LOGIC (Database-First Architecture)

**Document Version:** 3.4
**Last Updated:** 2026-05-17
**Status:** Unified - Backend is Single Source of Truth

---

## CHANGES IN v10.4 (2026-05-17)

### Task 1: Centralized Valuation Logic
- Tạo `dashboard/services/valuation_engine.py` với class `ValuationService`
- Singleton pattern: `get_valuation_service()`
- Tính FV Daily, FV Weekly, Intrinsic Value tập trung
- Sử dụng bởi cả `sync_service.py` và `views.py`

### Task 2: Handle Negative P/E
- `sync_sector_benchmarks()` đã filter `ttm_pe > 0` và `ttm_pb > 0`
- Fallback về `INDUSTRY_CONFIG` nếu stock_count < 3 sau filter

### Task 3: Single Stock Diagnostic Tool
- Hàm `diagnose_stock(symbol)` trong `sync_service.py`
- In chi tiết tất cả bước: Raw data → Valuation → FV → Criteria → VETO
- Trả về JSON với đầy đủ thông tin

### Task 4: CSV Export Synchronization
- `export_stocks_csv()` và `export_stock_detail_csv()` sử dụng `ValuationService`
- Đảm bảo tính nhất quán 100% với backend

### Task 5: IndustryValuation Priority
- `get_industry_pe_average()` ưu tiên lấy từ `IndustryValuation` (đã filtered P/E > 0)
- Fallback: VNINDEX PE → INDUSTRY_CONFIG

---

## PREVIOUS CHANGES (v10.3)

### Dynamic Sector Valuation - MEDIAN-Based Real Market Data

#### Bước 1: Model IndustryValuation
```python
class IndustryValuation(models.Model):
    name = models.CharField(max_length=50, unique=True)  # VD: "Banking"
    sector_code = models.CharField(max_length=20)  # ICB code
    median_pe = models.FloatField(default=0)  # Median P/E của ngành
    median_pb = models.FloatField(default=0)  # Median P/B của ngành
    stock_count = models.IntegerField(default=0)  # Số mã trong ngành
    market_cap_avg = models.FloatField(default=0)  # Vốn hóa TB
    updated_at = models.DateTimeField(auto_now=True)
```

#### Bước 2: sync_sector_benchmarks()
- **Source:** `vnstock_data.Insights().screener().filter()`
- **Filter:** Vốn hóa > 100 tỷ, P/E 0-1000, P/B 0-50
- **Aggregation:** MEDIAN (không phải Mean) để loại outliers
- **Nhóm theo:** `vi_sector` column

#### Bước 3: get_target_valuation()
**Priority:**
1. Dynamic Median từ `IndustryValuation` (database)
2. Fallback sang `INDUSTRY_CONFIG` (static)
3. **Wealth Guard Cap:** `Final = min(Dynamic, Static × 1.25)`

#### Bước 4: compute_core_logic() Refactor
- Sử dụng `get_target_valuation()` thay vì `INDUSTRY_CONFIG` trực tiếp
- Tách biệt Intrinsic Value (P/E-based) ra khỏi 52-week high
- FV Weekly = trung bình (Intrinsic + 52-week high)

---

## PREVIOUS CHANGES (v10.2)

### Major Refactoring: Separation of VETO, Valuation, and R:R

#### Bước 1: VETO Health Check (13 Rules) - STANDALONE
- **Location:** `dashboard/sync_service.py` - `check_health_veto()`
- **Purpose:** Chỉ kiểm tra sức khỏe, loại bỏ cổ phiếu rác/nguy hiểm
- **KHÔNG bao gồm R:R hay Định giá trong VETO**

**13 VETO Rules:**
| # | Rule | Condition |
|---|------|-----------|
| 1 | CMF Negative | CMF < 0 |
| 2 | Low Liquidity | VolTB20 < 15 tỷ |
| 3 | No Interest | Volume_Ratio < 0.5 |
| 4 | Downtrend | Giá < SMA50 |
| 5 | Ichimoku Bearish | Mây đỏ/giá dưới mây |
| 6 | No Trend | ADX < 20 |
| 7 | Overbought Extreme | RSI > 80 |
| 8 | BB Overbought | bbPos > 105 |
| 9 | Low ROE | ROE < 15% |
| 10 | Weak F-Score | F-Score < 5 |
| 11 | Negative Growth | Profit_Growth < 0 |
| 12 | Missing Data | Thiếu dữ liệu tài chính |
| 13 | Market Risk | VNIndex RSI > 80 |

#### Bước 2: Fair Value & R:R Thực Chiến
- **FV_Weekly:** Trung bình của (P/E valuation) và (52-week high valuation)
- **PE Multiplier Cap:** 1.25x
- **FV Cap:** Không vượt quá 130% thị giá
- **TP = FV_Weekly**

#### Bước 3: Khoảng thở & R:R Quality
- **Risk Buffer:** Tối thiểu 3% (điều chỉnh SL nếu cần)
- **Valuation "Rẻ":** Chỉ khi Price < FV × 0.9 (biên an toàn 10%)
- **R:R Quality Grading:**
  - ⚠️ Warning: R:R > 7 (cắt lỗ quá sát)
  - ⭐ Golden: 2.5 ≤ R:R ≤ 5.0
  - Good: 1.5 ≤ R:R < 2.5
  - Poor: R:R < 1.5

#### Bước 4: Trailing Stop
- **Trailing SL:** Price × 0.95 (5% từ đỉnh)
- **Final SL:** max(Support_SL, Trailing_SL)
- **R:R được recalculate với Final SL**

#### Bước 5: UI Integration
- R:R column: ⭐ cho Golden, ⚠️ cho Warning
- VETO badge: màu đỏ rực, font bold
- CSV export: thêm Trailing SL, R:R Quality, Chiến lược SL

---

## PREVIOUS CHANGES (v10.1)

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

## 5. Fair Value Calculation (v10.2)

### 5.1 FV_Daily (Fair Value Daily)

**Purpose:** Short-term fair value based on VWAP and SMA20.

**Formula:**
```python
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

### 5.2 FV_Weekly (Fair Value Weekly) - v10.2

**Purpose:** Medium-term fair value based on P/E valuation and 52-week high.

**Formula (v10.2):**
```python
# Step 1: P/E Based Valuation (với cap 1.25x)
pe_industry_avg = fund_data.get('pe_industry_avg', 0) or 0
industry_target_pe = config.get('target', 11.0)
actual_pe = fund_data.get('pe') or 0

if pe_industry_avg > 0:
    target_pe = pe_industry_avg * 1.25  # Cap at 1.25x
    pe_valuation = price_val * (target_pe / actual_pe) if actual_pe > 0 else price_val
elif industry_target_pe > 0:
    target_pe = industry_target_pe * 1.25  # Cap at 1.25x
    pe_valuation = price_val * (target_pe / actual_pe) if actual_pe > 0 else price_val
else:
    pe_valuation = price_val

# Step 2: 52-Week High Based Valuation
high_52w = tech.get('high_52w', 0)
if high_52w > 0:
    high_52w_valuation = high_52w  # Dùng luôn đỉnh cao 52 tuần
else:
    high_52w_valuation = price_val * 1.20  # Fallback: giả định đỉnh cao hơn 20%

# Step 3: FV_Weekly = Trung bình của 2 valuation
fv_weekly = (pe_valuation + high_52w_valuation) / 2

# Step 4: Cap FV_weekly at 130% of current price
max_fv = price_val * 1.30
if fv_weekly > max_fv:
    fv_weekly = max_fv

# Step 5: Market Risk Adjustment (-10% when Market RSI > 75)
if market_rsi > 75:
    fv_weekly = fv_weekly * 0.9
```

**Key Changes in v10.2:**
- FV_Weekly = Trung bình (P/E valuation + 52-week high valuation)
- PE Multiplier Cap: 1.25x (thay vì không giới hạn)
- FV Cap: 130% thị giá (không định giá ảo)

**Example:**
```
If:
- price = 72,900
- actual_PE = 15
- pe_industry_avg = 12
- high_52w = 95,000
- market_rsi = 50

Step 1: target_pe = 12 * 1.25 = 15
        pe_valuation = 72900 * (15 / 15) = 72,900

Step 2: high_52w_valuation = 95,000

Step 3: fv_weekly = (72,900 + 95,000) / 2 = 83,950

Step 4: max_fv = 72,900 * 1.30 = 94,770
        fv_weekly = 83,950 (OK, < max_fv)

Step 5: market_rsi = 50 < 75, no adjustment

Result: FV_Weekly = 83,950
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

### 5.3 Valuation Status (v10.2)

**Definition:** Whether current price is above or below fair value with 10% safety margin.

**Formula (v10.2):**
```python
# Chỉ "Rẻ" nếu Price < FV * 0.9 (biên an toàn 10%)
safe_threshold = fv_weekly * 0.9
valuation_status = "Rẻ" if price_val < safe_threshold else "Đắt"
```

**Key Change in v10.2:**
- "Rẻ" chỉ khi Price < FV × 0.9 (biên an toàn 10%)
- Trước đây: Price < FV là đủ

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

### 9.1 Backend VETO (v10.2 - STANDALONE Health Check)

**Location:** `dashboard/sync_service.py` - `check_health_veto()`
**13 VETO Conditions (KHÔNG bao gồm R:R hay Định giá):**

```python
def check_health_veto(tech, fund_data, market_rsi, df, avg_volume_value):
    """Kiểm tra VETO dựa trên 13 quy tắc sức khỏe"""

    # ===== NHÓM 1: DÒNG TIỀN (3 rules) =====
    # VETO_1: CMF < 0
    if tech.get('cmf', 0) < 0:
        return {"is_vetoed": True, "veto_reason": "VETO_1: CMF < 0"}

    # VETO_2: Volume TB 20 phiên < 15 tỷ
    elif avg_volume_value < 15:
        return {"is_vetoed": True, "veto_reason": "VETO_2: VolTB20 < 15B"}

    # VETO_3: Volume_Ratio < 0.5
    elif tech.get('volume_ratio', 1) < 0.5:
        return {"is_vetoed": True, "veto_reason": "VETO_3: VolRatio < 0.5"}

    # ===== NHÓM 2: XU HƯỚNG & ĐỘNG LƯỢNG (5 rules) =====
    # VETO_4: Giá < SMA50
    elif tech.get('price', 0) > 0 and tech.get('sma_50', 0) > 0:
        if tech['price'] < tech['sma_50']:
            return {"is_vetoed": True, "veto_reason": "VETO_4: Giá < SMA50"}

    # VETO_5: Giá dưới mây Ichimoku hoặc mây đỏ
    elif tech.get('ichimoku_status') == 'bearish':
        return {"is_vetoed": True, "veto_reason": "VETO_5: Ichimoku Bearish"}

    # VETO_6: ADX < 20
    elif tech.get('adx', 25) < 20:
        return {"is_vetoed": True, "veto_reason": "VETO_6: ADX < 20"}

    # VETO_7: RSI > 80
    elif tech.get('rsi', 50) > 80:
        return {"is_vetoed": True, "veto_reason": "VETO_7: RSI > 80"}

    # VETO_8: bbPos > 105
    elif tech.get('bb_percent', 50) > 105:
        return {"is_vetoed": True, "veto_reason": "VETO_8: BB% > 105"}

    # ===== NHÓM 3: SỨC KHỎE TÀI CHÍNH (4 rules) =====
    # VETO_9: ROE < 15%
    elif fund_data.get('roe') is not None and fund_data['roe'] < 15:
        return {"is_vetoed": True, "veto_reason": "VETO_9: ROE < 15%"}

    # VETO_10: F-Score < 5
    elif fund_data.get('f_score', 0) < 5:
        return {"is_vetoed": True, "veto_reason": "VETO_10: F-Score < 5"}

    # VETO_11: Profit_Growth < 0 (trừ cổ phiếu mới listing)
    elif not fund_data.get('is_new_listing', False):
        pg = fund_data.get('profit_growth')
        if pg is not None and pg < 0:
            return {"is_vetoed": True, "veto_reason": "VETO_11: ProfitGrowth < 0"}

    # VETO_12: Thiếu dữ liệu tài chính
    elif fund_data.get('roe') is None or fund_data.get('pe') is None or fund_data.get('pb') is None:
        return {"is_vetoed": True, "veto_reason": "VETO_12: Thiếu dữ liệu tài chính"}

    # ===== NHÓM 4: THỊ TRƯỜNG (1 rule) =====
    # VETO_13: VNIndex RSI > 80
    elif market_rsi > 80:
        return {"is_vetoed": True, "veto_reason": "VETO_13: Market RSI > 80"}

    return {"is_vetoed": False, "veto_reason": ""}
```

**VETO Effect:**
- `master_score` = 10 (strict cap)
- `signal` = "WAIT"
- Vẫn tính toán các chỉ số khác nhưng nhãn hiển thị là 🚫 VETO

**Note:** R:R < 1.0 và Inverted SL đã được chuyển thành **Status Tags/Warnings**, không còn là VETO.

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

## 14. Trading Levels Calculation (v10.2)

### 14.1 Entry Price

```python
# Entry = Current Price (market order assumption)
entry_price = current_price
```

---

### 14.2 Stop Loss Calculation (v10.2 - Support-Based + Trailing)

**Location:** `dashboard/sync_service.py` - `compute_core_logic()`

**Step 1: Calculate Support Price**
```python
# Support = min(SMA50, Low_20)
sma_50_support = tech.get("sma_50", 0)
low_20_val = df['low'].tail(20).min() if df is not None else 0

if sma_50_support > 0 and low_20_val > 0:
    support_price = min(sma_50_support, low_20_val)
elif low_20_val > 0:
    support_price = low_20_val
elif sma_50_support > 0:
    support_price = sma_50_support
else:
    support_price = entry * 0.97
```

**Step 2: Calculate Support-Based SL**
```python
# Stop Loss = Support * 0.985 (tối đa 1.5% dưới support)
stop_loss_support = round(support_price * 0.985, 2)
```

**Step 3: Calculate Trailing SL (5% from price)**
```python
# Trailing SL = 5% below current price
trailing_sl = round(price_val * 0.95, 2)
```

**Step 4: Final SL = max(Support_SL, Trailing_SL)**
```python
final_stop_loss = max(stop_loss_support, trailing_sl)
```

**Step 5: Minimum Risk Buffer (3%)**
```python
# Kiểm tra khoảng cách rủi ro, nếu < 3% thì điều chỉnh SL
risk_percent = (entry - final_stop_loss) / entry
if risk_percent < 0.03:
    final_stop_loss = round(entry * 0.96, 2)  # Cố định 4% risk
```

**Summary:**
- Support SL = min(SMA50, Low_20) × 0.985
- Trailing SL = Price × 0.95
- Final SL = max(Support SL, Trailing SL)
- Minimum Risk = 4% (nếu risk < 3%, điều chỉnh SL = Entry × 0.96)

---

### 14.3 Take Profit Calculation (v10.2 - FV-Based)

**Take Profit = FV_Weekly (xem Section 5)**

```python
take_profit = round(fv_weekly, 2)
```

---

### 14.4 Risk:Reward Ratio (v10.2)

```python
def _calculate_rr_ratio(self, pick: StockPick):
    """
    R:R = (TP - Entry) / (Entry - SL)
    Sử dụng Final Stop Loss (đã bao gồm Trailing)
    """
    risk = entry_price - final_stop_loss
    reward = take_profit - entry_price

    if risk > 0:
        risk_reward_ratio = round(reward / risk, 2)
    else:
        risk_reward_ratio = 0
        is_inverted_risk = True
```

---

### 14.5 R:R Quality Grading (v10.2)

**Location:** `dashboard/sync_service.py` - `compute_core_logic()`

```python
# R:R QUALITY GRADING
if rr_ratio > 7:
    rr_quality = "⚠️ Warning"
    rr_quality_detail = "Cắt lỗ quá sát, rủi ro nhiễu cao"
    rr_warning = f"⚠️ Cắt lỗ quá sát, rủi ro nhiễu cao"
elif 2.5 <= rr_ratio <= 5.0:
    rr_quality = "⭐ Golden"
    rr_quality_detail = "Vùng R:R lý tưởng"
elif 1.5 <= rr_ratio < 2.5:
    rr_quality = "Good"
    rr_quality_detail = "R:R khả thi"
else:
    rr_quality = "Poor"
    rr_quality_detail = "R:R thấp"
```

**Quality Thresholds:**
| Quality | R:R Range | Description |
|---------|-----------|-------------|
| ⚠️ Warning | > 7 | Cắt lỗ quá sát, rủi ro nhiễu cao |
| ⭐ Golden | 2.5 - 5.0 | Vùng R:R lý tưởng |
| Good | 1.5 - 2.5 | R:R khả thi |
| Poor | < 1.5 | R:R thấp |

---

### 14.6 Complete Trading Levels Example (v10.2)

```
Given:
- Current Price: 72,900
- SMA50: 70,000
- Low 20-day: 69,000
- FV_Weekly: 92,367

Calculations:
1. Support = min(70,000, 69,000) = 69,000
2. Support SL = 69,000 × 0.985 = 67,965
3. Trailing SL = 72,900 × 0.95 = 69,255
4. Final SL = max(67,965, 69,255) = 69,255
5. Risk % = (72,900 - 69,255) / 72,900 = 5.0% (OK)
6. TP = FV_Weekly = 92,367
7. R:R = (92,367 - 72,900) / (72,900 - 69,255) = 5.34
8. Quality = Poor (R:R > 5.0)
```

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
