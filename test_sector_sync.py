import sys
sys.path.insert(0, r"d:\OneDrive\Desktop\Trading-1")
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'vnstock_web.settings'
import django
django.setup()

from dashboard.sync_service import sync_sector_benchmarks, get_target_valuation

print("=" * 80)
print("TEST: Dynamic Sector Valuation (v10.3)")
print("=" * 80)

# Test 1: Sync sector benchmarks
print("\n>>> TEST 1: sync_sector_benchmarks()")
result = sync_sector_benchmarks()
print(f"Success: {result['success']}")
print(f"Sectors synced: {result['sectors_synced']}")
if result['errors']:
    print(f"Errors: {result['errors']}")

# Test 2: Get target valuation for different industries
print("\n>>> TEST 2: get_target_valuation()")
for industry in ['Banking', 'Technology', 'Steel', 'Real Estate', 'Retail']:
    val = get_target_valuation(industry)
    print(f"\n  {industry}:")
    print(f"    Type: {val['type']}")
    print(f"    Target: {val['target']:.2f}")
    print(f"    Dynamic Median: {val['dynamic']:.2f}")
    print(f"    Static Target: {val['static']:.2f}")
    print(f"    Source: {val['source']}")
    print(f"    Cap Applied: {val['cap_applied']}")
