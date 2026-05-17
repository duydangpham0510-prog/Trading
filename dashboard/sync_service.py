"""
Sync Engine v9 - Database-First Architecture (FULL SYNC)
- Uses vnstock_data for Fundamental data (like single-stock analyzer)
- Adds VWAP, Ichimoku, SuperTrend, MFI indicators
- Fixes Change% calculation
- Adds F-Score
- Applies consistent veto rules across all stocks
"""
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from time import sleep
from typing import List, Optional, Dict, Any
import pandas as pd

from django.utils import timezone
from dashboard.models import StockData, StockAnalysis, SyncStatus, IndustryValuation, VN30_SYMBOLS


# ============== INDUSTRY CONFIG (SHARED - Fallback) ==============
# Dùng chung cho cả Live scan và Backtest (chỉ là fallback khi không có Dynamic data)
INDUSTRY_CONFIG = {
    'Banking': {'type': 'PB', 'target': 1.65},
    'Real Estate': {'type': 'PB', 'target': 1.8},
    'Securities': {'type': 'PB', 'target': 2.0},
    'Technology': {'type': 'PE', 'target': 18.0},
    'Retail': {'type': 'PE', 'target': 15.0},
    'FMCG': {'type': 'PE', 'target': 14.0},
    'Oil & Gas': {'type': 'PE', 'target': 9.0},
    'Steel': {'type': 'PE', 'target': 8.5},
    'Rubber': {'type': 'PE', 'target': 10.0},
    'Conglomerate': {'type': 'PE', 'target': 10.0},
    'Default': {'type': 'PE', 'target': 11.0}
}

# Wealth Guard Cap multiplier
WEALTH_GUARD_CAP = 1.25  # Không cho phép P/E vượt quá 25% so với ngưỡng tĩnh


# ============== DYNAMIC SECTOR VALUATION ==============

def sync_sector_benchmarks() -> Dict[str, Any]:
    """
    Đồng bộ P/E và P/B Median theo ngành từ Screener API.
    Sử dụng Median thay vì Mean để loại bỏ outliers.
    
    Returns:
        Dict với thông tin sync sector
    """
    from dashboard.models import IndustryValuation
    import traceback
    
    result = {
        "success": False,
        "sectors_synced": 0,
        "errors": [],
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        print("[Sector Sync] Bắt đầu sync sector benchmarks...")
        
        # Import vnstock_data
        try:
            from vnstock_data import Insights
            ins = Insights()
        except ImportError:
            result["errors"].append("vnstock_data not installed")
            print("[Sector Sync] ❌ vnstock_data not installed")
            return result
        
        # Lấy dữ liệu screener
        try:
            print("[Sector Sync] Đang lấy dữ liệu screener...")
            df_screener = ins.screener().filter()
            
            if df_screener is None or len(df_screener) == 0:
                result["errors"].append("Empty screener data")
                return result
                
        except Exception as e:
            result["errors"].append(f"Screener API error: {str(e)}")
            print(f"[Sector Sync] ❌ Screener API error: {e}")
            return result
        
        # Chuẩn hóa columns (screener có: pe, pb, market_cap, vi_sector hoặc industry_en)
        df = df_screener.copy()
        
        # Rename columns nếu cần
        if 'pe' in df.columns:
            df = df.rename(columns={'pe': 'ttm_pe'})
        if 'pb' in df.columns:
            df = df.rename(columns={'pb': 'ttm_pb'})
        
        # Kiểm tra columns
        print(f"[Sector Sync] Columns: {df.columns.tolist()[:10]}...")
        
        # Filter: chỉ lấy mã có vốn hóa > 100 tỷ
        df = df[df['market_cap'].notna() & (df['market_cap'] > 100)]
        
        # Filter P/E hợp lệ (> 0 và < 1000 để loại outliers)
        df_valid_pe = df[df['ttm_pe'].notna() & (df['ttm_pe'] > 0) & (df['ttm_pe'] < 1000)]
        
        # Filter P/B hợp lệ (> 0 và < 50 để loại outliers)
        df_valid_pb = df[df['ttm_pb'].notna() & (df['ttm_pb'] > 0) & (df['ttm_pb'] < 50)]
        
        print(f"[Sector Sync] Tổng cổ phiếu: {len(df)}, Hợp lệ: {len(df_valid_pe)}")
        
        # Xác định column ngành (ưu tiên vi_sector, fallback sang industry_en)
        sector_col = 'vi_sector' if 'vi_sector' in df.columns else 'industry_en'
        
        if sector_col not in df.columns:
            result["errors"].append(f"No sector column found. Available: {df.columns.tolist()}")
            return result
        
        # Nhóm theo sector và tính Median bằng pandas (vectorized)
        sector_stats = df_valid_pe.groupby(sector_col).agg(
            median_pe=('ttm_pe', 'median'),
            stock_count_pe=('symbol', 'count'),
            market_cap_avg=('market_cap', 'mean')
        ).reset_index()
        
        # Tính median P/B theo sector
        sector_pb_stats = df_valid_pb.groupby(sector_col).agg(
            median_pb=('ttm_pb', 'median'),
            stock_count_pb=('symbol', 'count')
        ).reset_index()
        
        # Merge P/E và P/B
        sector_stats = sector_stats.merge(sector_pb_stats, on=sector_col, how='outer')
        
        # Lấy stock_count = min của PE và PB count
        sector_stats['stock_count'] = sector_stats[['stock_count_pe', 'stock_count_pb']].min(axis=1)
        
        # Rename sector column
        sector_stats = sector_stats.rename(columns={sector_col: 'sector_name'})
        
        # Fill NaN values
        sector_stats = sector_stats.fillna(0)
        
        # Map sector name sang industry name
        SECTOR_NAME_MAP = {
            'Ngân hàng': 'Banking',
            'Bảo hiểm': 'Insurance',
            'Chứng khoán': 'Securities',
            'Bất động sản': 'Real Estate',
            'Công nghệ': 'Technology',
            'Bán lẻ': 'Retail',
            'Tiêu dùng': 'FMCG',
            'Dầu khí': 'Oil & Gas',
            'Điện': 'Power & Energy',
            'Xây dựng': 'Construction',
            'Công nghiệp': 'Industrial',
            'Vận tải': 'Transportation',
            'Y tế': 'Healthcare',
            'Viễn thông': 'Telecommunications',
            'Tiện ích': 'Utilities',
            'Truyền thông': 'Media',
            'Du lịch': 'Travel',
            'Thép': 'Steel',
            'Hóa chất': 'Chemicals',
            'Nông nghiệp': 'Agriculture',
            'Cao su': 'Rubber',
            'Ô tô': 'Automobiles',
            'Tập đoàn': 'Conglomerate',
            'Tài nguyên': 'Basic Resources',
            'Thực phẩm': 'Food',
        }
        
        # Sync vào database
        synced_count = 0
        for _, row in sector_stats.iterrows():
            sector_name = str(row['sector_name']) if pd.notna(row['sector_name']) else 'Unknown'
            industry_name = SECTOR_NAME_MAP.get(sector_name, sector_name)
            
            # Skip nếu stock_count < 3 (không đủ mẫu)
            if row['stock_count'] < 3:
                continue
            
            obj, created = IndustryValuation.objects.update_or_create(
                name=industry_name,
                defaults={
                    'sector_code': sector_name,
                    'median_pe': round(row['median_pe'], 2),
                    'median_pb': round(row['median_pb'], 2),
                    'stock_count': int(row['stock_count']),
                    'market_cap_avg': round(row['market_cap_avg'], 2),
                    'is_active': True
                }
            )
            synced_count += 1
        
        result["success"] = True
        result["sectors_synced"] = synced_count
        print(f"[Sector Sync] ✅ Đã sync {synced_count} sectors thành công!")
        
        # Print sample
        for _, row in sector_stats.head(5).iterrows():
            print(f"  - {row['sector_name']}: PE={row['median_pe']:.1f}, PB={row['median_pb']:.1f}, Count={row['stock_count']}")
        
    except Exception as e:
        result["errors"].append(str(e))
        print(f"[Sector Sync] ❌ Lỗi: {e}")
        traceback.print_exc()
    
    return result


def get_target_valuation(industry_name: str) -> Dict:
    """
    Lấy P/E và P/B target cho một ngành.
    
    Priority:
    1. Dynamic Median từ IndustryValuation (database)
    2. Fallback sang INDUSTRY_CONFIG (static)
    3. Wealth Guard Cap: Final = min(Dynamic, Static * 1.25)
    
    Returns:
        Dict với 'type' (PE/PB), 'target' (float), 'source' (dynamic/static)
    """
    # Tìm industry trong database
    try:
        iv = IndustryValuation.objects.filter(name=industry_name, is_active=True).first()
        
        if iv and iv.median_pe > 0:
            # Lấy static config để apply cap
            static_config = INDUSTRY_CONFIG.get(industry_name, INDUSTRY_CONFIG['Default'])
            
            # Determine valuation type
            val_type = static_config.get('type', 'PE')
            static_target = static_config.get('target', 11.0)
            
            if val_type == 'PB':
                # P/B: Apply Wealth Guard Cap
                final_target = min(iv.median_pb, static_target * WEALTH_GUARD_CAP)
                return {
                    'type': 'PB',
                    'target': round(final_target, 2),
                    'dynamic': round(iv.median_pb, 2),
                    'static': static_target,
                    'source': 'dynamic',
                    'cap_applied': final_target != iv.median_pb
                }
            else:
                # P/E: Apply Wealth Guard Cap
                final_target = min(iv.median_pe, static_target * WEALTH_GUARD_CAP)
                return {
                    'type': 'PE',
                    'target': round(final_target, 2),
                    'dynamic': round(iv.median_pe, 2),
                    'static': static_target,
                    'source': 'dynamic',
                    'cap_applied': final_target != iv.median_pe
                }
    except Exception:
        pass
    
    # Fallback: Sử dụng INDUSTRY_CONFIG
    static_config = INDUSTRY_CONFIG.get(industry_name, INDUSTRY_CONFIG['Default'])
    return {
        'type': static_config.get('type', 'PE'),
        'target': static_config.get('target', 11.0),
        'dynamic': 0.0,
        'static': static_config.get('target', 11.0),
        'source': 'static',
        'cap_applied': False
    }


# ============== CONSTANTS ==============
MAX_WORKERS = 8
UNIVERSE_SIZE = 100
MIN_LIQUIDITY_BILLION = 10  # Giảm từ 15 xuống 10 tỷ để đảm bảo đủ mã
MIN_PRICE = 10000


def get_market_rsi() -> float:
    """Lấy RSI của VNIndex"""
    try:
        from vnstock import Quote
        q = Quote(symbol="VNINDEX", source="kbs")
        df = q.history(
            start=(datetime.now() - pd.Timedelta(days=60)).strftime("%Y-%m-%d"),
            end=datetime.now().strftime("%Y-%m-%d"),
            interval="1D"
        )
        if df is not None and len(df) >= 15:
            close = df['close']
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            return float(rsi.iloc[-1])
    except:
        pass
    return 50.0


def get_company_name(symbol: str) -> str:
    """Lấy tên công ty từ vnstock"""
    try:
        from vnstock import Company
        company = Company(symbol=symbol, source="vci")
        info = company.overview()
        if info is not None and not info.empty:
            if 'company_name' in info.columns:
                return str(info['company_name'].iloc[0])
            elif 'name' in info.columns:
                return str(info['name'].iloc[0])
    except:
        pass
    return symbol


def get_fundamental_data(symbol: str, fast_mode: bool = False) -> Dict[str, Any]:
    """
    Lấy dữ liệu cơ bản từ vnstock_data (Unified API) hoặc vnstock fallback
    fast_mode: True = chỉ lấy ratio (nhanh), False = lấy đầy đủ (chậm hơn)
    Returns: {roe, pe, pb, f_score, f_score_grade, profit_growth, profit_growth_note, is_new_listing}
    """
    result = {
        "roe": None,
        "pe": None,
        "pb": None,
        "pe_industry_avg": None,  # P/E trung bình ngành
        "f_score": 0,
        "f_score_grade": "N/A",
        "profit_growth": None,  # Tăng trưởng LN (%)
        "profit_growth_note": "N/A",  # Phương pháp tính: YoY, QoQ_adj, TTM, NEW_LISTING
        "is_new_listing": False,  # Cổ phiếu mới (< 2 quý)
        "foreign_buy_streak": 0,
        "industry_performance": 0,
        "is_industry_leader": True,
    }

    def safe_float(val):
        """Convert value to float safely"""
        if val is None or pd.isna(val):
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    # Try vnstock_data first (Silver+)
    try:
        from vnstock_data import Fundamental
        import warnings as w
        w.filterwarnings('ignore')

        fun = Fundamental()

        # Get financial ratios - try year first, then quarter
        ratios = None
        for period in ["year", "quarter"]:
            try:
                ratios = fun.equity(symbol).ratio(period=period)
                if ratios is not None and len(ratios) > 0:
                    break
            except:
                continue

        if ratios is not None and len(ratios) > 0:
            # IMPORTANT: Index 0 = newest data, Index -1 = oldest data
            # Get the latest row (index 0)
            if hasattr(ratios, 'iloc'):
                latest = ratios.iloc[0]  # Use index 0 for newest data
            else:
                latest = ratios

            # Try multiple possible column names for PE
            for col_name in ['pe', 'PE', 'P/E', 'price_to_earnings', 'pe_ratio']:
                if col_name in ratios.columns:
                    val = safe_float(latest.get(col_name))
                    if val is not None and 0 < val < 1000:
                        result['pe'] = val
                        break

            # Try multiple possible column names for PB
            for col_name in ['pb', 'PB', 'P/B', 'price_to_book', 'pb_ratio', 'book_value_per_share']:
                if col_name in ratios.columns:
                    val = safe_float(latest.get(col_name))
                    if val is not None and 0 < val < 100:
                        # book_value_per_share might need different handling
                        if col_name == 'book_value_per_share':
                            continue  # Skip, we'll calculate PB differently
                        result['pb'] = val
                        break

            # Try to find ROE or calculate from available data
            for col_name in ['roe', 'ROE', 'return_on_equity', 'roe_ratio']:
                if col_name in ratios.columns:
                    val = safe_float(latest.get(col_name))
                    if val is not None:
                        # ROE might be in decimal (0.15) or percentage (15)
                        if abs(val) < 1:  # Likely decimal form
                            val *= 100
                        result['roe'] = round(val, 2)
                        break

            # Calculate ROE from PE/PB if not found
            if result['roe'] is None and result['pe'] and result['pb'] and result['pe'] > 0:
                result['roe'] = round((result['pb'] / result['pe']) * 100, 2)

            # Fast mode: chỉ tính F-Score đơn giản từ ratio
            if fast_mode:
                # Simplified F-Score từ ratio (chỉ 3 điểm tối đa)
                simple_score = 0
                if result.get('roe') and result['roe'] > 10:
                    simple_score += 1
                if result.get('pe') and 5 < result['pe'] < 25:
                    simple_score += 1
                if result.get('pb') and result['pb'] < 3:
                    simple_score += 1
                result['f_score'] = simple_score * 3  # Scale lên 9
                result['f_score_grade'] = get_f_score_grade(result['f_score'])
            else:
                # Full mode: tính F-Score đầy đủ
                profit_growth_result = calculate_profit_growth(symbol)
                result['profit_growth'] = profit_growth_result.get('profit_growth')
                result['profit_growth_note'] = profit_growth_result.get('profit_growth_note', 'N/A')
                result['is_new_listing'] = profit_growth_result.get('is_new_listing', False)
                result['pe_industry_avg'] = get_industry_pe_average(symbol)
                result['foreign_buy_streak'] = get_foreign_buy_streak(symbol)
                result['industry_performance'] = get_industry_performance(symbol, None)
                result['is_industry_leader'] = result['industry_performance'] >= 0
                result['f_score'] = calculate_f_score(symbol, result)
                result['f_score_grade'] = get_f_score_grade(result['f_score'])

        return result

    except Exception as e:
        pass

    # Fallback: try vnstock
    if result['pe'] is None or result['pb'] is None or result['roe'] is None:
        try:
            from vnstock import Finance
            fin = Finance(symbol=symbol, source="vci")

            # Try to get ratios
            ratios = fin.ratio(period="quarter")
            if ratios is not None and not ratios.empty:
                # Get first row (newest data)
                for col in ratios.columns:
                    col_lower = str(col).lower()

                    # ROE
                    if ('roe' in col_lower or 'return on equity' in col_lower) and result['roe'] is None:
                        val = ratios[col].iloc[0] if hasattr(ratios[col], 'iloc') else ratios[col]
                        val = safe_float(val)
                        if val is not None:
                            if abs(val) < 1:  # Decimal form
                                val *= 100
                            result['roe'] = round(val, 2)

                    # PE
                    if ('pe' in col_lower or 'p/e' in col_lower) and result['pe'] is None:
                        val = ratios[col].iloc[0] if hasattr(ratios[col], 'iloc') else ratios[col]
                        val = safe_float(val)
                        if val is not None and 0 < val < 1000:
                            result['pe'] = val

                    # PB
                    if ('pb' in col_lower or 'p/b' in col_lower or 'book' in col_lower) and result['pb'] is None:
                        val = ratios[col].iloc[0] if hasattr(ratios[col], 'iloc') else ratios[col]
                        val = safe_float(val)
                        if val is not None and 0 < val < 100:
                            result['pb'] = val

        except Exception as e:
            pass

    # Calculate ROE from PE/PB if still missing
    if result['roe'] is None and result['pe'] and result['pb'] and result['pe'] > 0:
        result['roe'] = round((result['pb'] / result['pe']) * 100, 2)

    # Simplified F-Score if still 0
    if result['f_score'] == 0:
        simple_score = 0
        if result.get('roe') and result['roe'] > 15:
            simple_score += 3
        if result.get('pe') and 5 < result['pe'] < 25:
            simple_score += 3
        if result.get('pb') and result['pb'] < 3:
            simple_score += 3
        result['f_score'] = simple_score
        result['f_score_grade'] = get_f_score_grade(result['f_score'])

    return result


def get_industry_pe_average(symbol: str) -> Optional[float]:
    """
    Lấy P/E trung bình ngành của mã cổ phiếu
    
    Priority:
    1. Từ bảng IndustryValuation (đã được lọc P/E > 0)
    2. Fallback: P/E thị trường VNINDEX
    """
    try:
        # Lấy thông tin ngành của mã từ StockData
        from .models import StockData
        try:
            stock = StockData.objects.get(symbol=symbol.upper())
            industry = stock.industry
        except:
            industry = None
        
        # Normalize industry name
        if industry:
            industry_key = next((k for k in INDUSTRY_CONFIG if k.lower() in industry.lower()), None)
            
            if industry_key:
                # Lấy từ IndustryValuation (đã filtered P/E > 0)
                try:
                    iv = IndustryValuation.objects.filter(name=industry_key, is_active=True).first()
                    if iv and iv.median_pe > 0:
                        return round(iv.median_pe, 2)
                except:
                    pass
        
        # Fallback: P/E thị trường VNINDEX
        try:
            from vnstock_data import Market
            mkt = Market()
            pe_data = mkt.pe(duration="1Y")
            if pe_data is not None and len(pe_data) > 0:
                for col in pe_data.columns:
                    if 'pe' in col.lower():
                        return round(float(pe_data[col].iloc[-1]), 2)
        except:
            pass
        
        # Final fallback: sử dụng INDUSTRY_CONFIG
        if industry:
            industry_key = next((k for k in INDUSTRY_CONFIG if k.lower() in industry.lower()), 'Default')
            return INDUSTRY_CONFIG.get(industry_key, INDUSTRY_CONFIG['Default']).get('target')
        
        return INDUSTRY_CONFIG['Default']['target']
        
    except Exception:
        return None


def calculate_optimal_position(
    account_balance: float,
    risk_tolerance: float,
    entry_price: float,
    support_price: float
) -> float:
    """
    Tính số tiền giải ngân tối ưu dựa trên công thức:
    Vốn giải ngân = (Số dư × % Rủi ro) / (Entry - SMA50)
    
    Args:
        account_balance: Số dư tài khoản (VND)
        risk_tolerance: % rủi ro chấp nhận (ví dụ: 2.0 = 2%)
        entry_price: Giá mua (VND)
        support_price: Giá hỗ trợ cứng SMA50 (VND)
    
    Returns:
        Số tiền nên giải ngân (VND)
    """
    try:
        if entry_price <= 0 or support_price <= 0 or entry_price <= support_price:
            return 0
        
        # Risk amount = Số dư × % rủi ro
        risk_amount = account_balance * (risk_tolerance / 100)
        
        # Khoảng cách từ Entry đến Support (Hard Risk)
        hard_risk_per_share = entry_price - support_price
        
        # Số cổ phiếu tối đa = Risk Amount / Hard Risk per share
        shares = risk_amount / hard_risk_per_share
        
        # Vốn giải ngân = Số cổ phiếu × Giá mua
        position_value = shares * entry_price
        
        return round(position_value, -3)  # Làm tròn đến 1000 VND gần nhất
    except Exception as e:
        return 0


def get_foreign_buy_streak(symbol: str, lookback: int = 5) -> int:
    """
    Lấy số phiên liên tiếp khối ngoại mua ròng từ vnstock_data
    Returns: Số phiên mua ròng liên tiếp (0 = không có)
    """
    try:
        from vnstock_data import TopStock
        insights = TopStock()
        
        # Lấy dữ liệu foreign buy gần đây
        foreign_buy = insights.foreign_buy(limit=lookback)
        
        # Lấy dữ liệu foreign sell gần đây
        foreign_sell = insights.foreign_sell(limit=lookback)
        
        if foreign_buy is None or foreign_sell is None:
            return 0
        
        # Tạo dict để tracking
        buy_dates = set()
        sell_dates = set()
        
        # Parse foreign buy
        if len(foreign_buy) > 0:
            for idx, row in foreign_buy.iterrows():
                sym = str(row.get('symbol', '')).upper()
                date = str(row.get('date', ''))
                if sym == symbol.upper():
                    buy_dates.add(date)
        
        # Parse foreign sell
        if len(foreign_sell) > 0:
            for idx, row in foreign_sell.iterrows():
                sym = str(row.get('symbol', '')).upper()
                date = str(row.get('date', ''))
                if sym == symbol.upper():
                    sell_dates.add(date)
        
        # Đếm streak: nếu ngày trong buy nhưng không trong sell = mua ròng
        all_dates = sorted(list(buy_dates | sell_dates), reverse=True)
        
        streak = 0
        for date in all_dates:
            if date in buy_dates and date not in sell_dates:
                streak += 1
            else:
                break
        
        return streak
    except Exception as e:
        return 0


def get_industry_performance(symbol: str, df: pd.DataFrame, lookback: int = 5) -> float:
    """
    So sánh hiệu suất mã với trung bình ngành
    Returns: % chênh lệch so với ngành (dương = mạnh hơn ngành)
    """
    try:
        # Tính % tăng của mã trong N phiên
        if df is None or len(df) < lookback:
            return 0
        
        stock_return = 0
        if 'close' in df.columns and len(df) >= lookback:
            current_price = float(df['close'].iloc[-1])
            past_price = float(df['close'].iloc[-lookback])
            if past_price > 0:
                stock_return = ((current_price - past_price) / past_price) * 100
        
        # Lấy danh sách cổ phiếu cùng ngành từ vnstock
        try:
            from vnstock_data import Listing
            lst = Listing(source="kbs")
            
            # Lấy industry của mã (từ stock data)
            from .models import StockData
            try:
                stock = StockData.objects.get(symbol=symbol.upper())
                industry = stock.industry or stock.get_industry()
            except:
                industry = None
            
            if industry:
                # Lấy danh sách top stocks theo ngành (lấy mẫu)
                # So sánh với top gainers
                top = lst.top_gainers()
                
                if top is not None and len(top) > 0:
                    # Tính trung bình % tăng của top stocks
                    industry_return = top['change_percent'].mean() if 'change_percent' in top.columns else 0
                    
                    # Chênh lệch = Stock - Industry
                    return round(stock_return - industry_return, 2)
        except:
            pass
        
        # Fallback: so sánh với VNIndex (thị trường chung)
        return 0  # Không đủ dữ liệu
    except Exception as e:
        return 0


def calculate_profit_growth(symbol: str) -> dict:
    """
    Calculate profit growth với ưu tiên: TTM > YoY > QoQ
    
    Returns dict:
    {
        'profit_growth': float (growth percentage),
        'profit_growth_note': str (method used: 'YoY', 'QoQ', 'TTM', 'NEW_LISTING'),
        'is_new_listing': bool
    }
    
    Priority:
    1. TTM (Trailing Twelve Months) - ổn định nhất
    2. YoY (Year-over-Year) - chính xác nhất
    3. QoQ (Quarter-over-Quarter) với hệ số 0.8 - dự phòng
    4. NEW_LISTING - cổ phiếu mới (< 2 quý dữ liệu)
    """
    result = {
        'profit_growth': None,
        'profit_growth_note': 'N/A',
        'is_new_listing': False
    }
    
    try:
        from vnstock_data import Fundamental
        import warnings as w
        w.filterwarnings('ignore')

        fun = Fundamental()
        income = fun.equity(symbol).income_statement(limit=8)

        if income is None or len(income) == 0:
            return result
        
        # Find net profit column - ưu tiên LN của cổ đông công ty mẹ
        net_profit_col = None
        preferred_cols = [
            'profit_after_tax_for_shareholders_of_parent_company',
            'net_profit_after_tax',
            'profit_before_tax'
        ]
        for col in preferred_cols:
            if col in income.columns:
                net_profit_col = col
                break
        
        # Fallback: tìm bất kỳ cột nào có profit
        if net_profit_col is None:
            for col in income.columns:
                col_lower = str(col).lower()
                if ('net' in col_lower and 'profit' in col_lower) or 'lnst' in col_lower:
                    net_profit_col = col
                    break

        if net_profit_col is None:
            return result
        
        # Đếm số quý có dữ liệu hợp lệ
        valid_quarters = 0
        for idx in income.index:
            val = income.loc[idx, net_profit_col]
            if val is not None and not pd.isna(val) and float(val) > 0:
                valid_quarters += 1
        
        # NEW_LISTING: < 2 quý dữ liệu
        if valid_quarters < 2:
            result['profit_growth'] = 0.001  # Không âm, không None
            result['profit_growth_note'] = 'NEW_LISTING'
            result['is_new_listing'] = True
            return result
        
        # Hàm helper lấy giá trị
        def get_profit(idx):
            val = income.loc[idx, net_profit_col]
            if val is None or pd.isna(val):
                return None
            try:
                v = float(val)
                return v if v > 0 else None
            except:
                return None
        
        latest_idx = income.index[0]
        latest_profit = get_profit(latest_idx)
        
        if latest_profit is None:
            return result
        
        # ========== METHOD 1: TTM (Trailing Twelve Months) ==========
        # Tổng 4 quý gần nhất vs 4 quý trước
        if valid_quarters >= 4:
            ttm_current = 0
            ttm_prev = 0
            for i in range(4):
                if i < len(income.index):
                    val = get_profit(income.index[i])
                    if val is not None:
                        ttm_current += val
            
            for i in range(4, min(8, len(income))):
                val = get_profit(income.index[i])
                if val is not None:
                    ttm_prev += val
            
            if ttm_current > 0 and ttm_prev > 0:
                ttm_growth = ((ttm_current / ttm_prev) - 1) * 100
                result['profit_growth'] = round(ttm_growth, 2)
                result['profit_growth_note'] = 'TTM'
                return result
        
        # ========== METHOD 2: YoY (Year-over-Year) ==========
        # Tìm cùng kỳ năm trước (cách 4 quý)
        if isinstance(latest_idx, str):
            latest_dt = pd.to_datetime(latest_idx)
        else:
            latest_dt = latest_idx
        
        same_quarter_last_year = None
        for i in range(1, min(5, len(income))):
            row_idx = income.index[i]
            if isinstance(row_idx, str):
                row_dt = pd.to_datetime(row_idx)
            else:
                row_dt = row_idx
            
            # Same quarter: cùng tháng trong quý
            if (latest_dt.month - 1) // 3 == (row_dt.month - 1) // 3:
                if latest_dt.year == row_dt.year + 1:
                    same_quarter_last_year = get_profit(row_idx)
                    break
        
        if same_quarter_last_year is not None:
            yoy_growth = ((latest_profit / same_quarter_last_year) - 1) * 100
            result['profit_growth'] = round(yoy_growth, 2)
            result['profit_growth_note'] = 'YoY'
            return result
        
        # ========== METHOD 3: QoQ với hệ số 0.8 ==========
        # Chỉ dùng khi không có YoY
        if valid_quarters >= 2:
            prev_idx = income.index[1]
            prev_profit = get_profit(prev_idx)
            
            if prev_profit is not None and prev_profit > 0:
                qoq_growth = ((latest_profit / prev_profit) - 1) * 100
                # Áp dụng hệ số 0.8 để tránh sai số mùa vụ
                adjusted_growth = qoq_growth * 0.8
                result['profit_growth'] = round(adjusted_growth, 2)
                result['profit_growth_note'] = 'QoQ_adj'
                return result
        
        # Fallback: không tính được
        return result

    except Exception as e:
        pass
    
    return result


def calculate_f_score(symbol: str, fund_data: dict = None) -> int:  # pyright: ignore[reportArgumentType]
    """
    Calculate Piotroski F-Score (0-9)
    fund_data: Optional dict with ROE, PE, PB to use in score calculation
    """
    score = 0

    try:
        from vnstock_data import Fundamental
        import warnings as w
        w.filterwarnings('ignore')

        fun = Fundamental()

        income = fun.equity(symbol).income_statement(limit=8)
        balance = fun.equity(symbol).balance_sheet(limit=8)
        cf = fun.equity(symbol).cash_flow(limit=8)

        if income is None or len(income.columns) < 2:
            return 0

        # Get latest period
        latest_row = income.index[0]
        prev_row = income.index[1] if len(income.index) > 1 else None

        # Helper
        def get_val(df, row, col):
            try:
                if col in df.columns:
                    return df.loc[row, col]
            except:
                pass
            return None

        # 1. ROA > 0
        ni_col = 'net_profit_after_tax' if 'net_profit_after_tax' in income.columns else None
        ta_col = 'total_assets' if 'total_assets' in balance.columns else None
        if ni_col and ta_col:
            ni = get_val(income, latest_row, ni_col)
            ta = get_val(balance, latest_row, ta_col)
            if ni and ta and float(ta) != 0:
                roa = float(ni) / float(ta)
                if roa > 0:
                    score += 1

        # 2. OCF > 0
        ocf_col = None
        for col in cf.columns:
            if 'operating' in col.lower() and 'cash' in col.lower():
                ocf_col = col
                break
        if ocf_col:
            ocf = get_val(cf, latest_row, ocf_col)
            if ocf and float(ocf) > 0:
                score += 1

        # 3. ROA increase YoY
        if ni_col and ta_col:
            ni_prev = get_val(income, prev_row, ni_col) if prev_row else None
            ta_prev = get_val(balance, prev_row, ta_col) if prev_row else None
            if ni and ta and ni_prev and ta_prev and float(ta) != 0 and float(ta_prev) != 0:
                roa_current = float(ni) / float(ta)
                roa_prev = float(ni_prev) / float(ta_prev)
                if roa_current > roa_prev:
                    score += 1

        # 4. CFO > Net Income
        if ocf_col and ni_col:
            ocf_val = get_val(cf, latest_row, ocf_col)
            ni_val = get_val(income, latest_row, ni_col)
            if ocf_val and ni_val and float(ocf_val) > float(ni_val):
                score += 1

        # 5. Leverage decrease
        if ta_col:
            current_assets_col = 'total_current_assets' if 'total_current_assets' in balance.columns else None
            if current_assets_col:
                ca = get_val(balance, latest_row, current_assets_col)
                if ta and ca and float(ta) > 0:
                    de_ratio = float(ta) / float(ca) if float(ca) > 0 else 0
                    if prev_row:
                        ca_prev = get_val(balance, prev_row, current_assets_col)
                        ta_prev = get_val(balance, prev_row, ta_col)
                        if ca_prev and ta_prev and float(ta_prev) > 0:
                            de_ratio_prev = float(ta_prev) / float(ca_prev)
                            if de_ratio < de_ratio_prev:
                                score += 1

        # 6. Current ratio increase
        if current_assets_col and 'total_current_liabilities' in balance.columns:
            cl = get_val(balance, latest_row, 'total_current_liabilities')
            if ca and cl and float(cl) > 0:
                cr = float(ca) / float(cl)
                if prev_row:
                    cl_prev = get_val(balance, prev_row, 'total_current_liabilities')
                    ca_prev = get_val(balance, prev_row, current_assets_col)
                    if ca_prev and cl_prev and float(cl_prev) > 0:
                        cr_prev = float(ca_prev) / float(cl_prev)
                        if cr > cr_prev:
                            score += 1

        # 7-9. Margin/Asset improvements (simplified for speed)
        # Use fund_data if provided
        _roe = fund_data.get('roe', 0) if fund_data else None
        _pe = fund_data.get('pe', 0) if fund_data else None
        _pb = fund_data.get('pb', 0) if fund_data else None
        
        if _roe and _roe > 10:
            score += 1
        if _pe and 5 < _pe < 25:
            score += 1
        if _pb and _pb < 3:
            score += 1

    except:
        pass

    return min(score, 9)


def get_f_score_grade(score: int) -> str:
    """Convert F-Score to grade"""
    if score >= 8:
        return "A"
    elif score >= 6:
        return "B"
    elif score >= 4:
        return "C"
    elif score >= 2:
        return "D"
    else:
        return "F"


# ============== SECTOR-SPECIFIC SCORING FUNCTIONS (V3) ==============

def get_sector_category(industry: str) -> str:
    """
    Classify industry into sector category for scoring purposes.
    Returns: 'banking', 'real_estate', 'manufacturing', 'retail', 'general'
    """
    if not industry:
        return 'general'
    
    industry_lower = industry.lower()
    
    # Banking & Financial
    if any(k in industry_lower for k in ['bank', 'ngân hàng', 'chứng khoán', 'bảo hiểm', 'tín dụng', 'tài chính']):
        return 'banking'
    
    # Real Estate
    if any(k in industry_lower for k in ['bất động sản', 'real estate', 'xây dựng', 'construction']):
        return 'real_estate'
    
    # Manufacturing (Capital Intensive)
    if any(k in industry_lower for k in ['thép', 'steel', 'điện', 'power', 'năng lượng', 'dầu', 'oil', 'gas', 'hóa', 'chem', 'xi măng', 'cement', 'phân bón', 'fertilizer']):
        return 'manufacturing'
    
    # Retail & Consumer
    if any(k in industry_lower for k in ['bán lẻ', 'retail', 'fmcg', 'tiêu dùng', 'consumer', 'thực phẩm', 'food', 'đồ uống', 'beverage', 'dược', 'pharma']):
        return 'retail'
    
    return 'general'


def score_banking_sector(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score banking sector stocks using P/B, NIM, NPL, CASA metrics.
    Banking uses P/B instead of P/E for valuation.
    """
    result = {
        'fund_score': 0,
        'primary_metric': 'P/B',
        'primary_value': raw_data.get('pb'),
        'sector_metrics': {}
    }
    
    pb = raw_data.get('pb')
    roe = raw_data.get('roe')
    pe = raw_data.get('pe')
    
    # P/B scoring (Primary for banks)
    # Good P/B for banks: < 1.5, Great: < 1.0
    if pb:
        if pb < 0.8:
            result['fund_score'] += 25
        elif pb < 1.0:
            result['fund_score'] += 22
        elif pb < 1.5:
            result['fund_score'] += 18
        elif pb < 2.0:
            result['fund_score'] += 12
        else:
            result['fund_score'] += 5
    
    # ROE scoring (banks typically have 15-25% ROE)
    if roe:
        if roe >= 20:
            result['fund_score'] += 25
        elif roe >= 15:
            result['fund_score'] += 20
        elif roe >= 10:
            result['fund_score'] += 12
        elif roe >= 5:
            result['fund_score'] += 6
        else:
            result['fund_score'] += 0
    
    # NIM (Net Interest Margin) - if available
    nim = raw_data.get('nim') or raw_data.get('net_interest_margin')
    if nim:
        result['sector_metrics']['nim'] = nim
        if nim >= 4:
            result['fund_score'] += 15
        elif nim >= 3:
            result['fund_score'] += 10
        elif nim >= 2:
            result['fund_score'] += 5
    
    # NPL (Non-Performing Loans) - if available
    npl = raw_data.get('npl') or raw_data.get('npl_ratio')
    if npl:
        result['sector_metrics']['npl'] = npl
        if npl <= 2:
            result['fund_score'] += 20
        elif npl <= 3:
            result['fund_score'] += 12
        elif npl <= 5:
            result['fund_score'] += 5
        else:
            result['fund_score'] -= 10  # Penalty
    
    # CASA ratio - if available
    casa = raw_data.get('casa') or raw_data.get('casa_ratio')
    if casa:
        result['sector_metrics']['casa'] = casa
        if casa >= 30:
            result['fund_score'] += 10
        elif casa >= 20:
            result['fund_score'] += 5
    
    # Capital adequacy (CAR) - if available
    car = raw_data.get('car') or raw_data.get('capital_adequacy_ratio')
    if car:
        result['sector_metrics']['car'] = car
        if car >= 13:
            result['fund_score'] += 5
    
    # Cap at 100
    result['fund_score'] = min(result['fund_score'], 100)
    
    return result


def score_real_estate_sector(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score real estate sector stocks using D/E, Inventory status, and land bank.
    """
    result = {
        'fund_score': 0,
        'primary_metric': 'D/E',
        'primary_value': raw_data.get('debt_equity') or raw_data.get('de'),
        'sector_metrics': {}
    }
    
    de = raw_data.get('debt_equity') or raw_data.get('de') or 0
    roe = raw_data.get('roe')
    pb = raw_data.get('pb')
    
    # D/E scoring (Critical for RE)
    # Good D/E for RE: < 1.0, Caution: 1.0-1.5, High: > 1.5
    if de:
        if de < 0.5:
            result['fund_score'] += 25
        elif de < 1.0:
            result['fund_score'] += 20
        elif de < 1.5:
            result['fund_score'] += 12
        elif de < 2.0:
            result['fund_score'] += 6
        else:
            result['fund_score'] += 0
    
    # ROE scoring
    if roe:
        if roe >= 15:
            result['fund_score'] += 25
        elif roe >= 10:
            result['fund_score'] += 18
        elif roe >= 5:
            result['fund_score'] += 10
        elif roe >= 0:
            result['fund_score'] += 5
    
    # P/B scoring (RE often trades below book value)
    if pb:
        if pb < 0.7:
            result['fund_score'] += 15
        elif pb < 1.0:
            result['fund_score'] += 10
        elif pb < 1.5:
            result['fund_score'] += 5
    
    # Inventory status - if available
    inventory_days = raw_data.get('inventory_days') or raw_data.get('inventory_turnover_days')
    if inventory_days:
        result['sector_metrics']['inventory_days'] = inventory_days
        if inventory_days < 365:
            result['fund_score'] += 15
        elif inventory_days < 730:
            result['fund_score'] += 8
        elif inventory_days < 1095:
            result['fund_score'] += 3
    
    # Land bank (pre-sales potential) - if available
    land_bank = raw_data.get('land_bank') or raw_data.get('unsold_inventory')
    if land_bank:
        result['sector_metrics']['land_bank'] = land_bank
        result['fund_score'] += 5  # Having land bank is positive
    
    # Cap at 100
    result['fund_score'] = min(result['fund_score'], 100)
    
    return result


def score_manufacturing_sector(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score manufacturing sector stocks using Gross Margin, Inventory Turnover.
    Lower ROE threshold (10%) for capital-intensive sectors.
    """
    result = {
        'fund_score': 0,
        'primary_metric': 'Gross Margin',
        'primary_value': raw_data.get('gross_margin'),
        'sector_metrics': {}
    }
    
    roe = raw_data.get('roe')
    gross_margin = raw_data.get('gross_margin')
    inventory_turnover = raw_data.get('inventory_turnover')
    pb = raw_data.get('pb')
    
    # Gross Margin scoring
    if gross_margin:
        result['sector_metrics']['gross_margin'] = gross_margin
        if gross_margin >= 30:
            result['fund_score'] += 25
        elif gross_margin >= 20:
            result['fund_score'] += 18
        elif gross_margin >= 10:
            result['fund_score'] += 10
        else:
            result['fund_score'] += 3
    
    # ROE scoring (lower threshold for capital-intensive)
    if roe:
        if roe >= 15:
            result['fund_score'] += 25
        elif roe >= 10:  # Lowered from 15%
            result['fund_score'] += 18
        elif roe >= 5:
            result['fund_score'] += 10
        elif roe >= 0:
            result['fund_score'] += 3
    
    # Inventory Turnover
    if inventory_turnover:
        result['sector_metrics']['inventory_turnover'] = inventory_turnover
        if inventory_turnover >= 6:
            result['fund_score'] += 20
        elif inventory_turnover >= 4:
            result['fund_score'] += 14
        elif inventory_turnover >= 2:
            result['fund_score'] += 8
        else:
            result['fund_score'] += 3
    
    # P/B scoring
    if pb:
        if pb < 1.0:
            result['fund_score'] += 15
        elif pb < 1.5:
            result['fund_score'] += 10
        elif pb < 2.0:
            result['fund_score'] += 5
    
    # Cap at 100
    result['fund_score'] = min(result['fund_score'], 100)
    
    return result


def score_retail_sector(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Score retail/consumer sector stocks.
    Focus on P/E, Revenue Growth, ROE.
    """
    result = {
        'fund_score': 0,
        'primary_metric': 'P/E',
        'primary_value': raw_data.get('pe'),
        'sector_metrics': {}
    }
    
    pe = raw_data.get('pe')
    roe = raw_data.get('roe')
    profit_growth = raw_data.get('profit_growth')
    
    # P/E scoring (important for growth sectors)
    if pe:
        if 5 <= pe <= 15:
            result['fund_score'] += 28
        elif 15 < pe <= 20:
            result['fund_score'] += 20
        elif 20 < pe <= 25:
            result['fund_score'] += 12
        elif pe < 5:
            result['fund_score'] += 18  # May indicate problems
        else:
            result['fund_score'] += 5
    
    # ROE scoring (standard threshold for consumer)
    if roe:
        if roe >= 20:
            result['fund_score'] += 25
        elif roe >= 15:
            result['fund_score'] += 20
        elif roe >= 10:
            result['fund_score'] += 12
        else:
            result['fund_score'] += 5
    
    # Profit Growth
    if profit_growth:
        result['sector_metrics']['profit_growth'] = profit_growth
        if profit_growth >= 20:
            result['fund_score'] += 22
        elif profit_growth >= 10:
            result['fund_score'] += 16
        elif profit_growth >= 0:
            result['fund_score'] += 8
    
    # P/B scoring
    pb = raw_data.get('pb')
    if pb:
        if pb < 3:
            result['fund_score'] += 15
        elif pb < 5:
            result['fund_score'] += 10
        else:
            result['fund_score'] += 3
    
    # Cap at 100
    result['fund_score'] = min(result['fund_score'], 100)
    
    return result


def score_general_sector(raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Default scoring for sectors without specific rules.
    Uses P/E, P/B, ROE framework.
    """
    result = {
        'fund_score': 0,
        'primary_metric': 'P/E',
        'primary_value': raw_data.get('pe'),
        'sector_metrics': {}
    }
    
    pe = raw_data.get('pe')
    pb = raw_data.get('pb')
    roe = raw_data.get('roe')
    
    # P/E scoring
    if pe:
        if 5 <= pe <= 20:
            result['fund_score'] += 30
        elif 20 < pe <= 30:
            result['fund_score'] += 20
        elif pe < 5:
            result['fund_score'] += 15
        else:
            result['fund_score'] += 5
    
    # P/B scoring
    if pb:
        if pb < 1.5:
            result['fund_score'] += 25
        elif pb < 2.5:
            result['fund_score'] += 18
        elif pb < 4:
            result['fund_score'] += 10
        else:
            result['fund_score'] += 3
    
    # ROE scoring
    if roe:
        if roe >= 20:
            result['fund_score'] += 30
        elif roe >= 15:
            result['fund_score'] += 22
        elif roe >= 10:
            result['fund_score'] += 14
        elif roe >= 5:
            result['fund_score'] += 7
    
    # Cap at 100
    result['fund_score'] = min(result['fund_score'], 100)
    
    return result


def score_by_sector(raw_data: Dict[str, Any], industry: str = "") -> Dict[str, Any]:
    """
    Main entry point for sector-specific scoring.
    Routes to appropriate scoring function based on industry.
    """
    sector = get_sector_category(industry)
    
    if sector == 'banking':
        return score_banking_sector(raw_data)
    elif sector == 'real_estate':
        return score_real_estate_sector(raw_data)
    elif sector == 'manufacturing':
        return score_manufacturing_sector(raw_data)
    elif sector == 'retail':
        return score_retail_sector(raw_data)
    else:
        return score_general_sector(raw_data)


# ============== HEALTH VETO CHECK (13 RULES) ==============
def check_health_veto(
    tech: Dict[str, Any],
    fund_data: Dict[str, Any],
    market_rsi: float = 50.0,
    df: pd.DataFrame = None,
    avg_volume_value: float = 0.0,
    industry: str = ""
) -> Dict[str, Any]:
    """Kiểm tra VETO dựa trên 15 quy tắc sức khỏe (KHÔNG bao gồm R:R hay Định giá)

    SECTOR-ADAPTIVE RULES (V3):
    - VETO_Nợ: D/E > 1.5 cho Non-Financial sectors
    - VETO_ROE: Lower threshold (10%) for capital-intensive sectors (Steel, Power, Chemicals)
    - VETO_NPL: NPL > 3% for Banking sector

    Args:
        tech: Dict chỉ số kỹ thuật (price, cmf, rsi, adx, sma_50, bb_percent, ichimoku_status, ichimoku_tenkan, ichimoku_kijun, atr, volume_ratio)
        fund_data: Dict dữ liệu cơ bản (roe, f_score, profit_growth, pe, pb, is_new_listing)
        market_rsi: RSI thị trường chung
        df: DataFrame giá để tính volume TB 20 phiên
        avg_volume_value: Giá trị volume TB quy đổi sang tỷ đồng
        industry: Ngành của cổ phiếu (để xác định sector-adaptive rules)

    Returns:
        Dict: is_vetoed (bool), veto_reason (str), veto_reasons (list)
    """
    veto_reasons = []
    sector = get_sector_category(industry)
    
    # Determine capital-intensive flag for ROE threshold
    is_capital_intensive = sector in ['manufacturing', 'real_estate']
    roe_threshold = 10 if is_capital_intensive else 15

    # ===== NHÓM 1: DÒNG TIỀN (3 rules) =====

    # VETO_1: CMF < 0
    cmf_val = tech.get('cmf', 0)
    if cmf_val < 0:
        veto_reasons.append(f"VETO_1: CMF < 0 ({cmf_val:.2f})")

    # VETO_2: Volume TB 20 phiên < 15 tỷ
    elif avg_volume_value < 15:
        veto_reasons.append(f"VETO_2: VolTB20 < 15B ({avg_volume_value:.1f}B)")

    # VETO_3: Volume_Ratio < 0.5
    elif tech.get('volume_ratio', 1) < 0.5:
        veto_reasons.append(f"VETO_3: VolRatio < 0.5 ({tech.get('volume_ratio', 0):.2f})")

    # ===== NHÓM 2: XU HƯỚNG & ĐỘNG LƯỢNG (5 rules) =====

    # VETO_4: Giá < SMA50
    elif tech.get('price', 0) > 0 and tech.get('sma_50', 0) > 0:
        if tech['price'] < tech['sma_50']:
            veto_reasons.append("VETO_4: Giá < SMA50")

    # VETO_5: Giá dưới mây Ichimoku hoặc mây đỏ
    elif tech.get('ichimoku_status') == 'bearish':
        veto_reasons.append("VETO_5: Ichimoku Bearish")

    # VETO_6: ADX < 20
    elif tech.get('adx', 25) < 20:
        veto_reasons.append(f"VETO_6: ADX < 20 ({tech.get('adx', 0):.1f})")

    # VETO_7: RSI > 80
    elif tech.get('rsi', 50) > 80:
        veto_reasons.append(f"VETO_7: RSI > 80 ({tech.get('rsi', 0):.1f})")

    # VETO_8: bbPos > 105
    elif tech.get('bb_percent', 50) > 105:
        veto_reasons.append(f"VETO_8: BB% > 105 ({tech.get('bb_percent', 0):.1f})")

    # ===== NHÓM 3: SỨC KHỎE TÀI CHÍNH (5 rules) =====

    # VETO_14: D/E > 1.5 (Non-Financial sectors only)
    elif sector != 'banking':
        de = fund_data.get('debt_equity') or fund_data.get('de') or 0
        if de > 1.5:
            veto_reasons.append(f"VETO_14: D/E > 1.5 ({de:.2f})")

    # VETO_15: NPL > 3% (Banking only)
    elif sector == 'banking':
        npl = fund_data.get('npl') or fund_data.get('npl_ratio') or 0
        if npl > 3:
            veto_reasons.append(f"VETO_15: NPL > 3% ({npl:.2f}%)")

    # VETO_9: ROE < threshold (10% for capital-intensive, 15% for others)
    elif fund_data.get('roe') is not None:
        roe_val = fund_data['roe']
        if roe_val < roe_threshold:
            threshold_note = "10%" if is_capital_intensive else "15%"
            veto_reasons.append(f"VETO_9: ROE < {threshold_note} ({roe_val:.1f}%)")

    # VETO_10: F-Score < 5
    elif fund_data.get('f_score', 0) < 5:
        veto_reasons.append(f"VETO_10: F-Score < 5 ({fund_data.get('f_score', 0)}/9)")

    # VETO_11: Profit_Growth < 0 (trừ cổ phiếu mới listing)
    elif not fund_data.get('is_new_listing', False):
        pg = fund_data.get('profit_growth')
        if pg is not None and pg < 0:
            veto_reasons.append(f"VETO_11: ProfitGrowth < 0 ({pg:.1f}%)")

    # VETO_12: Thiếu dữ liệu tài chính
    elif fund_data.get('roe') is None or fund_data.get('pe') is None or fund_data.get('pb') is None:
        veto_reasons.append("VETO_12: Thiếu dữ liệu tài chính")

    # ===== NHÓM 4: THỊ TRƯỜNG (1 rule) =====

    # VETO_13: VNIndex RSI > 80
    elif market_rsi > 80:
        veto_reasons.append(f"VETO_13: Market RSI > 80 ({market_rsi:.1f})")

    # ===== KẾT QUẢ =====
    is_vetoed = len(veto_reasons) > 0
    veto_reason = "; ".join(veto_reasons) if veto_reasons else ""

    return {
        "is_vetoed": is_vetoed,
        "veto_reason": veto_reason,
        "veto_reasons": veto_reasons,
        "sector": sector,
        "roe_threshold_used": roe_threshold
    }


# ============== CORE LOGIC ENGINE (SHARED) ==============
# Hàm thuần túy - KHÔNG gọi API, chỉ tính toán từ dữ liệu đầu vào
# Dùng chung cho cả Live scan và Backtest

def compute_core_logic(
    symbol: str,
    tech: Dict[str, Any],
    fund_data: Dict[str, Any],
    market_rsi: float = 50.0,
    market_group: str = "UNKNOWN",
    df: pd.DataFrame = None,
    quarterly_data: Optional[Dict[str, Dict[str, Any]]] = None,
    date_str: Optional[str] = None
) -> Dict[str, Any]:
    """
    PURE FUNCTION - Engine tính toán trung tâm
    Nhận dữ liệu thô và trả về kết quả phân tích đầy đủ
    
    Args:
        symbol: Mã cổ phiếu
        tech: Dict chứa indicators (price, rsi, cmf, adx, sma_50, sma_200, v.v.)
        fund_data: Dict chứa dữ liệu tài chính (roe, pe, pb, f_score, v.v.)
        market_rsi: RSI của VNIndex tại thời điểm tính
        market_group: Nhóm thị trường (VN30, MIDCAP, SMALL)
        df: DataFrame OHLCV (tùy chọn, để tính avg_volume_value)
        quarterly_data: Dict quarter -> {roe, f_score} cho backtest
        date_str: Ngày tính (format YYYY-MM-DD) để lookup quarterly data
    """
    
    # ========== GET QUARTERLY DATA IF AVAILABLE (FOR BACKTEST) ==========
    roe_val = fund_data.get('roe')
    f_score_val = fund_data.get('f_score', 0)
    
    if quarterly_data and date_str:
        # Parse quarter from date
        try:
            from datetime import datetime as dt
            dt_obj = dt.strptime(date_str, '%Y-%m-%d')
            quarter = f"{dt_obj.year}-Q{(dt_obj.month - 1) // 3 + 1}"
            if quarter in quarterly_data:
                qd = quarterly_data[quarter]
                roe_val = qd.get('roe') or roe_val
                f_score_val = qd.get('f_score') or f_score_val
        except:
            pass
    
    # ========== ENTRY & SUPPORT ==========
    entry = tech.get("price", 0)
    
    # Hỗ trợ cứng = SMA50
    support_price = tech.get("sma_50", 0) if tech.get("sma_50", 0) > 0 else entry * 0.97
    hard_risk = entry - support_price
    hard_risk_pct = (hard_risk / entry) * 100 if entry > 0 else 3
    
    # Target = Entry + 5%
    target_5pct = round(entry * 1.05, 2)

    # ========== TRADING LEVELS: SL ONLY (Price Structure Based) ==========
    # Support = min(SMA50, Low 20 phiên)
    sma_50_support = tech.get("sma_50", 0)
    low_20_val = 0
    if df is not None and 'low' in df.columns and len(df) >= 20:
        low_20_val = df['low'].tail(20).min()

    # Chọn support thấp hơn
    if sma_50_support > 0 and low_20_val > 0:
        support_price = min(sma_50_support, low_20_val)
    elif low_20_val > 0:
        support_price = low_20_val
    elif sma_50_support > 0:
        support_price = sma_50_support
    else:
        support_price = entry * 0.97

    # Stop Loss = Support * 0.985 (tối đa 1.5% dưới support)
    stop_loss = round(support_price * 0.985, 2)

    # ===== MINIMUM RISK BUFFER (3%) =====
    # Kiểm tra khoảng cách rủi ro, nếu < 3% thì điều chỉnh SL
    risk_percent = (entry - stop_loss) / entry if entry > 0 else 0
    if risk_percent < 0.03:
        stop_loss = round(entry * 0.96, 2)  # Cố định 4% risk

    # Inverted SL check
    has_inverted_sl = stop_loss >= entry

    # ATR cho tính Est Days (không dùng cho SL)
    atr_value = tech.get("atr", 0) if tech.get("atr", 0) > 0 else entry * 0.02

    take_profit = round(entry + (atr_value * 3), 2)

    # Preliminary R:R (sẽ recalc sau khi có FV_weekly)
    risk = entry - stop_loss
    rr_ratio = 0
    is_inverted_risk = False
    if risk > 0:
        rr_ratio = round((take_profit - entry) / risk, 2)
    else:
        is_inverted_risk = True
        rr_ratio = 0
    
    # ========== TARGET YIELD & EST. DAYS ==========
    target_yield_pct = round((take_profit - entry) / entry * 100, 2) if entry > 0 else 0
    
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
    
    # Timeframe Label (merged with est days)
    est_days_rounded = round(est_days)
    if est_days <= 3:
        timeframe_label = f"Fast T+ ({est_days_rounded}d)"
        timeframe_color = "emerald"
    elif est_days <= 7:
        timeframe_label = f"Swing ({est_days_rounded}d)"
        timeframe_color = "emerald"
    elif est_days <= 15:
        timeframe_label = f"Swing ({est_days_rounded}d)"
        timeframe_color = "sky"
    else:
        timeframe_label = f"Position ({est_days_rounded}d+)"
        timeframe_color = "amber"
    
    profit_per_day = round(target_yield_pct / est_days, 2) if est_days > 0 else 0
    
    # ========== CRITERIA ==========
    criteria = []
    criteria_names = []
    
    rsi_val = tech.get("rsi", 50)
    cmf_val = tech.get("cmf", 0)
    volume_ratio_val = tech.get("volume_ratio", 1.0)
    vwap_status_val = tech.get("vwap_status", "neutral")
    sma_10_val = tech.get("sma_10", 0)
    sma_20_val = tech.get("sma_20", 0)
    sma_50_val = tech.get("sma_50", 0)
    macd_val = tech.get("macd", 0)
    macd_signal_val = tech.get("macd_signal", 0)
    ichimoku_status_val = tech.get("ichimoku_status", "neutral")
    supertrend_signal_val = tech.get("supertrend_signal", "neutral")
    bb_percent_val = tech.get("bb_percent", 50)
    bb_upper_val = tech.get("bb_upper", 0)
    bb_middle_val = tech.get("bb_middle", 0)
    bb_lower_val = tech.get("bb_lower", 0)
    sma_200_val = tech.get("sma_200", 0)
    price_val = tech.get("price", 0)
    
    # RSI Sweet Spot
    if 50 <= rsi_val <= 65:
        criteria.append("RSI Sweet Spot")
        criteria_names.append("RSI")
    # ADX Strong
    if adx_val > 20:
        criteria.append("ADX Strong")
        criteria_names.append("ADX")
    # DI Bullish
    if tech.get("plus_di", 0) > tech.get("minus_di", 0):
        criteria.append("DI Bullish")
        criteria_names.append("DI+")
    # CMF Positive
    if cmf_val > 0:
        criteria.append("CMF Positive")
        criteria_names.append("CMF")
    # Volume Active
    if volume_ratio_val > 1.0:
        criteria.append("Volume Active")
        criteria_names.append("Vol")
    # Above SMA20
    if sma_20_val > 0 and price_val > sma_20_val:
        criteria.append("Above SMA20")
        criteria_names.append("SMA20")
    # MACD Bullish
    if macd_val > macd_signal_val:
        criteria.append("MACD Bullish")
        criteria_names.append("MACD")
    # R:R Good
    if rr_ratio >= 2.0:
        criteria.append("R:R >= 2.0")
        criteria_names.append("R:R>=2")
    elif rr_ratio >= 1.5:
        criteria.append("R:R >= 1.5")
        criteria_names.append("R:R>=1.5")
    # Fast Holding
    if est_days <= 10:
        criteria.append("Fast Holding")
        criteria_names.append("Fast")
    # VWAP
    if vwap_status_val == "above":
        criteria.append("Above VWAP")
        criteria_names.append("VWAP")
    # Ichimoku Bullish
    if ichimoku_status_val == "bullish":
        criteria.append("Ichimoku Bullish")
        criteria_names.append("Cloud")
    # SuperTrend Bullish
    if supertrend_signal_val == "bullish":
        criteria.append("SuperTrend Bull")
        criteria_names.append("ST")
    
    criteria_met = len(criteria)

    # ========== HEALTH VETO CHECK (13 RULES) ==========
    # Tính avg_volume_value trước khi gọi check_health_veto
    avg_volume_value = 0.0
    if df is not None and 'volume' in df.columns and price_val > 0:
        avg_volume_value = round(volume_ratio_val * price_val * df['volume'].tail(20).mean() / 1e9, 1)

    # Gọi hàm check_health_veto với 13 quy tắc (KHÔNG bao gồm R:R hay Định giá)
    health_result = check_health_veto(
        tech=tech,
        fund_data=fund_data,
        market_rsi=market_rsi,
        df=df,
        avg_volume_value=avg_volume_value
    )

    is_vetoed = health_result["is_vetoed"]
    veto_reason = health_result["veto_reason"]

    # NOTE: R:R < 1.0 và các điều kiện liên quan KHÔNG còn là VETO
    # Chúng sẽ được xử lý như WARNING/CONCERN trong Bước 2

    has_high_resistance = False

    # Safe Entry
    safe_entry_distance = 0
    if sma_20_val > 0 and price_val > 0:
        safe_entry_distance = ((price_val - sma_20_val) / sma_20_val) * 100
    
    is_safe_entry = abs(safe_entry_distance) <= 2
    
    # ========== SCORES ==========
    tech_score = 50
    fund_score = 50
    
    if not is_vetoed:
        # TECH SCORE
        if 50 <= rsi_val <= 65:
            tech_score += 12 if 55 <= rsi_val <= 62 else 8
        elif rsi_val > 70:
            tech_score -= 15
        elif rsi_val > 65:
            tech_score -= 8
        elif rsi_val < 40:
            tech_score += 5
        
        if adx_val > 25:
            tech_score += 12
        elif adx_val > 20:
            tech_score += 8
        
        if cmf_val > 0.1:
            tech_score += 12
        elif cmf_val > 0:
            tech_score += 8
        else:
            tech_score -= 15
        
        if volume_ratio_val > 1.5:
            tech_score += 8
        elif volume_ratio_val > 1.0:
            tech_score += 5
        
        if rr_ratio >= 2.0:
            tech_score += 10
        elif rr_ratio >= 1.5:
            tech_score += 6
        elif rr_ratio < 1.0:
            tech_score -= 10
        
        if is_safe_entry:
            tech_score += 10
        
        # High Resistance Penalty
        if bb_upper_val > 0 and take_profit > bb_upper_val:
            tech_score -= 15
            has_high_resistance = True
        
        if vwap_status_val == "below":
            tech_score -= 8
        
        if has_inverted_sl:
            tech_score -= 10
        
        # FAST PICK
        is_fast_pick = adx_val > 18 and volume_ratio_val > 0.8
    else:
        tech_score = max(25, tech_score - 30)
        is_fast_pick = False
    
    tech_score = max(0, min(100, tech_score))
    
    # FUND SCORE
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
    
    if roe_val is not None:
        if roe_val > 25:
            fund_score = min(100, fund_score + 12)
        elif roe_val > 20:
            fund_score = min(100, fund_score + 10)
        elif roe_val > 15:
            fund_score = min(100, fund_score + 8)
        elif roe_val < 5:
            fund_score = max(0, fund_score - 15)
    
    # ========== PROFIT GROWTH STRATEGY ==========
    profit_growth = fund_data.get('profit_growth')
    if profit_growth is not None:
        if profit_growth > 25:
            fund_score = min(100, fund_score + 20)  # Tăng trưởng > 25% -> +20 điểm
        elif profit_growth > 15:
            fund_score = min(100, fund_score + 12)
        elif profit_growth > 5:
            fund_score = min(100, fund_score + 8)
        # NOTE: VETO cho profit_growth < 0 đã được xử lý ở trên (Veto 11)
    
    # SMART MONEY & INDUSTRY BONUS
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
    
    # ========== RISK ASSESSMENT ==========
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
    
    # ========== SIGNAL ==========
    is_sell_zone = market_rsi > 70
    
    # If VETO, always signal WAIT (already set, but ensure)
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
    
    # ========== MARKET WEIGHT ==========
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
    
    # ========== RELATIVE STRENGTH (RS) BONUS/PENALTY ==========
    # RS compares stock return vs Sector Index return vs VNIndex return
    # Leader: Stock > Sector > Market -> +15 boost
    # Laggard: Stock < Sector < Market -> -10 penalty
    industry_perf = fund_data.get('industry_performance', 0)
    rs_bonus = 0
    rs_label = "NEUTRAL"
    
    if industry_perf >= 5:
        # Stock outperforming sector
        rs_bonus = 15
        rs_label = "LEADER"
    elif industry_perf >= 2:
        rs_bonus = 8
        rs_label = "OUTPERFORM"
    elif industry_perf <= -5:
        # Stock underperforming sector
        rs_bonus = -10
        rs_label = "LAGGARD"
    elif industry_perf <= -2:
        rs_bonus = -5
        rs_label = "UNDERPERFORM"
    
    # Master Score = 70% Technical + 30% Fundamental + RS Bonus (per spec v3)
    base_master_score = int(tech_score * 0.7 + fund_score * 0.3)
    
    # VETO: Set master_score = 10 (strict per spec)
    if is_vetoed:
        master_score = 10
        base_master_score = 10
        rs_bonus = 0  # No RS bonus for vetoed stocks
        rs_label = "VETO"
    else:
        master_score = max(0, min(100, base_master_score + market_weight + rs_bonus))
    
    # Store RS info for UI
    rs_info = {
        'bonus': rs_bonus,
        'label': rs_label,
        'industry_performance': industry_perf
    }
    
    # ========== TREND ==========
    if sma_20_val > 0 and sma_50_val > 0:
        if price_val > sma_20_val > sma_50_val:
            trend = "UPTREND"
        elif price_val < sma_20_val < sma_50_val:
            trend = "DOWNTREND"
        else:
            trend = "SIDEWAYS"
    else:
        trend = "SIDEWAYS"
    
    # ========== AVG VOLUME VALUE ==========
    avg_volume_value = 0
    if df is not None and 'volume' in df.columns:
        avg_volume_value = round(volume_ratio_val * price_val * df['volume'].tail(20).mean() / 1e9, 1)

    # ========== INDUSTRY CONFIG (needed for FV) ==========
    industry = fund_data.get('industry', 'Default')
    industry_key = next((k for k in INDUSTRY_CONFIG if k.lower() in industry.lower()), 'Default')

    # ========== FAIR VALUE: DYNAMIC SECTOR VALUATION (v10.3) ==========
    vwap_val = tech.get('vwap', price_val)
    sma10_val = tech.get('sma_10', price_val)
    sma20_val_t = tech.get('sma_20', price_val)

    # FV Daily: (VWAP * 0.4) + (SMA20 * 0.6)
    fv_daily = round((vwap_val * 0.4) + (sma20_val_t * 0.6), 2)

    # Get dynamic sector valuation (Median-based với Wealth Guard Cap)
    actual_pe = fund_data.get('pe') or 0
    val_config = get_target_valuation(industry_key)
    
    # Sử dụng Dynamic Median PE hoặc Fallback (đã apply Wealth Guard Cap trong get_target_valuation)
    target_pe = val_config['target']
    pe_valuation = price_val * (target_pe / actual_pe) if actual_pe > 0 else price_val
    
    # Track valuation source for display
    valuation_source = val_config['source']
    valuation_cap_applied = val_config['cap_applied']
    sector_median_pe = val_config['dynamic']

    # 52-week high based valuation (nếu có data)
    high_52w = tech.get('high_52w', 0)
    if high_52w > 0:
        high_52w_valuation = high_52w  # Dùng luôn đỉnh cao 52 tuần
    else:
        high_52w_valuation = price_val * 1.20  # Fallback: giả định đỉnh cao hơn 20%

    # FV Weekly = Trung bình P/E valuation và 52-week high valuation
    fv_weekly = (pe_valuation + high_52w_valuation) / 2
    fv_weekly = round(fv_weekly, 2)

    # Cap FV_weekly at 130% of current price (không định giá ảo)
    max_fv = price_val * 1.30
    if fv_weekly > max_fv:
        fv_weekly = round(max_fv, 2)

    # Market Risk Adjustment: -10% when Market RSI > 75
    if market_rsi > 75:
        fv_weekly = round(fv_weekly * 0.9, 2)

    # ===== UPDATE TAKE_PROFIT = FV_WEEKLY =====
    take_profit = round(fv_weekly, 2)

    # ===== TRAILING STOP (Step 4) =====
    # Trailing SL = 5% below current price
    trailing_sl = round(price_val * 0.95, 2)
    
    # Final SL = max(support_SL, trailing_SL)
    final_stop_loss = max(stop_loss, trailing_sl)
    
    # Update stop_loss to final value
    stop_loss = final_stop_loss

    # ===== RECALCULATE R:R WITH FINAL STOP LOSS =====
    risk = entry - stop_loss
    if risk > 0:
        rr_ratio = round((take_profit - entry) / risk, 2)
    else:
        rr_ratio = 0
        is_inverted_risk = True

    # ========== RECOMMENDATION LABEL ==========
    # Format: Signal (Strategy Group)
    # GOLD: Score >= 70, GUERRILLA: Score >= 55, RISK: Score < 55, VETO: is_vetoed
    if is_vetoed:
        strategy_group = "VETO"
    elif master_score >= 70:
        strategy_group = "GOLD"
    elif master_score >= 55:
        strategy_group = "GUERRILLA"
    else:
        strategy_group = "RISK"

    recommendation_label = f"{signal} ({strategy_group})"

    # ===== UPDATE EST. DAYS & TARGET YIELD =====
    target_yield_pct = round((take_profit - entry) / entry * 100, 2) if entry > 0 else 0
    price_diff = take_profit - entry
    if atr_value > 0 and atr_value < entry:
        est_days = price_diff / (atr_value * trend_factor)
    elif atr_value > 0:
        est_days = price_diff / (atr_value * trend_factor)
    else:
        est_days = price_diff / (entry * 0.02 * trend_factor) if entry > 0 else 10
    est_days = min(max(est_days, 1), 30)
    profit_per_day = round(target_yield_pct / est_days, 2) if est_days > 0 else 0

    # Valuation Status - Chỉ "Rẻ" nếu Price < FV * 0.9 (biên an toàn 10%)
    if is_vetoed:
        valuation_status = "RISK"
    else:
        safe_threshold = fv_weekly * 0.9
        valuation_status = "Rẻ" if price_val < safe_threshold else "Đắt"

    # ===== R:R QUALITY GRADING =====
    rr_quality = ""
    rr_quality_detail = ""
    rr_warning = ""

    if rr_ratio >= 10:
        rr_quality = "⚠️ Warning"
        rr_quality_detail = "Cắt lỗ quá sát, rủi ro nhiễu cao"
        rr_warning = f"⚠️ Cắt lỗ quá sát, rủi ro nhiễu cao"
    elif 5.0 <= rr_ratio < 10:
        rr_quality = "💎 Diamond"
        rr_quality_detail = "Kèo cực phẩm - R:R vượt ngưỡng"
    elif 2.5 <= rr_ratio < 5.0:
        rr_quality = "⭐ Golden"
        rr_quality_detail = "Vùng R:R lý tưởng"
    elif 1.5 <= rr_ratio < 2.5:
        rr_quality = "Good"
        rr_quality_detail = "R:R khả thi"
    else:
        rr_quality = "Poor"
        rr_quality_detail = "R:R thấp"
    
    # ========== RETURN ==========
    return {
        # Basic info
        "symbol": symbol,
        "price": price_val,
        "change_percent": tech.get("change_percent", 0),
        "volume": tech.get("volume", 0),
        # Technical
        "rsi": rsi_val,
        "mfi": tech.get("mfi", 50),
        "adx": adx_val,
        "plus_di": tech.get("plus_di", 0),
        "minus_di": tech.get("minus_di", 0),
        "cmf": cmf_val,
        "atr": atr_value,
        "sma_10": sma10_val,
        "sma_20": sma20_val_t,
        "sma_50": sma_50_val,
        "bb_upper": bb_upper_val,
        "bb_middle": bb_middle_val,
        "bb_lower": bb_lower_val,
        "bb_percent": bb_percent_val,
        "macd": macd_val,
        "macd_signal": macd_signal_val,
        "volume_ratio": volume_ratio_val,
        # Advanced TA
        "vwap": vwap_val,
        "vwap_status": vwap_status_val,
        "ichimoku_tenkan": tech.get("ichimoku_tenkan", 0),
        "ichimoku_kijun": tech.get("ichimoku_kijun", 0),
        "ichimoku_status": ichimoku_status_val,
        "supertrend": tech.get("supertrend", 0),
        "supertrend_signal": supertrend_signal_val,
        # Avg volume value
        "avg_volume_value": avg_volume_value,
        # Trading levels
        "entry_price": entry,
        "stop_loss": stop_loss,
        "trailing_sl": trailing_sl,
        "take_profit": take_profit,
        "risk_reward_ratio": rr_ratio,
        "rr_quality": rr_quality,
        "rr_quality_detail": rr_quality_detail,
        "rr_warning": rr_warning,
        # Fair Value
        "fv_daily": fv_daily,
        "fv_weekly": fv_weekly,
        "valuation_status": valuation_status,
        "intrinsic_value": round(pe_valuation, 2),
        "sector_median_pe": sector_median_pe,
        "valuation_source": valuation_source,
        "valuation_cap_applied": valuation_cap_applied,
        "industry_config": val_config,
        # Target Yield & Est. Days
        "target_yield_pct": target_yield_pct,
        "trend_factor": trend_factor,
        "estimated_days_to_target": round(est_days, 1),
        "timeframe_label": timeframe_label,
        "timeframe_color": timeframe_color,
        "expected_profit_per_day": profit_per_day,
        "upside_per_day": profit_per_day,
        # Scores
        "master_score": master_score,
        "base_master_score": base_master_score,
        "market_weight": market_weight,
        "technical_score": tech_score,
        "fundamental_score": fund_score,
        # Safe Entry & Resistance
        "is_safe_entry": is_safe_entry,
        "has_high_resistance": has_high_resistance,
        # Signal & Status
        "signal": signal,
        "is_vetoed": is_vetoed,
        "veto_reason": veto_reason,
        "is_fast_pick": is_fast_pick,
        "is_short_term_qualified": not is_vetoed and criteria_met >= 9,
        "is_slow_mode": est_days > 10,
        "is_high_risk": is_high_risk,
        "is_market_high_risk": is_market_high_risk,
        "stock_risk_level": stock_risk_level,
        "stock_risk_reason": stock_risk_reason,
        "has_inverted_sl": has_inverted_sl,
        "is_inverted_risk": is_inverted_risk,
        # Criteria
        "criteria_met": criteria_met,
        "criteria_list": criteria,
        "criteria_names": criteria_names,
        # Recommendation Label
        "recommendation_label": recommendation_label,
        # Trend
        "trend": trend,
        "breakout_status": "BREAKOUT" if is_fast_pick and not is_vetoed else ("VETO" if is_vetoed else "WAIT"),
        # Market
        "market_rsi": market_rsi,
        # Fundamental
        "roe": roe_val,
        "pe": fund_data.get('pe'),
        "pb": fund_data.get('pb'),
        "f_score": f_score_val,
        "f_score_grade": get_f_score_grade(f_score_val),
        "profit_growth": fund_data.get('profit_growth'),
        "profit_growth_note": fund_data.get('profit_growth_note', 'N/A'),
        "is_new_listing": fund_data.get('is_new_listing', False),
        # Smart Money & Industry
        "foreign_buy_streak": foreign_streak,
        "foreign_bonus": foreign_bonus,
        "industry_performance": industry_perf,
        "is_industry_leader": industry_perf >= 0,
        # Real R:R
        "hard_risk_pct": round(hard_risk_pct, 2),
        "support_price": round(support_price, 2),
        "risk_percent": round(risk_percent * 100, 2),
        # P/E Industry
        "pe_industry_avg": fund_data.get('pe_industry_avg') or 0,
        # Early Exit
        "early_exit_trigger_pct": 2.0,
        "early_exit_drop_pct": 0.7,
        "optimal_position_size": calculate_optimal_position(
            account_balance=100_000_000,
            risk_tolerance=2.0,
            entry_price=entry,
            support_price=support_price
        ),
        "account_balance": 100_000_000,
        "risk_tolerance_pct": 2.0,
        # Industry
        "industry": industry,
        # Relative Strength (RS)
        "rs_bonus": rs_info['bonus'],
        "rs_label": rs_info['label'],
        "rs_industry_performance": rs_info['industry_performance'],
    }


def get_top_symbols_by_liquidity() -> List[str]:
    """Lấy Top 100 mã thanh khoản cao nhất"""
    warnings.filterwarnings('ignore')

    # Danh sách ~120 mã thanh khoản tốt nhất (không trùng lặp)
    candidates = [
        # VN30 & Bluechips
        "VNM", "VCB", "VHM", "VIC", "VPB", "BID", "TCB", "CTG", "MBB", "ACB",
        "STB", "HPG", "FPT", "MWG", "PNJ", "TPB", "SHB", "SSI", "MSN", "GAS",
        "PLX", "VRE", "VIB", "SAB", "HDB", "LPB", "SSB", "GVR", "BCM", "VJC",
        # Midcap - Ngân hàng
        "OCB", "EIB", "MSB", "NAB", "KLB", "BAB", "PGB", "VBB", "ABB", "TPB",
        # Midcap - Bất động sản
        "NVL", "DIG", "DXG", "KDH", "HDG", "IDJ", "SJS", "DPG", "CRE", "NLG",
        "ASM", "IJC", "KAC", "DPR", "VPH", "PDR", "BCM", "HII", "SRA", "VIG",
        # Midcap - Chứng khoán
        "VND", "HCM", "CTS", "VCI", "SHS", "VDS", "BVS", "TVS", "SSI", "VIX",
        "APG", "BSI", "CSI", "EVS", "FTS", "HBS", "IVS", "KBS", "MBS", "PHS",
        # Midcap - Sản xuất & Vật liệu
        "DGC", "GMD", "SBT", "DGW", "CMG", "IMP", "VHC", "REE", "NT2", "DRC",
        "AAA", "ALT", "AMC", "BMC", "CSV", "DCL", "DHC", "DPM", "DVP", "HAP",
        # Midcap - Năng lượng & Dịch vụ
        "POW", "HAG", "BSR", "PVD", "PVC", "VND", "OGC", "ASP", "CAV", "CLC",
        # Midcap - Bán lẻ & Tiêu dùng
        "DGW", "ELC", "GCC", "HAX", "MWG", "PET", "QNS", "SAT", "STK", "TMT",
        # Midcap - Công nghiệp
        "BMI", "CII", "CSM", "DXP", "HHS", "HT1", "KSB", "LIX", "LM8", "MSR",
    ]

    try:
        from vnstock import Quote
        liquidity_data = []
        for symbol in candidates:
            try:
                q = Quote(symbol=symbol, source="kbs")
                df = q.history(
                    start=(datetime.now() - pd.Timedelta(days=30)).strftime("%Y-%m-%d"),
                    end=datetime.now().strftime("%Y-%m-%d"),
                    interval="1D"
                )
                if df is not None and len(df) >= 10:
                    avg_volume = df['volume'].tail(20).mean()
                    avg_price = df['close'].tail(5).mean() * 1000  # KBS trả giá đã chia 1000
                    avg_value = avg_volume * avg_price

                    if avg_price > MIN_PRICE and avg_value > MIN_LIQUIDITY_BILLION * 1e9:
                        liquidity_data.append((symbol, avg_value))
            except:
                continue

        liquidity_data.sort(key=lambda x: x[1], reverse=True)
        top_symbols = [s[0] for s in liquidity_data[:UNIVERSE_SIZE]]

        if len(top_symbols) < 5:
            print(f"[Sync] Fallback: Chỉ có {len(top_symbols)} mã đủ thanh khoản")
            top_symbols = candidates[:UNIVERSE_SIZE]

        return top_symbols

    except Exception as e:
        print(f"[Sync] Error getting symbols: {e}")
        return [
            "VNM", "VCB", "VHM", "VIC", "VPB", "BID", "TCB", "CTG", "MBB", "ACB",
            "STB", "HPG", "FPT", "MWG", "PNJ", "TPB", "SHB", "SSI", "MSN", "GAS",
        ][:20]


def calculate_technical_indicators(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Calculate technical indicators using vnstock_ta
    Includes: RSI, MACD, ADX, CMF, Bollinger, SMA, VWAP, Ichimoku, SuperTrend, MFI
    """
    result = {
        "price": 0.0,
        "change_percent": 0.0,
        "volume": 0,
        "rsi": 50.0,
        "mfi": 50.0,
        "adx": 25.0,
        "plus_di": 0.0,
        "minus_di": 0.0,
        "cmf": 0.0,
        "sma_10": 0.0,
        "sma_20": 0.0,
        "sma_50": 0.0,
        "sma_200": 0.0,
        "bb_upper": 0.0,
        "bb_middle": 0.0,
        "bb_lower": 0.0,
        "bb_percent": 50.0,
        "macd": 0.0,
        "macd_signal": 0.0,
        "atr": 0.0,
        "vwap": 0.0,
        "vwap_status": "neutral",
        "ichimoku_tenkan": 0.0,
        "ichimoku_kijun": 0.0,
        "ichimoku_status": "neutral",
        "supertrend": 0.0,
        "supertrend_signal": "neutral",
        "volume_ratio": 1.0,
    }

    if df is None or len(df) < 20:
        return result

    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']

    try:
        # Current values
        result["price"] = float(close.iloc[-1])
        result["volume"] = int(volume.iloc[-1]) if 'volume' in df.columns else 0

        # Change Percent
        if len(close) > 1:
            prev_close = float(close.iloc[-2])
            if prev_close > 0:
                result["change_percent"] = round((result["price"] - prev_close) / prev_close * 100, 2)

        # Volume Ratio
        avg_vol = volume.tail(20).mean()
        if avg_vol > 0:
            result["volume_ratio"] = round(float(volume.iloc[-1]) / avg_vol, 2)

        # Try vnstock_ta
        try:
            from vnstock_ta import Indicator  # pyright: ignore[reportMissingImports]
            ind = Indicator(data=df)

            # RSI
            try:
                rsi_series = ind.rsi(length=14)
                if rsi_series is not None and len(rsi_series) > 0:
                    result["rsi"] = round(float(rsi_series.iloc[-1]), 1)
            except Exception:
                pass

            # ADX
            try:
                adx_df = ind.adx(length=14)
                if adx_df is not None and len(adx_df) > 0 and hasattr(adx_df, 'columns'):
                    for col in adx_df.columns:
                        col_str = str(col).upper()
                        if 'ADX' in col_str and 'DMP' not in col_str and 'DMN' not in col_str:
                            result["adx"] = round(float(adx_df[col].iloc[-1]), 1)
                            break
                    for col in adx_df.columns:
                        col_str = str(col).upper()
                        if 'DMP' in col_str or 'PLUS' in col_str:
                            result["plus_di"] = round(float(adx_df[col].iloc[-1]), 1)
                            break
                    for col in adx_df.columns:
                        col_str = str(col).upper()
                        if 'DMN' in col_str or 'MINUS' in col_str:
                            result["minus_di"] = round(float(adx_df[col].iloc[-1]), 1)
                            break
            except Exception:
                pass

            # MACD
            try:
                macd_df = ind.macd(fast=12, slow=26, signal=9)
                if macd_df is not None and len(macd_df) > 0 and hasattr(macd_df, 'columns'):
                    cols = list(macd_df.columns)
                    if len(cols) >= 1:
                        result["macd"] = round(float(macd_df[cols[0]].iloc[-1]), 2)
                    if len(cols) >= 2:
                        result["macd_signal"] = round(float(macd_df[cols[1]].iloc[-1]), 2)
            except Exception:
                pass

            # SMA
            try:
                sma_20_series = ind.sma(length=20)
                if sma_20_series is not None and len(sma_20_series) > 0:
                    result["sma_20"] = round(float(sma_20_series.iloc[-1]), 2)
            except Exception:
                pass

            try:
                sma_10_series = ind.sma(length=10)
                if sma_10_series is not None and len(sma_10_series) > 0:
                    result["sma_10"] = round(float(sma_10_series.iloc[-1]), 2)
            except Exception:
                pass

            try:
                sma_50_series = ind.sma(length=50)
                if sma_50_series is not None and len(sma_50_series) > 0:
                    result["sma_50"] = round(float(sma_50_series.iloc[-1]), 2)
            except Exception:
                pass

            try:
                sma_200_series = ind.sma(length=200)
                if sma_200_series is not None and len(sma_200_series) > 0:
                    result["sma_200"] = round(float(sma_200_series.iloc[-1]), 2)
            except Exception:
                pass

            # Bollinger
            try:
                bb_df = ind.bbands(length=20, std=2)
                if bb_df is not None and len(bb_df) > 0 and hasattr(bb_df, 'columns'):
                    cols = list(bb_df.columns)
                    for col in cols:
                        if 'BBL' in col.upper():
                            result["bb_lower"] = round(float(bb_df[col].iloc[-1]), 2)
                        elif 'BBM' in col.upper():
                            result["bb_middle"] = round(float(bb_df[col].iloc[-1]), 2)
                        elif 'BBU' in col.upper():
                            result["bb_upper"] = round(float(bb_df[col].iloc[-1]), 2)

                    if result["bb_upper"] > result["bb_lower"]:
                        result["bb_percent"] = round((result["price"] - result["bb_lower"]) / (result["bb_upper"] - result["bb_lower"]) * 100, 1)
            except Exception:
                pass

            # CMF
            try:
                cmf_series = ind.cmf(length=20)
                if cmf_series is not None and len(cmf_series) > 0:
                    result["cmf"] = round(float(cmf_series.iloc[-1]), 3)
            except Exception:
                pass

            # ATR
            try:
                atr_series = ind.atr(length=14)
                if atr_series is not None and len(atr_series) > 0:
                    result["atr"] = round(float(atr_series.iloc[-1]), 2)
            except Exception:
                pass

        except ImportError:
            pass

        # Manual ATR fallback
        if result["atr"] <= 0 and len(df) >= 15:
            try:
                tr1 = high - low
                tr2 = abs(high - close.shift(1))
                tr3 = abs(low - close.shift(1))
                tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
                atr_series = tr.rolling(14).mean()
                result["atr"] = round(float(atr_series.iloc[-1]), 2) if not pd.isna(atr_series.iloc[-1]) else 0
            except Exception:
                pass

        # ATR fallback to percentage
        if result["atr"] <= 0 or result["atr"] is None:
            result["atr"] = round(result["price"] * 0.02, 2) if result["price"] > 0 else 1000

        # Manual RSI fallback
        if result["rsi"] == 50.0:
            try:
                delta = close.diff()
                gain = delta.where(delta > 0, 0).rolling(14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs))
                result["rsi"] = round(float(rsi.iloc[-1]), 1) if not pd.isna(rsi.iloc[-1]) else 50
            except Exception:
                pass

        # Manual CMF
        if result["cmf"] == 0.0:
            try:
                mfm = ((close - low) - (high - close)) / (high - low)
                mfm = mfm.fillna(0)
                mfv = mfm * volume
                cmf = mfv.rolling(20).sum() / volume.rolling(20).sum()
                result["cmf"] = round(float(cmf.iloc[-1]), 4) if not pd.isna(cmf.iloc[-1]) else 0
            except Exception:
                pass

        # Manual MFI
        if result["mfi"] == 50.0:
            try:
                typical_price = (high + low + close) / 3
                money_flow = typical_price * volume
                positive_flow = money_flow.where(typical_price > typical_price.shift(), 0).rolling(14).sum()
                negative_flow = money_flow.where(typical_price < typical_price.shift(), 0).rolling(14).sum()
                money_ratio = positive_flow / negative_flow.replace(0, 1)
                mfi = 100 - (100 / (1 + money_ratio))
                result["mfi"] = round(float(mfi.iloc[-1]), 1) if not pd.isna(mfi.iloc[-1]) else 50
            except Exception:
                pass

        # VWAP
        try:
            typical_price = (high + low + close) / 3
            cum_vol = volume.cumsum()
            vwap_value = (typical_price * volume).cumsum() / cum_vol
            result["vwap"] = round(float(vwap_value.iloc[-1]), 2)
            result["vwap_status"] = "above" if result["price"] > result["vwap"] else "below"
        except Exception:
            result["vwap"] = result["price"]
            result["vwap_status"] = "neutral"

        # Ichimoku
        if len(df) >= 52:
            try:
                high_9 = high.rolling(9).max()
                low_9 = low.rolling(9).min()
                result["ichimoku_tenkan"] = round((high_9 + low_9).iloc[-1] / 2, 2)

                high_26 = high.rolling(26).max()
                low_26 = low.rolling(26).min()
                result["ichimoku_kijun"] = round((high_26 + low_26).iloc[-1] / 2, 2)

                tenkan = result["ichimoku_tenkan"]
                kijun = result["ichimoku_kijun"]
                price = result["price"]

                if price > tenkan > kijun:
                    result["ichimoku_status"] = "bullish"
                elif price < tenkan < kijun:
                    result["ichimoku_status"] = "bearish"
                else:
                    result["ichimoku_status"] = "neutral"
            except Exception:
                pass

        # SuperTrend
        try:
            if result["atr"] > 0:
                hl2 = (high + low) / 2
                lower_band = hl2 - (result["atr"] * 2)
                result["supertrend"] = round(float(lower_band.iloc[-1]), 2)
                result["supertrend_signal"] = "bullish" if result["price"] > result["supertrend"] else "bearish"
        except Exception:
            pass

    except Exception as e:
        print(f"[Sync] Error calculating indicators: {e}")

    return result


def analyze_stock(symbol: str, market_rsi: float = 50.0, fast_mode: bool = False) -> Optional[Dict[str, Any]]:
    """Phân tích một mã cổ phiếu - trả về dict kết quả
    fast_mode: True = bỏ qua các API calls tốn thời gian (profit_growth, industry, foreign)
    
    REFACTORED: Sử dụng compute_core_logic() để đảm bảo đồng bộ với Backtest
    """
    try:
        import warnings as w
        w.filterwarnings('ignore')

        # Get Company Name (skip in fast mode)
        company_name = get_company_name(symbol) if not fast_mode else symbol

        # Get Fundamental Data (ROE, P/E, P/B, F-Score)
        fund_data = get_fundamental_data(symbol, fast_mode=fast_mode)

        # Get Price Data - try vnstock_data first
        df = None
        try:
            from vnstock_data import Market
            mkt = Market()
            df = mkt.equity(symbol).ohlcv(
                start=(datetime.now() - pd.Timedelta(days=250)).strftime("%Y-%m-%d"),
                end=datetime.now().strftime("%Y-%m-%d")
            )
            if df is not None and len(df) > 0:
                # Convert to correct price scale
                for col in ['open', 'high', 'low', 'close']:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce') * 1000
                if 'time' in df.columns:
                    df.set_index('time', inplace=True)
        except:
            pass

        if df is None:
            try:
                from vnstock import Quote
                q = Quote(symbol=symbol, source="kbs")
                df = q.history(
                    start=(datetime.now() - pd.Timedelta(days=250)).strftime("%Y-%m-%d"),
                    end=datetime.now().strftime("%Y-%m-%d"),
                    interval="1D"
                )
            except:
                return None

        if df is None or len(df) < 20:
            return None

        # Get Market Group for Veto check
        market_group = "UNKNOWN"
        try:
            stock = StockData.objects.get(symbol=symbol.upper())
            market_group = stock.market_group or "UNKNOWN"
        except:
            pass

        # Calculate indicators
        tech = calculate_technical_indicators(df)
        
        # Add industry to fund_data
        fund_data_with_industry = dict(fund_data)
        try:
            stock = StockData.objects.get(symbol=symbol.upper())
            fund_data_with_industry['industry'] = stock.industry or 'Default'
        except:
            fund_data_with_industry['industry'] = 'Default'

        # ========== CALL CORE LOGIC ENGINE ==========
        result = compute_core_logic(
            symbol=symbol,
            tech=tech,
            fund_data=fund_data_with_industry,
            market_rsi=market_rsi,
            market_group=market_group,
            df=df
        )
        
        # Add company_name (only for live analysis)
        result['company_name'] = company_name

        return result

    except Exception as e:
        print(f"[Sync] Error analyzing {symbol}: {e}")
        import traceback
        traceback.print_exc()
        return None


def sync_stock_batch(symbols: List[str], market_rsi: float = 50.0, fast_mode: bool = False, retry_failed: int = 2) -> Dict[str, Any]:
    """Đồng bộ một batch mã cổ phiếu với timeout per-symbol, retry logic và fast_mode"""
    SYMBOL_TIMEOUT = 35 if fast_mode else 60  # Fast mode = 35s, Full mode = 60s
    MAX_RETRIES = retry_failed  # Số lần retry cho failed symbols
    
    results = []
    failed_symbols = list(symbols)  # Bắt đầu với tất cả symbols
    
    for attempt in range(MAX_RETRIES + 1):
        if not failed_symbols:
            break
            
        if attempt > 0:
            print(f"[Sync] 🔄 Retry attempt {attempt}/{MAX_RETRIES} for {len(failed_symbols)} failed symbols...")
            sleep(2)  # Chờ 2s trước khi retry
        
        batch_results = []
        still_failed = []
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(analyze_stock, symbol, market_rsi, fast_mode): symbol for symbol in failed_symbols}
            
            # Tính timeout tổng = timeout per symbol + buffer
            total_timeout = (SYMBOL_TIMEOUT + 10) * (MAX_RETRIES - attempt + 1)  # Tăng timeout cho retry
            
            try:
                for future in as_completed(futures, timeout=total_timeout):
                    symbol = futures[future]
                    try:
                        result = future.result(timeout=SYMBOL_TIMEOUT)
                        if result:
                            batch_results.append(result)
                        else:
                            still_failed.append(symbol)
                    except TimeoutError:
                        print(f"[Sync] ⏱️ Timeout analyzing {symbol}")
                        still_failed.append(symbol)
                    except Exception as e:
                        print(f"[Sync] Error processing {symbol}: {e}")
                        still_failed.append(symbol)
            except TimeoutError:
                # Timeout toàn bộ batch
                print(f"[Sync] ⚠️ Batch timeout after {total_timeout}s")
                still_failed = list(futures.values())
        
        results.extend(batch_results)
        failed_symbols = still_failed
    
    if failed_symbols:
        print(f"[Sync] ⚠️ {len(failed_symbols)} symbols failed after {MAX_RETRIES} retries: {failed_symbols}")
    
    return {"results": results, "count": len(results), "failed": failed_symbols}


def sync_market_data(mode: str = "full", fast_mode: bool = False) -> Dict[str, Any]:
    """Đồng bộ toàn bộ dữ liệu thị trường
    fast_mode: True = bỏ qua các API calls tốn thời gian (profit_growth, industry, foreign)
    """
    start_time = datetime.now()

    sync_record, created = SyncStatus.objects.get_or_create(
        id=1,
        defaults={
            "status": "running",
            "total_symbols": UNIVERSE_SIZE,
            "processed_symbols": 0,
            "started_at": timezone.now()
        }
    )
    sync_record.status = "running"
    sync_record.started_at = timezone.now()
    sync_record.save()

    mode_desc = "FULL" if not fast_mode else "FAST"
    print(f"[Sync] Starting sync in '{mode}' mode ({mode_desc})...")

    # Lấy Market RSI
    market_rsi = get_market_rsi()
    print(f"[Sync] Market RSI: {market_rsi:.2f}")

    if mode == "analyze":
        symbols = list(StockData.objects.values_list('symbol', flat=True))
        print(f"[Sync] Analyze mode: Re-analyzing {len(symbols)} existing symbols")
    else:
        symbols = get_top_symbols_by_liquidity()
        print(f"[Sync] Got {len(symbols)} symbols")

    # Process in batches
    batch_size = 20
    all_results = []
    total_failed = 0
    failed_symbols_list = []

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i+batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(symbols) + batch_size - 1) // batch_size
        print(f"[Sync] Batch {batch_num}/{total_batches}: {batch[:3]}...")
        print(f"[Sync] Progress: {min(i + batch_size, len(symbols))}/{len(symbols)} symbols ({(min(i + batch_size, len(symbols)) / len(symbols) * 100):.0f}%)")

        batch_result = sync_stock_batch(batch, market_rsi, fast_mode=fast_mode)
        all_results.extend(batch_result["results"])
        
        if batch_result.get("failed"):
            total_failed += len(batch_result["failed"])
            failed_symbols_list.extend(batch_result["failed"])

        # Update progress percentage
        progress = int(min(i + batch_size, len(symbols)) / len(symbols) * 100)
        sync_record.processed_symbols = min(i + batch_size, len(symbols))
        sync_record.save()

    # Save to Database
    failed_msg = f" ({total_failed} failed)" if total_failed > 0 else ""
    print(f"[Sync] Đã xử lý {len(all_results)}/{len(symbols)} mã thành công{failed_msg}")
    saved_count = save_results_to_db(all_results)

    # Validation: Top 5 by F-Score
    if all_results:
        valid_fscore = [r for r in all_results if r.get('f_score', 0) > 0]
        if valid_fscore:
            top_fscore = sorted(valid_fscore, key=lambda x: x.get('f_score') or 0, reverse=True)[:5]
            print(f"[Sync] Top 5 by F-Score:")
            for r in top_fscore:
                print(f"  {r['symbol']}: F={r.get('f_score')}, ROE={r.get('roe')}, PE={r.get('pe')}, PB={r.get('pb')}")

        # Top 5 by Volume Ratio (for FAST picks)
        non_vetoed = [r for r in all_results if not r.get('is_vetoed')]
        if non_vetoed:
            top_vol = sorted(non_vetoed, key=lambda x: x.get('volume_ratio') or 0, reverse=True)[:5]
            print(f"[Sync] Top 5 by Volume Ratio:")
            for r in top_vol:
                print(f"  {r['symbol']}: VolRatio={r.get('volume_ratio')}, Score={r.get('master_score')}")

    elapsed = (datetime.now() - start_time).total_seconds()

    sync_record.status = "completed"
    sync_record.completed_at = timezone.now()
    sync_record.save()

    result = {
        "status": "success",
        "mode": mode,
        "total": len(all_results),
        "saved": saved_count,
        "market_rsi": market_rsi,
        "elapsed_seconds": elapsed,
    }

    print(f"[Sync] Completed in {elapsed:.1f}s. Saved {saved_count}/{len(all_results)} results")
    return result


def save_results_to_db(results: List[Dict[str, Any]]) -> int:
    """Lưu kết quả vào Database"""
    saved = 0

    # Get VN30 list
    try:
        from vnstock_data import Reference
        ref = Reference()
        vn30_list = list(ref.equity.list_by_group(group="VN30")['symbol'].str.upper())
    except:
        vn30_list = list(VN30_SYMBOLS)

    for data in results:
        try:
            symbol = data["symbol"]
            industry = data.get("industry", "")
            market_group = "VN30" if symbol in vn30_list else ("MIDCAP" if data.get("avg_volume_value", 0) >= 5 else "SMALL")

            # Save StockData
            stock, _ = StockData.objects.update_or_create(
                symbol=symbol,
                defaults={
                    "company_name": data.get("company_name", symbol),
                    "industry": industry,
                    "market_group": market_group,
                    "price": data["price"],
                    "change_percent": data["change_percent"],
                    "volume": data["volume"],
                    "avg_volume_value": data.get("avg_volume_value", 0),
                    "rsi": data["rsi"],
                    "adx": data["adx"],
                    "plus_di": data["plus_di"],
                    "minus_di": data["minus_di"],
                    "cmf": data["cmf"],
                    "atr": data["atr"],
                    "sma_10": data["sma_10"],
                    "sma_20": data["sma_20"],
                    "sma_50": data["sma_50"],
                    "bb_upper": data["bb_upper"],
                    "bb_middle": data["bb_middle"],
                    "bb_lower": data["bb_lower"],
                    "bb_percent": data["bb_percent"],
                    "macd": data["macd"],
                    "macd_signal": data["macd_signal"],
                    "volume_ratio": data["volume_ratio"],
                    # Advanced TA
                    "mfi": data.get("mfi", 50),
                    "vwap": data.get("vwap", 0),
                    "vwap_status": data.get("vwap_status", "neutral"),
                    "ichimoku_tenkan": data.get("ichimoku_tenkan", 0),
                    "ichimoku_kijun": data.get("ichimoku_kijun", 0),
                    "ichimoku_status": data.get("ichimoku_status", "neutral"),
                    "supertrend": data.get("supertrend", 0),
                    "supertrend_signal": data.get("supertrend_signal", "neutral"),
                    # Fundamental
                    "pe": data.get("pe"),
                    "pb": data.get("pb"),
                    "roe": data.get("roe"),
                    "f_score": data.get("f_score", 0),
                    "profit_growth": data.get("profit_growth"),  # NEW
                }
            )

            # Save StockAnalysis
            StockAnalysis.objects.update_or_create(
                symbol=stock,
                defaults={
                    "master_score": data["master_score"],
                    "base_master_score": data.get("base_master_score", data["master_score"]),
                    "market_weight": data.get("market_weight", 0),
                    "technical_score": data["technical_score"],
                    "fundamental_score": data["fundamental_score"],
                    "signal": data["signal"],
                    "entry_price": data["entry_price"],
                    "stop_loss": data["stop_loss"],
                    "trailing_sl": data.get("trailing_sl", 0),
                    "take_profit": data["take_profit"],
                    "risk_reward_ratio": data["risk_reward_ratio"],
                    "rr_quality": data.get("rr_quality", ""),
                    "rr_quality_detail": data.get("rr_quality_detail", ""),
                    "rr_warning": data.get("rr_warning", ""),
                    "is_vetoed": data["is_vetoed"],
                    "veto_reason": data["veto_reason"],
                    "is_fast_pick": data["is_fast_pick"],
                    "is_short_term_qualified": data["is_short_term_qualified"],
                    "is_slow_mode": data["is_slow_mode"],
                    "is_high_risk": data["is_high_risk"],
                    "is_market_high_risk": data.get("is_market_high_risk", False),
                    "stock_risk_level": data.get("stock_risk_level", "Medium"),
                    "stock_risk_reason": data.get("stock_risk_reason", ""),
                    "has_inverted_sl": data["has_inverted_sl"],
                    "is_inverted_risk": data.get("is_inverted_risk", False),
                    # New fields
                    "is_safe_entry": data.get("is_safe_entry", False),
                    "has_high_resistance": data.get("has_high_resistance", False),
                    "avg_volume_value": data.get("avg_volume_value", 0),
                    "trend_factor": data.get("trend_factor", 0.6),
                    # Smart Money & Industry
                    "foreign_buy_streak": data.get("foreign_buy_streak", 0),
                    "foreign_bonus": data.get("foreign_bonus", 0),
                    "industry_performance": data.get("industry_performance", 0),
                    "is_industry_leader": data.get("is_industry_leader", True),
                    # Real R:R
                    "hard_risk_pct": data.get("hard_risk_pct", 0),
                    "support_price": data.get("support_price", 0),
                    # P/E Industry & Early Exit
                    "pe_industry_avg": data.get("pe_industry_avg", 0),
                    "early_exit_trigger_pct": data.get("early_exit_trigger_pct", 2.0),
                    "early_exit_drop_pct": data.get("early_exit_drop_pct", 0.7),
                    "optimal_position_size": data.get("optimal_position_size", 0),
                    "account_balance": data.get("account_balance", 100_000_000),
                    "risk_tolerance_pct": data.get("risk_tolerance_pct", 2.0),
                    "estimated_days_to_target": data["estimated_days_to_target"],
                    "timeframe_label": data.get("timeframe_label", ""),
                    "timeframe_color": data.get("timeframe_color", ""),
                    "expected_profit_per_day": data.get("expected_profit_per_day", 0),
                    "upside_per_day": data.get("upside_per_day", 0),
                    "target_yield_pct": data.get("target_yield_pct", 0),
                    "criteria_met": data["criteria_met"],
                    "criteria_list": data["criteria_list"],
                    "recommendation_label": data.get("recommendation_label", ""),
                    # Fair Value (v10.3 - Dynamic Sector Valuation)
                    "fv_daily": data.get("fv_daily", 0),
                    "fv_weekly": data.get("fv_weekly", 0),
                    "valuation_status": data.get("valuation_status", "N/A"),
                    "intrinsic_value": data.get("intrinsic_value", 0),
                    "sector_median_pe": data.get("sector_median_pe", 0),
                    "valuation_source": data.get("valuation_source", "static"),
                    "valuation_cap_applied": data.get("valuation_cap_applied", False),
                    "trend": data["trend"],
                    "breakout_status": data["breakout_status"],
                    "market_rsi": data["market_rsi"],
                }
            )
            saved += 1

        except Exception as e:
            print(f"[Sync] Error saving {data.get('symbol')}: {e}")

    return saved


def get_top_picks_from_db(limit: int = 5) -> List[Dict[str, Any]]:
    """Lấy top picks từ Database - SORTED by Profit/Day for best efficiency"""
    from django.db.models import F, ExpressionWrapper, FloatField  # pyright: ignore[reportMissingImports]

    # Get non-vetoed stocks, calculate profit_per_day and sort by it
    # Profit/Day = (take_profit - entry_price) / estimated_days_to_target / entry_price * 100
    analyses = StockAnalysis.objects.select_related("symbol").filter(
        is_vetoed=False,
        estimated_days_to_target__gt=0
    ).annotate(
        profit_per_day_calc=ExpressionWrapper(
            F('take_profit') - F('entry_price'),
            output_field=FloatField()
        )
    ).order_by(
        '-profit_per_day_calc',
        '-master_score'
    )[:limit]

    picks = []
    for a in analyses:
        s = a.symbol
        # Use target_yield_pct from DB if available, otherwise calculate
        target_yield_pct = a.target_yield_pct if a.target_yield_pct else round((a.take_profit - (a.entry_price or s.price)) / (a.entry_price or s.price) * 100, 2) if a.take_profit and (a.entry_price or s.price) > 0 else 0
        days = a.estimated_days_to_target or 1
        profit_per_day = round(target_yield_pct / days, 2) if days > 0 else 0
        
        picks.append({
            "symbol": s.symbol,
            "company_name": s.company_name,
            "price": s.price,
            "change_percent": s.change_percent,
            # Target Yield
            "target_yield_pct": target_yield_pct,
            "profit_per_day": profit_per_day,
            # Technical
            "rsi": s.rsi,
            "adx": s.adx,
            "volume_ratio": s.volume_ratio,
            "cmf": s.cmf,
            "atr": s.atr,
            # Scores
            "master_score": a.master_score,
            "technical_score": a.technical_score,
            "fundamental_score": a.fundamental_score,
            "signal": a.signal,
            "risk_reward_ratio": a.risk_reward_ratio,
            "is_fast_pick": a.is_fast_pick,
            "criteria_met": a.criteria_met,
            "criteria_list": a.criteria_list,
            "trend": a.trend,
            "breakout_status": a.breakout_status,
            # Trading Levels
            "entry_price": a.entry_price,
            "stop_loss": a.stop_loss,
            "take_profit": a.take_profit,
            "estimated_days_to_target": a.estimated_days_to_target,
            "timeframe_label": a.timeframe_label,
            "timeframe_color": a.timeframe_color,
            # Risk
            "is_high_risk": a.is_high_risk,
            "is_market_high_risk": getattr(a, 'is_market_high_risk', False),
            "stock_risk_level": getattr(a, 'stock_risk_level', 'Medium'),
            # Meta
            "market_rsi": a.market_rsi,
            "profit_growth": getattr(s, 'profit_growth', None),
            # Extra for criteria check
            "plus_di": s.plus_di,
            "minus_di": s.minus_di,
            "macd": s.macd,
            "macd_signal": s.macd_signal,
            "sma_20": s.sma_20,
        })

    return picks


def get_sync_status() -> Optional[Dict[str, Any]]:
    """Lấy trạng thái sync cuối cùng"""
    try:
        sync = SyncStatus.objects.get(id=1)
        return {
            "status": sync.status,
            "is_running": sync.is_running,
            "progress_percent": sync.progress_percent,
            "total_symbols": sync.total_symbols,
            "processed_symbols": sync.processed_symbols,
            "started_at": str(sync.started_at) if sync.started_at else None,
            "completed_at": str(sync.completed_at) if sync.completed_at else None,
            "error_message": sync.error_message,
        }
    except:
        return None


def diagnose_stock(symbol: str) -> Dict[str, Any]:
    """
    Diagnostic tool cho một mã cổ phiếu - Single Stock Test Mode
    
    Chạy full sync pipeline cho một mã và trả về chi tiết tất cả các bước:
    - Raw data từ API
    - Valuation info (từ DB hay Config)
    - Computed FV Daily/Weekly
    - Criteria passed/failed
    - VETO reasons (if any)
    
    Args:
        symbol: Mã cổ phiếu cần diagnose
        
    Returns:
        Dict chứa chi tiết đầy đủ của quá trình tính toán
    """
    print(f"\n{'='*80}")
    print(f"🔍 DIAGNOSTIC REPORT: {symbol}")
    print(f"{'='*80}\n")
    
    result = {
        "symbol": symbol.upper(),
        "timestamp": datetime.now().isoformat(),
        "steps": {},
        "summary": {}
    }
    
    try:
        # ========== STEP 1: Get Raw Technical Data ==========
        print("[1/5] Fetching technical data...")
        result["steps"]["technical"] = {}
        
        try:
            from vnstock import Quote
            q = Quote(symbol=symbol, source="vci")
            df = q.history(
                start=(datetime.now() - pd.Timedelta(days=90)).strftime("%Y-%m-%d"),
                end=datetime.now().strftime("%Y-%m-%d"),
                interval="1D"
            )
            
            if df is not None and len(df) > 0:
                tech = calculate_technical_indicators(df)
                result["steps"]["technical"]["status"] = "success"
                result["steps"]["technical"]["raw_data"] = {
                    "price": float(df['close'].iloc[-1]),
                    "volume": int(df['volume'].iloc[-1]),
                    "rows": len(df)
                }
                result["steps"]["technical"]["indicators"] = tech
                print(f"  ✅ Price: {tech.get('price')}, RSI: {tech.get('rsi')}, CMF: {tech.get('cmf')}")
            else:
                result["steps"]["technical"]["status"] = "error"
                result["steps"]["technical"]["error"] = "No data returned"
                print(f"  ❌ No data returned")
                return result
        except Exception as e:
            result["steps"]["technical"]["status"] = "error"
            result["steps"]["technical"]["error"] = str(e)
            print(f"  ❌ Error: {e}")
            return result
        
        # ========== STEP 2: Get Raw Fundamental Data ==========
        print("[2/5] Fetching fundamental data...")
        result["steps"]["fundamental"] = {}
        
        try:
            fund_data = get_fundamental_data(symbol, fast_mode=False)
            result["steps"]["fundamental"]["status"] = "success"
            result["steps"]["fundamental"]["raw_data"] = {
                "roe": fund_data.get("roe"),
                "pe": fund_data.get("pe"),
                "pb": fund_data.get("pb"),
                "f_score": fund_data.get("f_score"),
                "industry": fund_data.get("industry"),
                "profit_growth": fund_data.get("profit_growth")
            }
            print(f"  ✅ ROE: {fund_data.get('roe')}, PE: {fund_data.get('pe')}, PB: {fund_data.get('pb')}")
            print(f"  ✅ F-Score: {fund_data.get('f_score')}, Industry: {fund_data.get('industry')}")
        except Exception as e:
            result["steps"]["fundamental"]["status"] = "error"
            result["steps"]["fundamental"]["error"] = str(e)
            print(f"  ❌ Error: {e}")
            fund_data = {}
        
        # ========== STEP 3: Get Market RSI ==========
        print("[3/5] Fetching market RSI...")
        result["steps"]["market"] = {}
        
        market_rsi = get_market_rsi()
        result["steps"]["market"]["status"] = "success"
        result["steps"]["market"]["data"] = {"vnindex_rsi": market_rsi}
        print(f"  ✅ VNIndex RSI: {market_rsi}")
        
        # ========== STEP 4: Valuation Info ==========
        print("[4/5] Analyzing valuation...")
        result["steps"]["valuation"] = {}
        
        industry = fund_data.get('industry', 'Default')
        industry_key = next((k for k in INDUSTRY_CONFIG if k.lower() in industry.lower()), 'Default')
        
        # Get from IndustryValuation DB
        db_valuation = None
        try:
            iv = IndustryValuation.objects.filter(name=industry_key, is_active=True).first()
            if iv:
                db_valuation = {
                    "name": iv.name,
                    "median_pe": iv.median_pe,
                    "median_pb": iv.median_pb,
                    "stock_count": iv.stock_count,
                    "source": "database"
                }
        except:
            pass
        
        # Get from Config
        config_val = INDUSTRY_CONFIG.get(industry_key, INDUSTRY_CONFIG['Default'])
        
        # Get resolved valuation
        val_config = get_target_valuation(industry_key)
        
        result["steps"]["valuation"]["industry"] = industry_key
        result["steps"]["valuation"]["database_valuation"] = db_valuation
        result["steps"]["valuation"]["config_valuation"] = config_val
        result["steps"]["valuation"]["resolved"] = val_config
        
        print(f"  Industry: {industry_key}")
        print(f"  Database Median PE: {db_valuation.get('median_pe') if db_valuation else 'N/A'}")
        print(f"  Config Target: {config_val.get('target')}")
        print(f"  Resolved Target: {val_config.get('target')} (Source: {val_config.get('source')})")
        print(f"  Wealth Guard Cap Applied: {val_config.get('cap_applied')}")
        
        # ========== STEP 5: Compute Core Logic ==========
        print("[5/5] Running core computation...")
        result["steps"]["computation"] = {}
        
        try:
            # Get market group
            try:
                stock = StockData.objects.get(symbol=symbol.upper())
                market_group = stock.market_group or "UNKNOWN"
            except:
                market_group = "UNKNOWN"
            
            analysis = compute_core_logic(
                symbol=symbol,
                tech=tech,
                fund_data=fund_data,
                market_rsi=market_rsi,
                market_group=market_group,
                df=df if 'df' in dir() else None
            )
            
            result["steps"]["computation"]["status"] = "success"
            result["steps"]["computation"]["analysis"] = analysis
            
            print(f"\n  📊 COMPUTED VALUES:")
            print(f"  ├── FV Daily: {analysis.get('fv_daily')}")
            print(f"  ├── FV Weekly: {analysis.get('fv_weekly')}")
            print(f"  ├── Intrinsic Value: {analysis.get('intrinsic_value')}")
            print(f"  ├── Take Profit: {analysis.get('take_profit')}")
            print(f"  ├── Stop Loss: {analysis.get('stop_loss')}")
            print(f"  └── R:R Ratio: {analysis.get('risk_reward_ratio')}")
            
        except Exception as e:
            result["steps"]["computation"]["status"] = "error"
            result["steps"]["computation"]["error"] = str(e)
            print(f"  ❌ Error: {e}")
            import traceback
            traceback.print_exc()
        
        # ========== SUMMARY ==========
        print(f"\n{'='*80}")
        print("📋 SUMMARY")
        print(f"{'='*80}")
        
        if result["steps"].get("computation", {}).get("status") == "success":
            analysis = result["steps"]["computation"]["analysis"]
            
            print(f"\n  🎯 SIGNAL: {analysis.get('signal')}")
            print(f"  📈 MASTER SCORE: {analysis.get('master_score')}")
            print(f"  📉 TECH SCORE: {analysis.get('tech_score')}")
            print(f"  💰 FUND SCORE: {analysis.get('fund_score')}")
            
            # Criteria
            criteria_met = analysis.get('criteria_met', 0)
            criteria_list = analysis.get('criteria_list', [])
            print(f"\n  ✅ CRITERIA MET: {criteria_met}/12")
            if criteria_list:
                print(f"     {', '.join(criteria_list)}")
            
            # VETO
            is_vetoed = analysis.get('is_vetoed', False)
            veto_reason = analysis.get('veto_reason', '')
            print(f"\n  {'🚫 VETO' if is_vetoed else '✅ NO VETO'}")
            if is_vetoed:
                print(f"     Reason: {veto_reason}")
            
            # Fair Value Status
            print(f"\n  💵 VALUATION:")
            print(f"     Status: {analysis.get('valuation_status')}")
            print(f"     Source: {analysis.get('valuation_source')}")
            print(f"     Sector Median PE: {analysis.get('sector_median_pe')}")
            
            result["summary"] = {
                "signal": analysis.get('signal'),
                "master_score": analysis.get('master_score'),
                "is_vetoed": is_vetoed,
                "veto_reason": veto_reason,
                "fv_weekly": analysis.get('fv_weekly'),
                "valuation_status": analysis.get('valuation_status'),
                "valuation_source": analysis.get('valuation_source')
            }
        
        print(f"\n{'='*80}\n")
        
    except Exception as e:
        result["error"] = str(e)
        import traceback
        traceback.print_exc()
    
    return result
