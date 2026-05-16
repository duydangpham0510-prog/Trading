import sys
sys.path.insert(0, r"d:\OneDrive\Desktop\Trading-1")
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'vnstock_web.settings'
import django
django.setup()
from dashboard.sync_service import analyze_stock

print("=" * 60)
print("TEST: Multiple stocks")
print("=" * 60)

for symbol in ['FPT', 'HPG', 'MWG', 'SSI', 'TCB']:
    print(f"\n>>> {symbol}")
    result = analyze_stock(symbol, market_rsi=50.0, fast_mode=False)
    if result:
        print(f"    is_vetoed: {result.get('is_vetoed')}")
        print(f"    veto_reason: {result.get('veto_reason')}")
        print(f"    master_score: {result.get('master_score')}")
        print(f"    tech_score: {result.get('technical_score')}")
        print(f"    fund_score: {result.get('fundamental_score')}")
        print(f"    profit_growth: {result.get('profit_growth')}")
        print(f"    profit_growth_note: {result.get('profit_growth_note')}")
        print(f"    ROE: {result.get('roe')}")
        print(f"    F-Score: {result.get('f_score')}")
    else:
        print(f"    ERROR: No result")
