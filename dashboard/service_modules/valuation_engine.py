"""
ValuationEngine - Centralized Fair Value Calculation Service
============================================================

Module này chứa tất cả logic tính toán FV Daily, FV Weekly, Intrinsic Value
Dùng chung cho cả sync_service.py (background) và views.py (CSV/Web export)
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import pandas as pd


@dataclass
class ValuationResult:
    """Kết quả định giá"""
    fv_daily: float
    fv_weekly: float
    intrinsic_value: float
    target_pe: float
    valuation_type: str
    valuation_source: str  # 'dynamic' or 'static'
    sector_median_pe: float
    sector_median_pb: float
    cap_applied: bool
    valuation_status: str  # 'Rẻ', 'Đắt', 'RISK'


class ValuationService:
    """
    Centralized valuation logic - KHÔNG gọi API
    Chỉ nhận dữ liệu đã lấy và trả về kết quả tính toán
    """
    
    # Wealth Guard Cap multiplier
    WEALTH_GUARD_CAP = 1.25
    
    # Fallback config khi không có dynamic data
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
    
    def __init__(self):
        """Import IndustryValuation lazily để tránh circular import"""
        self._industry_valuation_model = None
    
    @property
    def IndustryValuation(self):
        """Lazy import để tránh circular dependency"""
        if self._industry_valuation_model is None:
            from dashboard.models import IndustryValuation
            self._industry_valuation_model = IndustryValuation
        return self._industry_valuation_model
    
    def get_industry_key(self, industry_name: str) -> str:
        """Normalize industry name để match với config"""
        if not industry_name:
            return 'Default'
        
        industry_lower = industry_name.lower()
        for key in self.INDUSTRY_CONFIG.keys():
            if key.lower() in industry_lower or industry_lower in key.lower():
                return key
        return 'Default'
    
    def get_sector_median(self, industry_name: str) -> Dict[str, float]:
        """
        Lấy Median P/E và P/B từ database IndustryValuation
        
        Returns:
            Dict với 'median_pe', 'median_pb', 'stock_count', 'source'
        """
        industry_key = self.get_industry_key(industry_name)
        
        try:
            iv = self.IndustryValuation.objects.filter(
                name=industry_key,
                is_active=True
            ).first()
            
            if iv and (iv.median_pe > 0 or iv.median_pb > 0):
                return {
                    'median_pe': iv.median_pe,
                    'median_pb': iv.median_pb,
                    'stock_count': iv.stock_count,
                    'source': 'database',
                    'industry_name': iv.name
                }
        except Exception:
            pass
        
        # Fallback về config
        return {
            'median_pe': 0,
            'median_pb': 0,
            'stock_count': 0,
            'source': 'config',
            'industry_name': industry_key
        }
    
    def get_target_valuation(self, industry_name: str) -> ValuationResult:
        """
        Tính toán target valuation cho một ngành
        
        Priority:
        1. Dynamic Median từ IndustryValuation (database)
        2. Fallback sang INDUSTRY_CONFIG (static)
        3. Wealth Guard Cap: Final = min(Dynamic, Static * 1.25)
        """
        industry_key = self.get_industry_key(industry_name)
        static_config = self.INDUSTRY_CONFIG.get(industry_key, self.INDUSTRY_CONFIG['Default'])
        static_target = static_config.get('target', 11.0)
        val_type = static_config.get('type', 'PE')
        
        # Lấy dynamic data từ database
        sector_data = self.get_sector_median(industry_name)
        dynamic_pe = sector_data.get('median_pe', 0)
        dynamic_pb = sector_data.get('median_pb', 0)
        
        # Determine final target với Wealth Guard Cap
        cap_applied = False
        if val_type == 'PB':
            if dynamic_pb > 0:
                final_target = min(dynamic_pb, static_target * self.WEALTH_GUARD_CAP)
                cap_applied = final_target != dynamic_pb
            else:
                final_target = static_target
                dynamic_pb = static_target
        else:  # PE
            if dynamic_pe > 0:
                final_target = min(dynamic_pe, static_target * self.WEALTH_GUARD_CAP)
                cap_applied = final_target != dynamic_pe
            else:
                final_target = static_target
                dynamic_pe = static_target
        
        return ValuationResult(
            fv_daily=0,  # Sẽ được tính trong compute_fair_value
            fv_weekly=0,
            intrinsic_value=0,
            target_pe=round(final_target, 2),
            valuation_type=val_type,
            valuation_source=sector_data['source'],
            sector_median_pe=round(dynamic_pe, 2),
            sector_median_pb=round(dynamic_pb, 2),
            cap_applied=cap_applied,
            valuation_status='N/A'
        )
    
    def compute_fair_value(
        self,
        price: float,
        tech: Dict[str, Any],
        fund_data: Dict[str, Any],
        market_rsi: float = 50.0,
        is_vetoed: bool = False,
        industry: str = ""
    ) -> ValuationResult:
        """
        Tính Fair Value Daily và Weekly (SECTOR-AWARE V3)
        
        Growth Sectors (Tech, Retail, FMCG): PEG = 1.0 logic
        Financial Sectors (Banking, Securities): P/B Forward vs Historical Median
        
        Args:
            price: Giá hiện tại
            tech: Dict chứa indicators (vwap, sma_20, high_52w, v.v.)
            fund_data: Dict chứa PE, PB, industry, profit_growth
            market_rsi: RSI thị trường
            is_vetoed: Cổ phiếu có bị VETO không
            industry: Ngành của cổ phiếu (để xác định valuation method)
        
        Returns:
            ValuationResult với đầy đủ thông tin định giá
        """
        if price <= 0:
            return ValuationResult(
                fv_daily=0, fv_weekly=0, intrinsic_value=0,
                target_pe=0, valuation_type='PE',
                valuation_source='error', sector_median_pe=0,
                sector_median_pb=0, cap_applied=False, valuation_status='RISK'
            )
        
        # Determine sector category
        from dashboard.sync_service import get_sector_category
        sector = get_sector_category(industry)
        
        # Get industry và valuation config
        industry_key = self.get_industry_key(industry)
        val_result = self.get_target_valuation(industry)
        
        # FV Daily: (VWAP * 0.4) + (SMA20 * 0.6) - unchanged
        vwap_val = tech.get('vwap', price)
        sma20_val = tech.get('sma_20', price)
        fv_daily = round((vwap_val * 0.4) + (sma20_val * 0.6), 2)
        
        # ===== SECTOR-AWARE INTRINSIC VALUE CALCULATION =====
        
        actual_pe = fund_data.get('pe') or 0
        actual_pb = fund_data.get('pb') or 0
        profit_growth = fund_data.get('profit_growth') or 0
        
        if sector == 'banking':
            # Banking: P/B Forward vs Historical Median
            # FV = Price * (Historical P/B Median / Current P/B)
            if actual_pb > 0:
                historical_pb = val_result.sector_median_pb or 1.5
                intrinsic_value = price * (historical_pb / actual_pb)
                val_result.valuation_type = 'PB'
            else:
                intrinsic_value = price
                
        elif sector in ['retail', 'manufacturing']:
            # Growth Sectors: PEG = 1.0 Logic
            # PEG = P/E / Earnings Growth Rate
            # FV = Price where PEG = 1.0 => FV = Price * (ExpectedGrowth / ActualGrowth)
            # Simplified: FV = Price * (IndustryPEG / SectorPEG)
            if actual_pe > 0 and profit_growth > 0:
                # Target PEG = 1.0 for fair value
                # Expected growth rate = industry median growth
                industry_growth = val_result.sector_median_pe or 15  # Default 15% growth
                peg = actual_pe / profit_growth
                if peg > 1:
                    # Stock is expensive relative to growth -> FV should be lower
                    intrinsic_value = price / peg
                else:
                    # Stock is cheap relative to growth -> FV should be higher
                    target_pe = min(actual_pe, profit_growth)  # PEG = 1
                    intrinsic_value = price * (target_pe / actual_pe) if actual_pe > 0 else price
                val_result.valuation_type = 'PEG'
            elif actual_pe > 0:
                # No growth data, use P/E
                intrinsic_value = price * (val_result.target_pe / actual_pe) if actual_pe > 0 else price
                val_result.valuation_type = 'PE'
            else:
                intrinsic_value = price
                
        else:
            # General: P/E based valuation
            if actual_pe > 0:
                intrinsic_value = price * (val_result.target_pe / actual_pe)
            else:
                intrinsic_value = price
            val_result.valuation_type = 'PE'
        
        # 52-week high valuation (slightly adjusted for sector)
        high_52w = tech.get('high_52w', 0)
        if high_52w > 0:
            high_52w_valuation = high_52w
        else:
            high_52w_valuation = price * 1.20  # Fallback: +20%
        
        # FV Weekly = trung bình (Intrinsic + 52-week high)
        fv_weekly = (intrinsic_value + high_52w_valuation) / 2
        fv_weekly = round(fv_weekly, 2)
        
        # Cap FV_weekly at 130% of current price (adjusted for sector)
        max_fv = price * 1.30
        if fv_weekly > max_fv:
            fv_weekly = round(max_fv, 2)
        
        # Market Risk Adjustment: -10% when Market RSI > 75
        if market_rsi > 75:
            fv_weekly = round(fv_weekly * 0.9, 2)
        
        # Valuation Status
        if is_vetoed:
            valuation_status = 'RISK'
        else:
            safe_threshold = fv_weekly * 0.9
            valuation_status = 'Rẻ' if price < safe_threshold else 'Đắt'
        
        return ValuationResult(
            fv_daily=fv_daily,
            fv_weekly=fv_weekly,
            intrinsic_value=round(intrinsic_value, 2),
            target_pe=val_result.target_pe,
            valuation_type=val_result.valuation_type,
            valuation_source=val_result.valuation_source,
            sector_median_pe=val_result.sector_median_pe,
            sector_median_pb=val_result.sector_median_pb,
            cap_applied=val_result.cap_applied,
            valuation_status=valuation_status
        )
    
    def compute_all(
        self,
        symbol: str,
        tech: Dict[str, Any],
        fund_data: Dict[str, Any],
        market_rsi: float = 50.0,
        is_vetoed: bool = False
    ) -> Dict[str, Any]:
        """
        Tính toán tất cả valuation metrics cho một mã cổ phiếu
        
        Returns:
            Dict với đầy đủ thông tin để lưu vào database
        """
        price = tech.get('price', 0)
        
        val = self.compute_fair_value(
            price=price,
            tech=tech,
            fund_data=fund_data,
            market_rsi=market_rsi,
            is_vetoed=is_vetoed
        )
        
        return {
            'fv_daily': val.fv_daily,
            'fv_weekly': val.fv_weekly,
            'intrinsic_value': val.intrinsic_value,
            'valuation_status': val.valuation_status,
            'valuation_source': val.valuation_source,
            'valuation_cap_applied': val.cap_applied,
            'sector_median_pe': val.sector_median_pe,
            'sector_median_pb': val.sector_median_pb,
            'valuation_type': val.valuation_type,
            'target_pe': val.target_pe,
        }


# Singleton instance
_valuation_service: Optional[ValuationService] = None


def get_valuation_service() -> ValuationService:
    """Get singleton instance of ValuationService"""
    global _valuation_service
    if _valuation_service is None:
        _valuation_service = ValuationService()
    return _valuation_service


def compute_fair_value(
    price: float,
    tech: Dict[str, Any],
    fund_data: Dict[str, Any],
    market_rsi: float = 50.0,
    is_vetoed: bool = False
) -> ValuationResult:
    """Convenience function"""
    return get_valuation_service().compute_fair_value(price, tech, fund_data, market_rsi, is_vetoed)
