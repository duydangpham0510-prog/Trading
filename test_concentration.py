"""
Test script for Portfolio Concentration Warning System
"""

import os
import sys
import django

sys.path.insert(0, r'd:\OneDrive\Desktop\Trading-1')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vnstock_web.settings')
django.setup()

from dashboard.sync_service import get_top_picks_from_db, calculate_portfolio_health

print("=" * 70)
print("⚠️ PORTFOLIO CONCENTRATION WARNING SYSTEM - TEST")
print("=" * 70)

# Test 1: Real portfolio health
print("\n📊 Test 1: Real Portfolio Health")
print("-" * 70)

picks, health = get_top_picks_from_db(limit=10)

print(f"\n🎯 Top 10 Picks:")
for i, pick in enumerate(picks, 1):
    print(f"  {i:2}. {pick['symbol']:6} | {pick['industry']:20}")

print(f"\n📈 Sector Distribution:")
for sector, count in sorted(health['sector_distribution'].items(), key=lambda x: -x[1]):
    pct = health['concentration_pct'] if sector == health['concentrated_sector'] else count / health['total_picks'] * 100
    bar = "█" * count
    print(f"  {sector:20}: {count} {bar} ({pct:.1f}%)")

print(f"\n🛡️ Portfolio Health:")
print(f"  Risk Level: {health['risk_level']}")
print(f"  Concentration: {health['concentration_pct']}%")
if health['concentrated_sector']:
    print(f"  Concentrated Sector: {health['concentrated_sector']}")
if health['risk_message']:
    print(f"  ⚠️ {health['risk_message']}")
if health['suggested_sectors']:
    print(f"  💡 Suggested Sectors: {', '.join(health['suggested_sectors'])}")

# Test 2: Simulated high concentration
print("\n\n📊 Test 2: Simulated High Concentration (Banking)")
print("-" * 70)

simulated_counts = {
    "Banking": 6,
    "Real Estate": 2,
    "Technology": 2,
}
sim_health = calculate_portfolio_health(simulated_counts, 10)

print(f"\n🎯 Simulated Distribution:")
for sector, count in simulated_counts.items():
    bar = "█" * count
    print(f"  {sector:20}: {count} {bar}")

print(f"\n🛡️ Portfolio Health (Simulated):")
print(f"  Risk Level: {sim_health['risk_level']}")
print(f"  Concentration: {sim_health['concentration_pct']}%")
print(f"  Concentrated Sector: {sim_health['concentrated_sector']}")
if sim_health['risk_message']:
    print(f"  ⚠️ {sim_health['risk_message']}")
if sim_health['suggested_sectors']:
    print(f"  💡 Suggested Sectors (low correlation): {', '.join(sim_health['suggested_sectors'])}")

# Test 3: Diversified portfolio
print("\n\n📊 Test 3: Diversified Portfolio")
print("-" * 70)

div_counts = {
    "Banking": 2,
    "Real Estate": 2,
    "Technology": 2,
    "Retail": 2,
    "Utilities": 2,
}
div_health = calculate_portfolio_health(div_counts, 10)

print(f"\n🎯 Diversified Distribution:")
for sector, count in div_counts.items():
    bar = "█" * count
    print(f"  {sector:20}: {count} {bar}")

print(f"\n🛡️ Portfolio Health (Diversified):")
print(f"  Risk Level: {div_health['risk_level']}")
print(f"  Concentration: {div_health['concentration_pct']}%")
if div_health['risk_message']:
    print(f"  ⚠️ {div_health['risk_message']}")
else:
    print(f"  ✅ Portfolio is well diversified!")

print("\n" + "=" * 70)
print("✅ TEST COMPLETE")
print("=" * 70)
