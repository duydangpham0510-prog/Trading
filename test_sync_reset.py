"""
Reset SyncStatus and run full sync to verify everything works
"""
import sys
import os

sys.path.insert(0, r"d:\OneDrive\Desktop\Trading-1")
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vnstock_web.settings')

import django
django.setup()

from dashboard.models import StockData, StockAnalysis, SyncStatus
from django.utils import timezone

def reset_and_sync():
    print("=" * 60)
    print("RESET SYNC AND RUN")
    print("=" * 60)
    
    # 1. Reset SyncStatus
    print("\n[1] Resetting SyncStatus...")
    sync, _ = SyncStatus.objects.get_or_create(
        id=1,
        defaults={
            "status": "idle",
            "total_symbols": 0,
            "processed_symbols": 0,
            "started_at": None,
            "completed_at": None
        }
    )
    sync.status = "idle"
    sync.processed_symbols = 0
    sync.completed_at = None
    sync.save()
    print(f"    SyncStatus reset: status={sync.status}")
    
    # 2. Check DB counts
    print("\n[2] Current DB state:")
    stock_count = StockData.objects.count()
    analysis_count = StockAnalysis.objects.count()
    print(f"    StockData: {stock_count}")
    print(f"    StockAnalysis: {analysis_count}")
    
    # 3. Show top stocks by master_score
    print("\n[3] Top 10 stocks by master_score:")
    top_stocks = StockAnalysis.objects.select_related('symbol').order_by('-master_score')[:10]
    for i, a in enumerate(top_stocks, 1):
        print(f"    {i}. {a.symbol.symbol}: score={a.master_score}, signal={a.signal}, veto={a.is_vetoed}")
    
    # 4. Show some sample data
    print("\n[4] Sample saved data (HPG):")
    try:
        hpg = StockData.objects.get(symbol='HPG')
        hpg_analysis = StockAnalysis.objects.get(symbol=hpg)
        print(f"    Price: {hpg.price}")
        print(f"    RSI: {hpg.rsi}")
        print(f"    Master Score: {hpg_analysis.master_score}")
        print(f"    Signal: {hpg_analysis.signal}")
        print(f"    Is Vetoed: {hpg_analysis.is_vetoed}")
    except Exception as e:
        print(f"    Error: {e}")
    
    print("\n[5] Ready for next sync!")
    print("    - Clear previous sync if needed")
    print("    - Run sync from web UI or API")

if __name__ == "__main__":
    reset_and_sync()
