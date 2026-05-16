import sys
sys.path.insert(0, '.')
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'vnstock_web.settings'

import django
django.setup()

from dashboard.sync_service import analyze_stock

print('=' * 60)
print('TEST: analyze_stock for VCB')
print('=' * 60)

result = analyze_stock('VCB', market_rsi=50.0, fast_mode=False)

if result:
    print()
    print('=== BASIC INFO ===')
    print(f"Symbol: {result.get('symbol')}")
    print(f"Price: {result.get('price')}")
    
    print()
    print('=== TECHNICAL ===')
    print(f"RSI: {result.get('rsi')}")
    print(f"ADX: {result.get('adx')}")
    print(f"CMF: {result.get('cmf')}")
    print(f"ATR: {result.get('atr')}")
    print(f"MFI: {result.get('mfi')}")
    
    print()
    print('=== TRADING LEVELS ===')
    print(f"Entry: {result.get('entry_price')}")
    print(f"Stop Loss: {result.get('stop_loss')}")
    print(f"Take Profit: {result.get('take_profit')}")
    print(f"R:R Ratio: {result.get('risk_reward_ratio')}")
    
    print()
    print('=== FUNDAMENTAL ===')
    print(f"ROE: {result.get('roe')}")
    print(f"P/E: {result.get('pe')}")
    print(f"P/B: {result.get('pb')}")
    print(f"F-Score: {result.get('f_score')}")
    print(f"F-Score Grade: {result.get('f_score_grade')}")
    
    print()
    print('=== PROFIT GROWTH (NEW) ===')
    print(f"Profit Growth: {result.get('profit_growth')}")
    print(f"Profit Growth Note: {result.get('profit_growth_note')}")
    print(f"Is New Listing: {result.get('is_new_listing')}")
    
    print()
    print('=== SCORES ===')
    print(f"Master Score: {result.get('master_score')}")
    print(f"Technical Score: {result.get('technical_score')}")
    print(f"Fundamental Score: {result.get('fundamental_score')}")
    
    print()
    print('=== VETO STATUS ===')
    print(f"Is Vetoed: {result.get('is_vetoed')}")
    print(f"Veto Reason: {result.get('veto_reason')}")
    
    print()
    print('=== FAIR VALUE ===')
    print(f"FV Daily: {result.get('fv_daily')}")
    print(f"FV Weekly: {result.get('fv_weekly')}")
    print(f"Valuation Status: {result.get('valuation_status')}")
    print(f"Intrinsic Value: {result.get('intrinsic_value')}")
    
    print()
    print('=== INDUSTRY & FOREIGN ===')
    print(f"Industry Performance: {result.get('industry_performance')}")
    print(f"Foreign Buy Streak: {result.get('foreign_buy_streak')}")
    print(f"P/E Industry Avg: {result.get('pe_industry_avg')}")
    
    print()
    print('=== SIGNAL ===')
    print(f"Signal: {result.get('signal')}")
    print(f"Trend: {result.get('trend')}")
    print(f"Breakout Status: {result.get('breakout_status')}")
    
    print()
    print('=' * 60)
    print('TEST COMPLETE')
    print('=' * 60)
else:
    print('Error: No result returned')
