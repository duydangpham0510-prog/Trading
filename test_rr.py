import sys
sys.path.insert(0, r"d:\OneDrive\Desktop\Trading-1")
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'vnstock_web.settings'
import django
django.setup()
from dashboard.sync_service import analyze_stock

print("=" * 80)
print("TEST: R:R Ratio for 5 stocks")
print("=" * 80)

for symbol in ['AAB', 'SAB', 'HDB', 'NAB', 'MWG']:
    print(f"\n{'='*40}")
    print(f">>> {symbol}")
    print(f"{'='*40}")
    result = analyze_stock(symbol, market_rsi=50.0, fast_mode=False)
    if result:
        entry = result.get('entry_price', 0)
        stop_loss = result.get('stop_loss', 0)
        take_profit = result.get('take_profit', 0)
        atr = result.get('atr', 0)
        risk = entry - stop_loss if entry and stop_loss else 0
        rr = result.get('risk_reward_ratio', 0)
        
        print(f"  Entry:     {entry}")
        print(f"  Stop Loss: {stop_loss}")
        print(f"  Take Profit: {take_profit}")
        print(f"  ATR:       {atr}")
        print(f"  Risk (E-SL): {risk}")
        print(f"  Reward (TP-E): {take_profit - entry if entry else 0}")
        print(f"  R:R Ratio: {rr}")
        
        # Verify calculation
        if risk > 0 and entry > 0:
            calc_rr = round((take_profit - entry) / risk, 2)
            print(f"  Calc R:R:  {calc_rr}")
    else:
        print(f"  ERROR: No result")
