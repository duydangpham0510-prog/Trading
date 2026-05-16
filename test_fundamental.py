import sys
sys.path.insert(0, '.')
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'vnstock_web.settings'

import django
django.setup()

from dashboard.sync_service import get_fundamental_data

print('=' * 60)
print('TEST: get_fundamental_data for VCB')
print('=' * 60)

result = get_fundamental_data('VCB', fast_mode=False)

print()
print('=== RESULT ===')
for key, value in result.items():
    print(f"{key}: {value}")

print()
print('=' * 60)

# Also try directly with vnstock_data
print()
print('=== TEST DIRECT vnstock_data ===')
try:
    from vnstock_data import Fundamental
    fun = Fundamental()
    ratios = fun.equity('VCB').ratio()
    print(f"Ratios type: {type(ratios)}")
    print(f"Ratios shape: {ratios.shape if hasattr(ratios, 'shape') else 'N/A'}")
    print(f"Ratios columns: {list(ratios.columns)[:10]}...")
    print(f"First row:\n{ratios.iloc[0] if len(ratios) > 0 else 'Empty'}")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
