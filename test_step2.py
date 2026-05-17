import sys
sys.path.insert(0, r"d:\OneDrive\Desktop\Trading-1")
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'vnstock_web.settings'
import django
django.setup()
from dashboard.sync_service import analyze_stock

print("=" * 90)
print("TEST: Bước 2 - FV & R:R Thực Chiến")
print("=" * 90)

for symbol in ['VCB', 'FPT', 'HPG', 'MWG', 'SSI', 'SAB', 'HDB']:
    print(f"\n{'='*60}")
    print(f">>> {symbol}")
    print(f"{'='*60}")
    result = analyze_stock(symbol, market_rsi=50.0, fast_mode=False)
    if result:
        entry = result.get('entry_price', 0)
        stop_loss = result.get('stop_loss', 0)
        take_profit = result.get('take_profit', 0)  # Now = FV_weekly
        fv_daily = result.get('fv_daily', 0)
        fv_weekly = result.get('fv_weekly', 0)
        rr = result.get('risk_reward_ratio', 0)
        
        risk = entry - stop_loss
        calc_rr = round((take_profit - entry) / risk, 2) if risk > 0 else 0
        
        print(f"  Entry:      {entry:,.0f}")
        print(f"  Stop Loss:  {stop_loss:,.0f}")
        print(f"  Support:    {result.get('support_price', 0):,.0f}")
        print(f"  Take Profit (FV_weekly): {take_profit:,.0f}")
        print(f"  FV Daily:   {fv_daily:,.0f}")
        print(f"  FV Weekly:  {fv_weekly:,.0f}")
        print(f"  Risk:       {risk:,.0f}")
        print(f"  R:R Ratio:  {rr:.2f} (calc: {calc_rr:.2f})")
        print(f"  Inverted:   {result.get('is_inverted_risk', False)}")
        print(f"  is_vetoed:  {result.get('is_vetoed')}")
        print(f"  Valuation:  {result.get('valuation_status')}")
    else:
        print(f"  ERROR: No result")
