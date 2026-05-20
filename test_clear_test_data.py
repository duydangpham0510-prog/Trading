"""
Clear test data and prepare for real sync
"""
import sys
import os

sys.path.insert(0, r"d:\OneDrive\Desktop\Trading-1")
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vnstock_web.settings')

import django
django.setup()

from dashboard.models import StockData, StockAnalysis, SyncStatus
from django.utils import timezone

def clear_test_data():
    print("=" * 60)
    print("CLEAR TEST DATA")
    print("=" * 60)
    
    # 1. Delete TEST symbols
    print("\n[1] Deleting TEST symbols...")
    test_stocks = StockData.objects.filter(symbol__startswith='TEST')
    count = test_stocks.count()
    test_stocks.delete()
    print(f"    Deleted {count} TEST stocks")
    
    # Also delete any test analysis
    test_analysis = StockAnalysis.objects.filter(symbol__symbol__startswith='TEST')
    count2 = test_analysis.count()
    test_analysis.delete()
    print(f"    Deleted {count2} TEST analyses")
    
    # 2. Reset SyncStatus
    print("\n[2] Resetting SyncStatus...")
    sync, _ = SyncStatus.objects.get_or_create(id=1)
    sync.status = "idle"
    sync.total_symbols = 0
    sync.processed_symbols = 0
    sync.started_at = None
    sync.completed_at = None
    sync.save()
    print(f"    SyncStatus reset")
    
    # 3. Check remaining stocks
    print("\n[3] Remaining stocks in DB:")
    remaining = StockData.objects.count()
    print(f"    Total: {remaining}")
    
    if remaining > 0:
        print("\n    Sample stocks:")
        samples = StockData.objects.all()[:10]
        for s in samples:
            print(f"    - {s.symbol}: price={s.price}, industry={s.industry}")
    
    print("\n[4] Ready for full sync!")
    print("    Run sync from web UI: /top-picks/")

if __name__ == "__main__":
    clear_test_data()
