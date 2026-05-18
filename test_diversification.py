"""
Test script for Sector Diversification (Portfolio Shield) - Detailed
"""

import os
import sys
import django

sys.path.insert(0, r'd:\OneDrive\Desktop\Trading-1')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vnstock_web.settings')
django.setup()

from dashboard.models import StockData, StockAnalysis

print("=" * 60)
print("🛡️ PORTFOLIO SHIELD - SECTOR DIVERSIFICATION TEST")
print("=" * 60)

# First, check what industries are in the database
print("\n📊 Checking Industries in Database:")
print("-" * 60)
industries = StockData.objects.values_list('industry', flat=True).distinct()
for ind in industries[:20]:
    count = StockData.objects.filter(industry=ind).count()
    print(f"  '{ind}': {count} stocks")

# Check a sample stock
sample = StockData.objects.first()
if sample:
    print(f"\n📌 Sample Stock: {sample.symbol}")
    print(f"   industry field: '{sample.industry}'")
    print(f"   get_industry(): '{sample.get_industry()}'")

# Now test get_top_picks_from_db
from dashboard.sync_service import get_top_picks_from_db

print("\n" + "=" * 60)
print("📊 Top 10 Picks (with Sector Cap = 3):")
print("-" * 60)

picks = get_top_picks_from_db(limit=10)

# Track sector counts
sector_counts = {}
for i, pick in enumerate(picks, 1):
    industry = pick.get('industry', 'Unknown')
    sector_counts[industry] = sector_counts.get(industry, 0) + 1
    
    print(f"{i:2}. {pick['symbol']:6} | Industry: '{industry}' | Score: {pick['master_score']:3}")

print("\n" + "-" * 60)
print("📈 Sector Distribution:")
for sector, count in sorted(sector_counts.items(), key=lambda x: -x[1]):
    bar = "█" * count
    print(f"  '{sector}'".ljust(30) + f": {count} {bar}")

# Verify no sector exceeds 3
violations = [s for s, c in sector_counts.items() if c > 3]
if violations:
    print(f"\n❌ VIOLATION: {violations} exceed MAX_STOCKS_PER_SECTOR=3")
else:
    print(f"\n✅ PASS: All sectors within MAX_STOCKS_PER_SECTOR=3 limit")

print("=" * 60)
