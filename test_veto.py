import sys
sys.path.insert(0, r"d:\OneDrive\Desktop\Trading-1")
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'vnstock_web.settings'
import django
django.setup()
from dashboard.sync_service import analyze_stock

print("=" * 80)
print("TEST: Health VETO with 13 rules")
print("=" * 80)

for symbol in ['VCB', 'FPT', 'HPG', 'MWG', 'SSI']:
    print(f"\n{'='*50}")
    print(f">>> {symbol}")
    print(f"{'='*50}")
    result = analyze_stock(symbol, market_rsi=50.0, fast_mode=False)
    if result:
        print(f"  is_vetoed:    {result.get('is_vetoed')}")
        print(f"  veto_reason:  {result.get('veto_reason')}")
        print(f"  master_score: {result.get('master_score')}")
        print(f"  tech_score:   {result.get('technical_score')}")
        print(f"  fund_score:   {result.get('fundamental_score')}")
        print(f"  CMF:          {result.get('cmf')}")
        print(f"  RSI:          {result.get('rsi')}")
        print(f"  ADX:          {result.get('adx')}")
        print(f"  ROE:          {result.get('roe')}")
        print(f"  F-Score:      {result.get('f_score')}")
        print(f"  ProfitGrowth: {result.get('profit_growth')}")
    else:
        print(f"  ERROR: No result")
