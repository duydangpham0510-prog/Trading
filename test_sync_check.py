"""
Quick test to check how many stocks are saved after sync
"""
import sys
import os

sys.path.insert(0, r"d:\OneDrive\Desktop\Trading-1")
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vnstock_web.settings')

import django
django.setup()

from dashboard.models import StockData, StockAnalysis, SyncStatus
from dashboard.sync_service import _get_top_100_by_liquidity, sync_stock_batch, get_market_rsi

def check_sync_results():
    print("=" * 60)
    print("SYNC RESULTS CHECK")
    print("=" * 60)
    
    # Check current DB
    stock_count = StockData.objects.count()
    analysis_count = StockAnalysis.objects.count()
    print(f"\n[DB] Current stocks in DB: {stock_count}")
    print(f"[DB] Current analyses in DB: {analysis_count}")
    
    # Check SyncStatus
    try:
        sync_status = SyncStatus.objects.get(id=1)
        print(f"\n[SyncStatus]")
        print(f"  Status: {sync_status.status}")
        print(f"  Total: {sync_status.total_symbols}")
        print(f"  Processed: {sync_status.processed_symbols}")
        if sync_status.completed_at:
            print(f"  Completed: {sync_status.completed_at}")
    except Exception as e:
        print(f"[SyncStatus] Error: {e}")
    
    # Test _get_top_100_by_liquidity
    print(f"\n[TEST] Getting top 100 by liquidity...")
    try:
        symbols = _get_top_100_by_liquidity()
        print(f"[TEST] Got {len(symbols)} symbols")
        print(f"[TEST] First 10: {symbols[:10]}")
    except Exception as e:
        print(f"[TEST] Error getting symbols: {e}")
        return
    
    # Test sync_batch with first 20 symbols
    print(f"\n[TEST] Testing sync_batch with first 20 symbols...")
    try:
        market_rsi = get_market_rsi()
        print(f"[TEST] Market RSI: {market_rsi:.2f}")
        
        test_symbols = symbols[:20]
        print(f"[TEST] Testing with: {test_symbols}")
        
        result = sync_stock_batch(test_symbols, market_rsi, fast_mode=True)
        print(f"\n[TEST] Batch result:")
        print(f"  Results count: {len(result.get('results', []))}")
        print(f"  Failed count: {len(result.get('failed', []))}")
        print(f"  Failed symbols: {result.get('failed', [])}")
        
        if result.get('results'):
            print(f"\n[TEST] Sample results:")
            for r in result['results'][:3]:
                print(f"  - {r.get('symbol')}: score={r.get('master_score')}, signal={r.get('signal')}")
        
    except Exception as e:
        print(f"[TEST] Error in batch: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_sync_results()
