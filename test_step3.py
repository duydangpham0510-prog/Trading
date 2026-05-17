import sys
sys.path.insert(0, r"d:\OneDrive\Desktop\Trading-1")
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'vnstock_web.settings'
import django
django.setup()
from dashboard.sync_service import analyze_stock

print("=" * 100)
print("TEST: Bước 3 - Risk Buffer & R:R Quality Grading")
print("=" * 100)

for symbol in ['HPG', 'VCB', 'FPT', 'SAB', 'HDB', 'NAB', 'MWG']:
    print(f"\n{'='*70}")
    print(f">>> {symbol}")
    print(f"{'='*70}")
    result = analyze_stock(symbol, market_rsi=50.0, fast_mode=False)
    if result:
        entry = result.get('entry_price', 0)
        stop_loss = result.get('stop_loss', 0)
        take_profit = result.get('take_profit', 0)
        fv_weekly = result.get('fv_weekly', 0)
        price = result.get('price', 0)
        rr = result.get('risk_reward_ratio', 0)
        risk_pct = result.get('risk_percent', 0)
        
        print(f"  Price:      {price:,.0f}")
        print(f"  Entry:      {entry:,.0f}")
        print(f"  Stop Loss:  {stop_loss:,.0f}")
        print(f"  Support:    {result.get('support_price', 0):,.0f}")
        print(f"  Risk %:     {risk_pct:.2f}%")
        print(f"  Take Profit: {take_profit:,.0f}")
        print(f"  FV Weekly:  {fv_weekly:,.0f}")
        print(f"  R:R Ratio:  {rr:.2f}")
        print(f"  R:R Quality: {result.get('rr_quality', '')}")
        print(f"  R:R Detail: {result.get('rr_quality_detail', '')}")
        print(f"  Valuation:  {result.get('valuation_status')}")
        print(f"  is_vetoed: {result.get('is_vetoed')}")
    else:
        print(f"  ERROR: No result")
