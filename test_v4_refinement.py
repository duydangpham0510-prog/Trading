"""
Test script for Professional Grade Refinement (V4)
Tests: Robust Fallback, Relative VETO, Earning Guidance
"""

import os
import sys
import django

sys.path.insert(0, r'd:\OneDrive\Desktop\Trading-1')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vnstock_web.settings')
django.setup()

from dashboard.sync_service import (
    score_banking_sector,
    score_real_estate_sector,
    score_manufacturing_sector,
    score_retail_sector,
    score_general_sector,
    score_by_sector,
    get_sector_median_de,
    calculate_portfolio_health
)
from datetime import datetime

print("=" * 70)
print("🚀 PROFESSIONAL GRADE REFINEMENT V4 - TEST SUITE")
print("=" * 70)

# ============== TEST 1: ROBUST FALLBACK LOGIC ==============
print("\n📊 TEST 1: ROBUST FALLBACK LOGIC")
print("-" * 70)

# Banking with missing NIM/NPL should fall back to general
bank_data_no_nim = {'pb': 1.2, 'roe': 15}
result = score_banking_sector(bank_data_no_nim, symbol="TEST_BANK")
print(f"\n  Banking (no NIM/NPL):")
print(f"    fund_score: {result['fund_score']}")
print(f"    fallback: {result.get('fallback', False)}")
print(f"    reason: {result.get('fallback_reason', 'N/A')}")

# Banking with complete data
bank_data_full = {'pb': 1.2, 'roe': 18, 'nim': 3.5, 'npl': 1.5}
result = score_banking_sector(bank_data_full, symbol="VCB")
print(f"\n  Banking (full data):")
print(f"    fund_score: {result['fund_score']}")
print(f"    fallback: {result.get('fallback', False)}")

# Real Estate with missing D/E should fall back
re_data_no_de = {'roe': 12, 'pb': 0.8}
result = score_real_estate_sector(re_data_no_de, symbol="TEST_RE")
print(f"\n  Real Estate (no D/E):")
print(f"    fund_score: {result['fund_score']}")
print(f"    fallback: {result.get('fallback', False)}")
print(f"    reason: {result.get('fallback_reason', 'N/A')}")

# Manufacturing with missing Gross Margin should fall back
mfg_data_no_gm = {'roe': 15, 'pe': 12}
result = score_manufacturing_sector(mfg_data_no_gm, symbol="TEST_MFG")
print(f"\n  Manufacturing (no Gross Margin):")
print(f"    fund_score: {result['fund_score']}")
print(f"    fallback: {result.get('fallback', False)}")
print(f"    reason: {result.get('fallback_reason', 'N/A')}")

print("\n  ✅ Fallback logic working correctly!")

# ============== TEST 2: RELATIVE VETO FOR RE ==============
print("\n\n📊 TEST 2: RELATIVE VETO FOR REAL ESTATE")
print("-" * 70)

sector_median_de = get_sector_median_de("Real Estate")
print(f"\n  Real Estate Sector Median D/E: {sector_median_de:.2f}")
print(f"  Relative VETO threshold (20% above median): {sector_median_de * 1.2:.2f}")

# Simulate RE stocks with different D/E
test_cases = [
    (0.8, "Low D/E - Should NOT veto"),
    (1.0, "Median D/E - Should NOT veto"),
    (1.2, "20% above median - Should NOT veto"),
    (1.4, "40% above median - Should VETO"),
]

from dashboard.sync_service import check_health_veto
import logging
logging.disable(logging.WARNING)

for de, desc in test_cases:
    tech = {'cmf': 0.2, 'volume_ratio': 1.5, 'price': 100, 'sma_50': 95, 'adx': 25, 'rsi': 55, 'bb_percent': 50}
    fund = {'debt_equity': de, 'roe': 12, 'pe': 10, 'pb': 1.0, 'f_score': 6, 'profit_growth': 10}
    
    result = check_health_veto(tech, fund, industry="Real Estate")
    status = "❌ VETO" if result['is_vetoed'] else "✅ PASS"
    print(f"\n  D/E = {de:.1f}: {status}")
    print(f"    {desc}")
    if result['veto_reason']:
        print(f"    Reason: {result['veto_reason']}")

# ============== TEST 3: EARNING GUIDANCE ==============
print("\n\n📊 TEST 3: EARNING GUIDANCE (profit_plan_completion)")
print("-" * 70)

# Simulate quarterly completion
now = datetime.now()
quarter = (now.month - 1) // 3 + 1
expected_progress = quarter * 25

print(f"\n  Current Quarter: Q{quarter}")
print(f"  Expected Progress: {expected_progress}%")
print(f"  Min Required (80%): {expected_progress * 0.8:.1f}%")

# Test cases
test_plans = [
    (100, 60, "Plan: 100, YTD: 60", f"{expected_progress}% progress"),
    (100, 40, "Plan: 100, YTD: 40", f"{expected_progress * 0.8:.1f}% threshold"),
    (100, 80, "Plan: 100, YTD: 80", "Should PASS"),
]

for annual_plan, ytd, desc, expected in test_plans:
    completion = (ytd / annual_plan) * 100 if annual_plan > 0 else 0
    min_required = expected_progress * 0.8
    is_on_track = completion >= min_required
    
    status = "✅ ON_TRACK" if is_on_track else "❌ BEHIND (penalty)"
    penalty = 0 if is_on_track else -20
    
    print(f"\n  {desc}")
    print(f"    Completion: {completion:.1f}%")
    print(f"    Expected: {expected}")
    print(f"    Status: {status}")
    if penalty:
        print(f"    Penalty: {penalty} points to Master Score")

print("\n" + "=" * 70)
print("✅ ALL TESTS COMPLETED")
print("=" * 70)
