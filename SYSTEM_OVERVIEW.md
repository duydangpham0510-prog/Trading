# VN30 Alpha Scanner - Hệ Thống Phân Tích & Giao Dịch Chứng Khoán

> **Phiên bản**: v2.x  
> **Ngày cập nhật**: 2026-05-19  
> **Tech Stack**: Django 5 + SQLite + Tailwind CSS + HTMX + ECharts

---

## 📋 Mục Lục

1. [Tổng Quan](#-tổng-quan)
2. [Kiến Trúc Hệ Thống](#-kiến-trúc-hệ-thống)
3. [Models & Database](#-models--database)
4. [Views & API Endpoints](#-views--api-endpoints)
5. [Trang Chính](#-trang-chính)
6. [Các Trang Phụ](#-các-trang-phụ)
7. [Luồng Dữ Liệu](#-luồng-dữ-liệu)
8. [Tính Năng Nổi Bật](#-tính-năng-nổi-bật)
9. [Cấu Trúc Thư Mục](#-cấu-trúc-thư-mục)

---

## 🎯 Tổng Quan

Đây là hệ thống **Database-First Stock Scanner** dành cho thị trường chứng khoán Việt Nam (VN30), cung cấp:

- **Quét & Phân tích**: Tự động quét ~33 mã VN30 + MIDCAP
- **Chỉ báo kỹ thuật**: RSI, MACD, Bollinger Bands, Ichimoku, SuperTrend...
- **Định giá tự động**: Fair Value (FV) với Wealth Guard
- **Backtesting**: Kiểm tra chiến lược trên dữ liệu lịch sử
- **Simulation**: Mô phỏng giao dịch với tham số tùy chỉnh
- **Top Picks**: Gợi ý cổ phiếu tiềm năng nhất

---

## 🏗️ Kiến Trúc Hệ Thống

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND                                  │
│  Django Templates + Tailwind CSS + HTMX + ECharts               │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP/JSON
┌────────────────────────────▼────────────────────────────────────┐
│                        BACKEND (Django)                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │   Views      │  │   Models     │  │   Service Modules    │  │
│  │  - stock_list│  │ - StockData  │  │ - valuation_engine   │  │
│  │  - top_picks │  │ - StockAnalysis  │ - sync_service   │  │
│  │  - strategy_ │  │ - SyncStatus │  │ - analyzers/        │  │
│  │    lab       │  │ - Quarterly..│  │   (vn30, gold...)   │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└────────────────────────────┬────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────┐
│                      DATABASE (SQLite)                            │
│  stock_data, stock_analysis, sync_status, quarterly_financial   │
│  industry_valuation, function_registry, execution_history         │
└─────────────────────────────────────────────────────────────────┘
                             ▲
┌────────────────────────────┴────────────────────────────────────┐
│                    DATA SOURCES (vnstock/vnstock_data)          │
│  - Price Data (OHLCV)                                           │
│  - Financial Data (ROE, P/E, F-Score)                          │
│  - Industry Metrics                                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📊 Models & Database

### 1. StockData (`stock_data`)
Lưu trữ dữ liệu kỹ thuật của mã cổ phiếu.

| Trường | Mô tả |
|--------|-------|
| `symbol` | Mã cổ phiếu (VN30: VCB, FPT, HPG...) |
| `price`, `change_percent` | Giá & % thay đổi |
| `volume`, `volume_ratio` | Khối lượng & tỷ lệ so với TB |
| **Technical Indicators** | |
| `rsi`, `adx`, `cmf`, `atr` | Chỉ báo cơ bản |
| `sma_10/20/50` | Đường trung bình |
| `bb_upper/middle/lower` | Bollinger Bands |
| `macd`, `macd_signal` | MACD |
| **Advanced TA** | |
| `mfi`, `vwap`, `ichimoku_*` | Chỉ báo nâng cao |
| `supertrend`, `supertrend_signal` | SuperTrend |
| **Fundamental** | |
| `pe`, `pb`, `roe`, `f_score` | Chỉ số cơ bản |
| `profit_growth` | Tăng trưởng lợi nhuận |

### 2. StockAnalysis (`stock_analysis`)
Kết quả phân tích AI cho mỗi mã.

| Trường | Mô tả |
|--------|-------|
| **Scores** | |
| `master_score` | Điểm tổng hợp (0-100) |
| `technical_score`, `fundamental_score` | Điểm thành phần |
| **Signal** | |
| `signal` | BUY/SELL/WAIT/ACCUMULATE |
| **Trading Levels** | |
| `entry_price`, `stop_loss`, `take_profit` | Mức giá giao dịch |
| `risk_reward_ratio` | Tỷ lệ R:R |
| **Risk Assessment** | |
| `is_vetoed`, `veto_reason` | Cờ VETO & lý do |
| `is_market_high_risk` | Thị trường RSI > 80 |
| `stock_risk_level` | Very Low/Low/Medium/High |
| **Fair Value** | |
| `fv_daily` | FV trong ngày = (VWAP×0.4) + (SMA20×0.6) |
| `fv_weekly` | FV trong tuần (intrinsic-based) |
| `valuation_status` | Rẻ / Đắt |
| **Holding** | |
| `estimated_days_to_target` | Ngày ước tính đến target |
| `timeframe_label` | SWING / GROWTH / GUERRILLA / DIAMOND |
| `target_yield_pct` | Lợi nhuận kỳ vọng % |
| **Smart Money** | |
| `foreign_buy_streak` | Số phiên khối ngoại mua ròng |
| `industry_performance` | % chênh lệch vs ngành |

### 3. SyncStatus (`sync_status`)
Theo dõi trạng thái đồng bộ.

| Trường | Mô tả |
|--------|-------|
| `status` | idle/running/completed/failed |
| `total_symbols`, `processed_symbols` | Tiến trình |
| `started_at`, `completed_at` | Thời gian |

### 4. QuarterlyFinancial (`quarterly_financial`)
Dữ liệu tài chính theo quý.

| Trường | Mô tả |
|--------|-------|
| `quarter` | VD: "2024-Q3" |
| `roe`, `roa`, `pe`, `pb` | Chỉ số quý |
| `f_score` | F-Score (0-9) |
| `is_vetoed` | Cờ VETO quý |

### 5. IndustryValuation (`industry_valuation`)
P/E và P/B median theo ngành.

| Trường | Mô tả |
|--------|-------|
| `name` | Tên ngành (Banking, Technology...) |
| `median_pe`, `median_pb`, `median_de` | Median của ngành |
| `stock_count` | Số mã trong ngành |

---

## 🔌 Views & API Endpoints

### Main Pages

| URL | View | Mô tả |
|-----|------|-------|
| `/stocks/` | `stock_list` | **Trang chính** - Danh sách tất cả cổ phiếu |
| `/top-picks/` | → redirect `/stocks/` | Legacy, chuyển hướng |
| `/overview/` | → redirect `/stocks/` | Legacy, chuyển hướng |
| `/strategy-lab/` | `strategy_lab` | Lab backtesting & simulation |
| `/wealth-guard-backtest/` | `wealth_guard_backtest` | Time-series backtest |
| `/backtest/` | `backtest` | Backtest đơn giản |
| `/history/` | `history` | Lịch sử execution |

### API Endpoints

| URL | Method | Mô tả |
|-----|--------|-------|
| `/api/scan/vn30/` | POST | Trigger sync (full/data_only/analyze) |
| `/api/scan/vn30/` | GET | Lấy kết quả scan |
| `/api/simulate/` | GET | Live simulation với params |
| `/api/backtest/` | GET | Historical backtest |
| `/api/lab/stock-data/` | GET | Lấy data 1 mã |
| `/api/lab/symbols/` | GET | Lấy danh sách symbols |
| `/api/wealth-guard/data/` | GET | Dữ liệu 5 năm cho backtest |
| `/api/quarterly-financial/` | POST | Fetch dữ liệu tài chính quý |
| `/stocks/export/` | GET | Export tất cả ra CSV |
| `/stocks/<symbol>/export/` | GET | Export chi tiết 1 mã |

---

## 📱 Trang Chính (`/stocks/`)

### Giao diện chính bao gồm:

#### 1. Header
- Tiêu đề: "Danh Sách Cổ Phiếu - VN30 Alpha Scanner v2"
- Navigation: Stocks, History, Strategy Lab
- Nút Export CSV

#### 2. Summary Cards (7 cards)
| Card | Màu | Dữ liệu |
|------|-----|----------|
| Tổng quét | Blue | `total_scanned` |
| Tín hiệu BUY | Green | `bullish_count` |
| VETO | Red | `vetoed_count` |
| Fast Pick | Orange | `fast_count` |
| Qualified (≥7 criteria) | Purple | `qualified_count` |
| High Risk | Red | `high_risk_count` |
| VNIndex RSI | dynamic | Market status |

#### 3. Filters Panel
- **Loại**: all, buy, veto, fast, high_risk, qualified
- **Sắp xếp**: master_score, rsi, criteria, rr, price, volume, change
- **Thị trường**: all, VN30, MIDCAP, SMALL
- **Ngành**: Banking, Technology, Real Estate...
- **Tìm kiếm**: Symbol/Company name
- **Điểm tối thiểu**: Slider

#### 4. Stock Table
Cột chính:
- **Symbol** | **Price** | **Change%**
- **Score**: Master, Tech, Fund
- **Signal**: BUY/SELL/WAIT badge
- **R:R Ratio** | **Criteria**
- **Entry/SL/TP**
- **Target Yield%** | **Days to Target**
- **Fair Value**: Daily, Weekly, Status
- **Technical**: RSI, CMF, ADX, MFI
- **Fundamental**: ROE, P/E, F-Score
- **Status**: VETO, Fast Pick, High Risk badges
- **Trend**: Uptrend/Downtrend/Sideways
- **Action**: Export detail

---

## 📊 Trang Top Picks (`top_picks.html`)

### Market Status Banner
- **SELL ZONE**: VNIndex RSI > 70 (red gradient)
- **BULL**: Market bullish (green gradient)
- **Conflict**: Tín hiệu mâu thuẫn

### Summary Cards
- Market RSI, Bullish count, Fast Pick count...

### Trading Table (Top 8 picks)
Cột hiển thị:
1. **Rank** (1-8, top 3 có màu gold/silver/bronze)
2. **Symbol** + Company
3. **Score** (bar + number)
4. **Price** + Change%
5. **Signal** badge
6. **R:R** ratio
7. **Entry** / **SL** / **TP**
8. **Est. Days**
9. **Yield%** / **Per Day**
10. **Risk Level** badge
11. **VETO** warning (nếu có)

---

## 🔬 Trang Strategy Lab (`strategy_lab/`)

### Sidebar
- Danh sách symbols (VN30 + MIDCAP)
- Search box

### Main Panel
- Stock info card (symbol, price, change)
- Technical indicators display
- **Simulation Controls**:
  - Price adjustment slider (-20% to +20%)
  - CMF slider
  - RSI slider
  - ADX slider
  - Market RSI slider
  - F-Score slider
  - ROE slider

### Results Panel
- Computed entry/SL/TP
- New scores after simulation
- Signal recommendation

### Backtest Tab
- Date range picker
- Strategy selector (MA Cross, RSI, MACD)
- Results: Win rate, Total return, Profit factor, Max drawdown

---

## 🛡️ Wealth Guard Backtest (`wealth-guard-backtest/`)

### Features
- Symbol selector với search
- Date range (default: 90 days)
- Full 5-year historical data
- Real-time indicator calculation
- **Computed fields**:
  - FV Daily, FV Weekly
  - Signal, Criteria
  - R:R Ratio, Entry/SL/TP
  - Market RSI at each point
  - VETO status history

### Data Table
Scrollable với ~1000+ records
- Date, OHLCV
- All indicators
- Analysis results per day

---

## 🔄 Luồng Dữ Liệu

### 1. Sync Flow (Full Scan)
```
POST /api/scan/vn30/ (mode=full)
    │
    ▼
sync_service.sync_market_data(mode="full")
    │
    ├─► get_stock_list_from_vnstock()     [Lấy VN30 symbols]
    │
    ├─► For each symbol (ThreadPool):
    │   ├─► get_stock_data_from_vnstock()  [Price, volume]
    │   ├─► calculate_technical_indicators() [RSI, MACD...]
    │   ├─► get_financial_data()            [ROE, P/E, F-Score]
    │   └─► compute_core_logic()             [AI scoring]
    │
    ├─► update_industry_medians()          [Industry P/E, P/B]
    │
    └─► Save to DB (StockData, StockAnalysis)
```

### 2. Core Logic (compute_core_logic)
```
Input: symbol, tech_data, fund_data, market_rsi
    │
    ▼
┌─────────────────────────────────────────┐
│ 1. VALIDATION & VETO CHECK             │
│    - F-Score < 5 → VETO                 │
│    - ROE < 15 → VETO                    │
│    - Market RSI > 80 → High Risk Flag   │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│ 2. TECHNICAL SCORING (0-100)             │
│    - Trend Factor (ADX-based)           │
│    - RSI Score                          │
│    - CMF Score                          │
│    - VWAP Status                        │
│    - Volume Ratio                       │
│    - Ichimoku Signal                    │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│ 3. FUNDAMENTAL SCORING (0-100)           │
│    - ROE Score                          │
│    - F-Score                            │
│    - P/E vs Industry                    │
│    - Profit Growth                      │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│ 4. MASTER SCORE                         │
│    Master = (Tech × 0.6) + (Fund × 0.4)│
│    Apply Market Weight Adjustment        │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│ 5. TRADING LEVELS                       │
│    - Entry: Current Price               │
│    - SL: SMA50 (Hard Support)          │
│    - TP: FV_Weekly (Take Profit)       │
│    - R:R = (TP-Entry) / (Entry-SL)    │
└────────────────────┬────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────┐
│ 6. FAIR VALUE (Wealth Guard)            │
│    FV_Daily = (VWAP × 0.4) + (SMA20×0.6)│
│    FV_Weekly = Intrinsic-based formula  │
│    Apply Wealth Guard Cap if needed     │
└────────────────────┬────────────────────┘
                     │
                     ▼
Output: StockAnalysis record
```

### 3. Fast Pick Criteria (≥6 điều kiện)
```
1. RSI in [30-70]
2. CMF > 0
3. ADX > 25
4. Price above SMA20
5. Not VETOed
6. Market RSI < 70
7. Not High Risk
```

---

## ⭐ Tính Năng Nổi Bật

### 1. Database-First Architecture
- **Ưu điểm**: 
  - Load nhanh (đọc từ SQLite thay vì gọi API)
  - Sync background với ThreadPoolExecutor
  - Offline access

### 2. Wealth Guard Valuation
```
FV_Daily = (VWAP × 0.4) + (SMA20 × 0.6)
FV_Weekly = Dynamic based on sector P/E
Valuation Status = Rẻ (price < FV) / Đắt (price > FV)
```

### 3. Smart Money Detection
- Foreign buy streak tracking
- Industry leader identification
- Industry-relative performance

### 4. Risk Management
- **VETO System**: F-Score < 5, ROE < 15 → Block
- **Market High Risk**: VNIndex RSI > 80
- **Stock Risk Level**: Very Low → High
- **Hard Stop Loss**: SMA50 support

### 5. Dynamic Timeframe
| Label | Criteria |
|-------|----------|
| DIAMOND | Master Score ≥ 80, R:R ≥ 3.0 |
| GOLD | Score ≥ 70, R:R ≥ 2.0 |
| GUERRILLA | Fast mode, < 5 days |
| SWING | Standard swing (5-15 days) |
| GROWTH | Long-term (> 30 days) |

---

## 📁 Cấu Trúc Thư Mục

```
Trading-1/
├── manage.py
├── db.sqlite3
├── RUN_GUIDE.md
├── requirements.txt
│
└── dashboard/
    ├── __init__.py
    ├── models.py           # StockData, StockAnalysis, SyncStatus...
    ├── views.py            # Tất cả views & API endpoints
    ├── urls.py             # URL routing
    ├── forms.py            # Dynamic form generation
    ├── registry.py         # Function registry metadata
    ├── runners.py          # Function executors
    ├── services.py         # Service layer
    │
    ├── sync_service.py     # Core sync logic
    │   ├── sync_market_data()
    │   ├── compute_core_logic()
    │   ├── calculate_technical_indicators()
    │   └── get_top_picks_from_db()
    │
    ├── analyzers/          # Chuyên biệt analyzers
    │   ├── __init__.py
    │   ├── stock_analyzer.py
    │   ├── simulator.py     # Trade simulation
    │   ├── signals.py       # Signal generation
    │   ├── index_analyzer.py
    │   ├── gold_analyzer.py
    │   ├── bond_analyzer.py
    │   ├── crypto_analyzer.py
    │   ├── forex_analyzer.py
    │   ├── futures_analyzer.py
    │   └── cw_analyzer.py
    │
    ├── service_modules/
    │   ├── __init__.py
    │   └── valuation_engine.py  # Fair Value calculation
    │
    ├── templatetags/
    │   └── dashboard_extras.py  # Custom template filters
    │
    ├── migrations/         # Database migrations
    │
    └── templates/dashboard/
        ├── stock_list.html     # Trang chính
        ├── top_picks.html      # Top picks dashboard
        ├── strategy_lab.html   # Backtesting lab
        ├── wealth_guard_backtest.html
        ├── backtest.html
        ├── home.html           # Legacy home
        ├── history.html        # Execution history
        └── result_partial.html # HTMX partial
```

---

## 🎨 Design System

### Color Palette
| Purpose | Color |
|---------|-------|
| Background | `#0a0f1a` → `#0e1a2b` gradient |
| Card | `#1e293b` |
| Accent Blue | `#3b82f6` |
| Buy/Success | `#22c55e` |
| Sell/Warning | `#ef4444` |
| VETO | `#dc2626` |
| Gold Pick | `#fbbf24` |
| Purple | `#8b5cf6` |

### Signal Badges
| Signal | Color |
|--------|-------|
| BUY | Green `#22c55e` |
| STRONG_BUY | Deep Green |
| SELL | Red `#ef4444` |
| WAIT | Gray `#64748b` |
| ACCUMULATE | Blue `#3b82f6` |

### Risk Level Badges
| Level | Color |
|-------|-------|
| Very Low | `#10b981` |
| Low | `#22c55e` |
| Medium | `#f59e0b` |
| High | `#ef4444` |

---

## 🔗 External Dependencies

| Library | Version | Purpose |
|---------|---------|---------|
| Django | 5.x | Web framework |
| pandas | latest | Data manipulation |
| vnstock | latest | Free stock data API |
| vnstock_data | ≥3.0.0 | Sponsored unified UI (Silver+) |
| tailwindcss | via CDN | Styling |

---

## 📝 Ghi Chú

1. **vnstock_data Required**: Dashboard sử dụng Unified UI, cần gói Silver+
2. **ThreadPoolExecutor**: Sync chạy song song để tăng tốc
3. **HTMX**: AJAX không cần viết JS cho form submissions
4. **ECharts**: Biểu đồ cho visualization

---

## 🚀 Roadmap (Gợi Ý)

- [ ] React/Next.js frontend thay thế Django Templates
- [ ] Real-time WebSocket updates
- [ ] Portfolio tracking
- [ ] Alert system (Telegram/Email)
- [ ] Mobile app
- [ ] Multi-market support (US, Crypto)
