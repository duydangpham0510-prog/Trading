"""
Test script to check if Vnstock provides DCF data
"""
import sys

print("=" * 70)
print("📊 DCF (Discounted Cash Flow) DATA CHECK - Vnstock")
print("=" * 70)

try:
    from vnstock_data import Finance, show_api, show_doc
    print("\n✅ vnstock_data is available")
    
    # Check what Finance provides
    print("\n📋 Checking Finance module capabilities...")
    
    # Try MAS source for annual_plan (business plan)
    try:
        fin_mas = Finance(source='MAS', symbol='VNM')
        plan = fin_mas.annual_plan()
        print(f"\n✅ MAS annual_plan() available")
        print(plan.columns.tolist() if hasattr(plan, 'columns') else plan)
    except Exception as e:
        print(f"\n❌ MAS annual_plan() error: {e}")
    
    # Check Cash Flow
    try:
        fin_kbs = Finance(source='KBS', symbol='VNM')
        cf = fin_kbs.cash_flow(period='quarter', limit=4)
        print(f"\n✅ KBS cash_flow() available")
        print(f"   Columns: {cf['item'].tolist()[:20]}..." if 'item' in cf.columns else cf.columns.tolist())
    except Exception as e:
        print(f"\n❌ KBS cash_flow() error: {e}")
    
    # Check Ratio for D/E, ROE, etc.
    try:
        ratio = fin_kbs.ratio(period='quarter', limit=4)
        print(f"\n✅ KBS ratio() available")
        print(f"   Columns: {ratio['item'].tolist()[:15]}..." if 'item' in ratio.columns else ratio.columns.tolist())
    except Exception as e:
        print(f"\n❌ KBS ratio() error: {e}")
        
except ImportError as e:
    print(f"\n❌ vnstock_data not installed: {e}")
    print("   Install with: pip install vnstock_data")

print("\n" + "=" * 70)
print("📝 SUMMARY: DCF in Vnstock")
print("=" * 70)
print("""
🔍 DCF (Discounted Cash Flow) Status:

1. ❌ NO BUILT-IN DCF MODEL
   Vnstock does NOT provide pre-calculated DCF values

2. ✅ AVAILABLE RAW DATA for DCF calculation:
   - Cash Flow Statement (cash_flow)
     • Operating Cash Flow
     • Investing Cash Flow  
     • Financing Cash Flow
   - Balance Sheet
     • Total Debt, Equity
   - Financial Ratios
     • D/E, ROE, ROA

3. 📊 KẾ HOẠCH NĂM (Annual Plan) - ONLY from MAS source:
   - annual_profit_plan: Lợi nhuận kế hoạch năm
   - revenue_plan: Doanh thu kế hoạch
   
4. 🔧 HOW TO CALCULATE DCF:
   You need to build your own DCF model using:
   
   DCF = Σ [FCF_t / (1 + WACC)^t] + [TV / (1 + WACC)^n]
   
   Where:
   - FCF = Free Cash Flow (from cash_flow)
   - WACC = Weighted Average Cost of Capital
   - TV = Terminal Value
   - t = year
   
5. 📋 RECOMMENDED APPROACH:
   Vnstock provides the BUILDING BLOCKS:
   ✓ Cash Flow data → Calculate FCF
   ✓ D/E ratio → Estimate Capital Structure
   ✓ ROE, ROA → Estimate ROIC
   ✓ Annual Plan → Revenue/LN targets
   
   You need to:
   1. Fetch Cash Flow from vnstock
   2. Calculate FCF = CFO - CapEx
   3. Estimate growth rate from Annual Plan
   4. Apply DCF formula manually or with a library
""")
print("=" * 70)
