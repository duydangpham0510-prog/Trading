from django.db import models  # pyright: ignore[reportMissingImports]


class FunctionGroup(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)

    def __str__(self) -> str:
        return self.name


class FunctionDefinition(models.Model):
    group = models.ForeignKey(FunctionGroup, on_delete=models.CASCADE, related_name="functions")
    function_id = models.CharField(max_length=120, unique=True)
    label = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    runner_path = models.CharField(max_length=255)
    param_schema = models.JSONField(default=dict)
    output_type = models.CharField(max_length=50, default="table")
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.label


class ExecutionHistory(models.Model):
    function = models.ForeignKey(FunctionDefinition, on_delete=models.CASCADE, related_name="history")
    params = models.JSONField(default=dict)
    status = models.CharField(max_length=30, default="success")
    result_preview = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class UserPreset(models.Model):
    name = models.CharField(max_length=120)
    function = models.ForeignKey(FunctionDefinition, on_delete=models.CASCADE, related_name="presets")
    params = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class ExecutionResult(models.Model):
    function = models.ForeignKey(FunctionDefinition, on_delete=models.CASCADE, related_name="results")
    params = models.JSONField(default=dict)
    status = models.CharField(max_length=30, default="success")
    result_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


# ============== STOCK DATA MODELS (Database-First Architecture) ==============

# VN30 Symbols (hardcoded for quick lookup)
VN30_SYMBOLS = {
    'ACB', 'BCM', 'BID', 'BVH', 'CTG', 'FPT', 'GAS', 'GVR', 'HDB', 'HPG',
    'MBB', 'MSN', 'MWG', 'NVL', 'PDR', 'PHB', 'PLX', 'PNJ', 'POW', 'SAB',
    'SSI', 'STB', 'TCB', 'TPB', 'VCB', 'VCB', 'VHM', 'VIB', 'VIC', 'VJC',
    'VNM', 'VPB', 'VRE'
}

# Industry mapping (simplified)
INDUSTRY_MAP = {
    'VCB': 'Banking', 'BID': 'Banking', 'CTG': 'Banking', 'TCB': 'Banking',
    'ACB': 'Banking', 'VPB': 'Banking', 'MBB': 'Banking', 'STB': 'Banking',
    'HDB': 'Banking', 'LPB': 'Banking', 'OCB': 'Banking', 'VIB': 'Banking',
    'SHB': 'Banking', 'EIB': 'Banking', 'MSB': 'Banking', 'TPB': 'Banking',
    'FPT': 'Technology', 'SSI': 'Securities', 'VND': 'Securities',
    'HCM': 'Securities', 'VCI': 'Securities', 'CTS': 'Securities',
    'MBS': 'Securities', 'SHS': 'Securities', 'BSR': 'Oil & Gas',
    'PLX': 'Oil & Gas', 'POW': 'Oil & Gas', 'GAS': 'Oil & Gas',
    'VNM': 'FMCG', 'MWG': 'Retail', 'PNJ': 'Retail', 'DGW': 'Retail',
    'PET': 'Retail', 'SBT': 'FMCG', 'VHC': 'FMCG', 'ANV': 'FMCG',
    'VHM': 'Real Estate', 'NVL': 'Real Estate', 'KDH': 'Real Estate',
    'DIG': 'Real Estate', 'HDG': 'Real Estate', 'DXG': 'Real Estate',
    'Nam Long': 'Real Estate', 'PDR': 'Real Estate', 'C21': 'Real Estate',
    'HPG': 'Steel', 'HSG': 'Steel', 'NKG': 'Steel', ' SMC': 'Steel',
    'VIC': 'Conglomerate', 'VRE': 'Real Estate', 'MSN': 'Conglomerate',
    'GVR': 'Rubber', 'DRC': 'Tire', 'CMG': 'Technology', 'ELC': 'Technology',
}


class StockData(models.Model):
    """Lưu trữ dữ liệu kỹ thuật của mã cổ phiếu"""
    symbol = models.CharField(max_length=10, unique=True, db_index=True)
    company_name = models.CharField(max_length=200, blank=True, default="")
    industry = models.CharField(max_length=50, blank=True, default="")
    market_group = models.CharField(max_length=20, blank=True, default="")  # VN30, MIDCAP, SMALL

    # Price
    price = models.FloatField(default=0)
    change_percent = models.FloatField(default=0)
    volume = models.BigIntegerField(default=0)
    avg_volume_value = models.FloatField(default=0)  # Tỷ VND

    # Technical Indicators
    rsi = models.FloatField(default=50)
    adx = models.FloatField(default=25)
    plus_di = models.FloatField(default=0)
    minus_di = models.FloatField(default=0)
    cmf = models.FloatField(default=0)
    atr = models.FloatField(default=0)

    # Moving Averages
    sma_10 = models.FloatField(default=0)
    sma_20 = models.FloatField(default=0)
    sma_50 = models.FloatField(default=0)

    # Bollinger Bands
    bb_upper = models.FloatField(default=0)
    bb_middle = models.FloatField(default=0)
    bb_lower = models.FloatField(default=0)
    bb_percent = models.FloatField(default=50)

    # MACD
    macd = models.FloatField(default=0)
    macd_signal = models.FloatField(default=0)

    # Volume
    volume_ratio = models.FloatField(default=1.0)

    # Advanced TA
    mfi = models.FloatField(default=50)  # Money Flow Index
    vwap = models.FloatField(default=0)
    vwap_status = models.CharField(max_length=20, default="neutral")
    ichimoku_tenkan = models.FloatField(default=0)
    ichimoku_kijun = models.FloatField(default=0)
    ichimoku_status = models.CharField(max_length=20, default="neutral")
    supertrend = models.FloatField(default=0)
    supertrend_signal = models.CharField(max_length=20, default="neutral")

    # Fundamental (optional, may be None)
    pe = models.FloatField(null=True, blank=True)
    pb = models.FloatField(null=True, blank=True)
    roe = models.FloatField(null=True, blank=True)
    f_score = models.IntegerField(default=0)
    profit_growth = models.FloatField(null=True, blank=True)  # Tăng trưởng LN quý (%)
    profit_growth_note = models.CharField(max_length=20, default="N/A")  # YoY, QoQ_adj, TTM, NEW_LISTING
    is_new_listing = models.BooleanField(default=False)  # Cổ phiếu mới (< 2 quý)
    
    # Earning Guidance (Kế hoạch lợi nhuận năm)
    annual_profit_plan = models.FloatField(null=True, blank=True)  # Kế hoạch LN năm (tỷ VND)
    current_ytd_profit = models.FloatField(null=True, blank=True)  # LN YTD hiện tại (tỷ VND)
    profit_plan_completion = models.FloatField(null=True, blank=True)  # Tỷ lệ hoàn thành kế hoạch (%)

    # Meta
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stock_data"
        ordering = ["-avg_volume_value"]

    def __str__(self):
        return f"{self.symbol}: {self.price}"

    def get_market_group(self):
        """Determine market group based on symbol"""
        if self.symbol in VN30_SYMBOLS:
            return "VN30"
        elif self.avg_volume_value >= 5:  # > 5 tỷ/ngày
            return "MIDCAP"
        else:
            return "SMALL"

    def get_industry(self):
        """Get industry from mapping"""
        return INDUSTRY_MAP.get(self.symbol, "Other")


class StockAnalysis(models.Model):
    """Lưu trữ kết quả phân tích AI của mã cổ phiếu"""
    symbol = models.OneToOneField(StockData, on_delete=models.CASCADE, related_name="analysis")

    # Scores
    master_score = models.IntegerField(default=50)
    technical_score = models.IntegerField(default=50)
    fundamental_score = models.IntegerField(default=50)

    # Signal
    signal = models.CharField(max_length=20, default="WAIT")  # BUY/SELL/WAIT/ACCUMULATE

    # Trading Levels
    entry_price = models.FloatField(default=0)
    stop_loss = models.FloatField(default=0)
    trailing_sl = models.FloatField(default=0)  # Trailing Stop = Price * 0.95
    take_profit = models.FloatField(default=0)
    risk_reward_ratio = models.FloatField(default=0)
    rr_quality = models.CharField(max_length=50, blank=True, default="")
    rr_quality_detail = models.CharField(max_length=100, blank=True, default="")
    rr_warning = models.CharField(max_length=100, blank=True, default="")

    # Status Flags
    is_vetoed = models.BooleanField(default=False)
    veto_reason = models.CharField(max_length=200, blank=True, default="")
    is_fast_pick = models.BooleanField(default=False)
    is_short_term_qualified = models.BooleanField(default=False)
    is_slow_mode = models.BooleanField(default=False)
    is_high_risk = models.BooleanField(default=False)
    has_inverted_sl = models.BooleanField(default=False)
    is_inverted_risk = models.BooleanField(default=False, null=True, blank=True)
    
    # NEW: Separated Risk Assessment
    is_market_high_risk = models.BooleanField(default=False)  # VNIndex RSI > 80
    stock_risk_level = models.CharField(max_length=20, default="Medium")  # Very Low/Low/Medium/High
    stock_risk_reason = models.CharField(max_length=200, blank=True, default="")
    
    # Score Breakdown
    base_master_score = models.IntegerField(default=50)  # Before market weight adjustment
    market_weight = models.IntegerField(default=0)  # Adjustment based on market RSI
    
    # Entry Quality
    is_safe_entry = models.BooleanField(default=False)  # Within [-2%, +2%] of SMA20
    has_high_resistance = models.BooleanField(default=False)  # TP above Bollinger Upper Band
    
    # Volume
    avg_volume_value = models.FloatField(default=0)  # 20-day avg volume in Billions VND
    trend_factor = models.FloatField(default=0.6)  # ADX-based factor (0.4-0.8)
    
    # Smart Money & Industry
    foreign_buy_streak = models.IntegerField(default=0)  # Số phiên khối ngoại mua ròng liên tiếp
    foreign_bonus = models.IntegerField(default=0)  # Điểm cộng từ Smart Money
    industry_performance = models.FloatField(default=0)  # % chênh lệch vs ngành
    is_industry_leader = models.BooleanField(default=True)  # True = mạnh hơn ngành
    
    # Real R:R
    hard_risk_pct = models.FloatField(default=0)  # % rủi ro thực (Entry - SMA50)
    support_price = models.FloatField(default=0)  # Giá hỗ trợ cứng (SMA50)
    
    # Early Exit Sensor & Money Management
    pe_industry_avg = models.FloatField(default=0)  # P/E trung bình ngành
    early_exit_trigger_pct = models.FloatField(default=2.0)  # Ngưỡng kích hoạt trailing (mặc định 2%)
    early_exit_drop_pct = models.FloatField(default=0.7)  # Sụt giảm tối đa từ đỉnh (mặc định 0.7%)
    optimal_position_size = models.FloatField(default=0)  # Số tiền giải ngân tối ưu
    account_balance = models.FloatField(default=100000000)  # Số dư tài khoản mặc định (100M)
    risk_tolerance_pct = models.FloatField(default=2.0)  # % rủi ro chấp nhận (mặc định 2%)
    
    # Holding
    estimated_days_to_target = models.FloatField(default=0)
    timeframe_label = models.CharField(max_length=30, default="")
    timeframe_color = models.CharField(max_length=20, default="")
    expected_profit_per_day = models.FloatField(default=0)
    upside_per_day = models.FloatField(default=0)
    target_yield_pct = models.FloatField(default=0)  # NEW: Lợi nhuận kỳ vọng (TP - Entry) / Entry * 100

    # Criteria
    criteria_met = models.IntegerField(default=0)
    criteria_list = models.JSONField(default=list)
    recommendation_label = models.CharField(max_length=50, default="")  # e.g. "BUY (GOLD)"

    # Fair Value (v10.3 - Dynamic Sector Valuation)
    fv_daily = models.FloatField(default=0)  # (VWAP * 0.4) + (SMA20 * 0.6)
    fv_weekly = models.FloatField(default=0)  # Intrinsic-based formula
    valuation_status = models.CharField(max_length=20, default="N/A")  # "Rẻ" or "Đắt"
    intrinsic_value = models.FloatField(default=0)  # Base intrinsic value
    sector_median_pe = models.FloatField(default=0)  # Dynamic sector median P/E
    valuation_source = models.CharField(max_length=10, default="static")  # "dynamic" or "static"
    valuation_cap_applied = models.BooleanField(default=False)  # Wealth Guard Cap was applied

    # Trend
    trend = models.CharField(max_length=20, default="SIDEWAYS")
    breakout_status = models.CharField(max_length=50, default="")

    # Meta
    market_rsi = models.FloatField(default=50)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stock_analysis"
        ordering = ["-risk_reward_ratio", "-master_score"]

    def __str__(self):
        return f"{self.symbol}: {self.signal} (Score: {self.master_score})"


class SyncStatus(models.Model):
    """Theo dõi trạng thái đồng bộ"""
    STATUS_CHOICES = [
        ("idle", "Idle"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="idle")
    total_symbols = models.IntegerField(default=0)
    processed_symbols = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "sync_status"

    @property
    def progress_percent(self):
        if self.total_symbols == 0:
            return 0
        return int(self.processed_symbols / self.total_symbols * 100)

    @property
    def is_running(self):
        return self.status == "running"


# ============== QUARTERLY FINANCIAL DATA ==============

class IndustryValuation(models.Model):
    """Lưu trữ P/E và P/B Median theo ngành từ dữ liệu thị trường thực tế"""
    name = models.CharField(max_length=50, unique=True)  # VD: "Banking", "Technology"
    sector_code = models.CharField(max_length=20, blank=True, default="")  # ICB sector code
    median_pe = models.FloatField(default=0)  # P/E median của ngành
    median_pb = models.FloatField(default=0)  # P/B median của ngành
    median_de = models.FloatField(default=0)  # D/E median của ngành (thêm mới)
    stock_count = models.IntegerField(default=0)  # Số mã trong ngành
    market_cap_avg = models.FloatField(default=0)  # Vốn hóa TB (tỷ VND)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "industry_valuation"
        verbose_name_plural = "Industry Valuations"
        ordering = ['name']

    def __str__(self):
        return f"{self.name}: PE={self.median_pe:.1f}, PB={self.median_pb:.1f} ({self.stock_count} stocks)"


class QuarterlyFinancial(models.Model):
    """Lưu trữ dữ liệu tài chính theo quý cho VETO chính xác"""
    symbol = models.CharField(max_length=10, db_index=True)
    quarter = models.CharField(max_length=10)  # VD: "2024-Q3"
    quarter_date = models.DateField()  # Ngày cuối quý
    
    # Chỉ số tài chính
    roe = models.FloatField(null=True, blank=True)
    roa = models.FloatField(null=True, blank=True)
    pe = models.FloatField(null=True, blank=True)
    pb = models.FloatField(null=True, blank=True)
    
    # F-Score components
    f_score_roc = models.IntegerField(default=0)  # Return on Change
    f_score_roa = models.IntegerField(default=0)  # ROA > 0
    f_score_accrual = models.IntegerField(default=0)  # Accrual nhỏ
    
    # Tổng F-Score (0-9)
    f_score = models.IntegerField(default=0)
    
    # Revenue & Profit
    revenue = models.BigIntegerField(null=True, blank=True)  # Doanh thu
    net_profit = models.BigIntegerField(null=True, blank=True)  # Lợi nhuận ròng
    profit_growth = models.FloatField(null=True, blank=True)  # Tăng trưởng lợi nhuận QoQ
    
    # Quality metrics
    is_vetoed = models.BooleanField(default=False)
    veto_reason = models.CharField(max_length=200, blank=True, default="")
    
    # VCI data (source)
    vci_data = models.JSONField(default=dict, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = "quarterly_financial"
        unique_together = ['symbol', 'quarter']
        ordering = ['-quarter_date']
    
    def __str__(self):
        return f"{self.symbol} {self.quarter} (F={self.f_score}, ROE={self.roe})"
    
    def calculate_f_score(self):
        """Tính F-Score từ các thành phần"""
        self.f_score = self.f_score_roc + self.f_score_roa + self.f_score_accrual
        return self.f_score
    
    def check_veto(self):
        """Kiểm tra điều kiện VETO dựa trên dữ liệu quý"""
        self.is_vetoed = False
        self.veto_reason = ""
        
        if self.roe is not None and self.roe < 15:
            self.is_vetoed = True
            self.veto_reason = "ROE < 15"
        elif self.f_score < 5:
            self.is_vetoed = True
            self.veto_reason = f"F-Score < 5 ({self.f_score})"
        
        return self.is_vetoed
    
    def get_effective_roe(self, on_date):
        """Lấy ROE hiệu quả cho ngày cụ thể (nếu quý chưa công bố thì dùng quý trước)"""
        if self.quarter_date <= on_date:
            return self.roe
        return None
