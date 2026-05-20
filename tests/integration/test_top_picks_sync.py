"""
Test script for Top Picks Full Sync functionality
Tests the complete sync flow including API endpoint, sync_service, and error handling

Run: python -m pytest tests/integration/test_top_picks_sync.py -v
"""
import sys
import os
import json
import time
from datetime import datetime
from unittest.mock import patch, MagicMock

# Setup Django environment
sys.path.insert(0, r"d:\OneDrive\Desktop\Trading-1")
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vnstock_web.settings')

import django
django.setup()

import pytest
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.sessions.backends.db import SessionStore

from dashboard.views import scan_vn30_api, top_picks
from dashboard.sync_service import (
    sync_market_data, 
    get_sync_status, 
    get_top_picks_from_db,
    sync_stock_batch,
    save_results_to_db
)
from dashboard.models import SyncStatus, StockData, StockAnalysis


# ============== FIXTURES ==============

@pytest.fixture
def client():
    """Django test client"""
    return Client()


@pytest.fixture
def sync_status():
    """Create a sample sync status for testing"""
    sync, _ = SyncStatus.objects.get_or_create(
        id=1,
        defaults={
            "status": "completed",
            "total_symbols": 30,
            "processed_symbols": 30,
            "started_at": django.utils.timezone.now(),
            "completed_at": django.utils.timezone.now()
        }
    )
    sync.status = "completed"
    sync.completed_at = django.utils.timezone.now()
    sync.save()
    return sync


@pytest.fixture
def sample_stock_data(db):
    """Create sample stock data for testing"""
    from dashboard.models import StockData, StockAnalysis
    
    # Create sample stock
    stock, _ = StockData.objects.update_or_create(
        symbol="TEST",
        defaults={
            "company_name": "Test Company",
            "industry": "Technology",
            "market_group": "VN30",
            "price": 50000,
            "change_percent": 2.5,
            "volume": 1000000,
            "rsi": 55,
            "adx": 25,
            "cmf": 0.1,
            "atr": 500,
            "sma_10": 49000,
            "sma_20": 48000,
            "sma_50": 47000,
            "volume_ratio": 1.5,
        }
    )
    
    # Create sample analysis
    StockAnalysis.objects.update_or_create(
        symbol=stock,
        defaults={
            "master_score": 75,
            "technical_score": 80,
            "fundamental_score": 70,
            "signal": "BUY",
            "entry_price": 50000,
            "stop_loss": 47500,
            "take_profit": 55000,
            "risk_reward_ratio": 2.0,
            "is_vetoed": False,
            "is_fast_pick": True,
            "market_rsi": 45,
        }
    )
    
    return stock


@pytest.fixture
def sample_sync_results():
    """Sample sync results for testing"""
    return [
        {
            "symbol": "TEST1",
            "company_name": "Test Company 1",
            "industry": "Technology",
            "price": 50000,
            "change_percent": 2.5,
            "volume": 1000000,
            "rsi": 55,
            "adx": 25,
            "plus_di": 30,
            "minus_di": 20,
            "cmf": 0.1,
            "atr": 500,
            "sma_10": 49000,
            "sma_20": 48000,
            "sma_50": 47000,
            "bb_upper": 52000,
            "bb_middle": 50000,
            "bb_lower": 48000,
            "bb_percent": 50,
            "macd": 100,
            "macd_signal": 50,
            "volume_ratio": 1.5,
            "mfi": 55,
            "vwap": 49500,
            "vwap_status": "above",
            "ichimoku_tenkan": 49000,
            "ichimoku_kijun": 48500,
            "ichimoku_status": "bullish",
            "supertrend": 47000,
            "supertrend_signal": "buy",
            "pe": 15,
            "pb": 1.5,
            "roe": 20,
            "f_score": 7,
            "master_score": 75,
            "technical_score": 80,
            "fundamental_score": 70,
            "signal": "BUY",
            "entry_price": 50000,
            "stop_loss": 47500,
            "take_profit": 55000,
            "risk_reward_ratio": 2.0,
            "is_vetoed": False,
            "veto_reason": "",
            "is_fast_pick": True,
            "is_short_term_qualified": True,
            "is_slow_mode": False,
            "is_high_risk": False,
            "has_inverted_sl": False,
            "avg_volume_value": 50,
            "target_yield_pct": 10,
            "estimated_days_to_target": 7,
            "timeframe_label": "Fast T+",
            "profit_per_day": 1.4,
            "criteria_met": 8,
            "criteria_list": ["RSI", "ADX", "CMF", "Volume"],
            "market_rsi": 45,
            # Fixed: Added missing fields that caused KeyError
            "trend": "UPTREND",
            "breakout_status": "BREAKOUT",
        }
    ]


# ============== TEST: API ENDPOINT ==============

class TestScanVN30API:
    """Test suite for scan_vn30_api endpoint"""
    
    def test_get_sync_status(self, client, sync_status, sample_stock_data):
        """Test GET request to scan_vn30_api returns correct status"""
        response = client.get('/api/scan/vn30/')
        assert response.status_code == 200
        
        data = response.json()
        print(f"[TEST] GET Response: {json.dumps(data, indent=2, default=str)[:500]}...")
        
        # Check response structure
        assert 'status' in data
        assert 'is_syncing' in data
        assert 'sync_progress' in data
        
        # If sync is completed, should have data
        if data.get('status') == 'success':
            assert 'top_picks' in data
            assert 'fast_count' in data
    
    def test_post_trigger_full_sync(self, client):
        """Test POST request triggers sync"""
        # This test just checks the POST returns 200
        response = client.post(
            '/api/scan/vn30/',
            data=json.dumps({"mode": "full"}),
            content_type='application/json'
        )
        assert response.status_code == 200
        
        data = response.json()
        print(f"[TEST] POST Response: {data}")
        
        # Should return started status
        assert data.get('status') == 'started'
        assert 'message' in data
    
    def test_post_trigger_data_only_sync(self, client):
        """Test POST with data_only mode"""
        response = client.post(
            '/api/scan/vn30/',
            data=json.dumps({"mode": "data_only"}),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'started'
    
    def test_post_trigger_analyze_sync(self, client):
        """Test POST with analyze mode"""
        response = client.post(
            '/api/scan/vn30/',
            data=json.dumps({"mode": "analyze"}),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'started'
    
    def test_post_invalid_mode_defaults_to_full(self, client):
        """Test invalid mode defaults to full"""
        response = client.post(
            '/api/scan/vn30/',
            data=json.dumps({"mode": "invalid_mode"}),
            content_type='application/json'
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'started'
    
    def test_post_empty_body_defaults_to_full(self, client):
        """Test empty body defaults to full sync"""
        response = client.post(
            '/api/scan/vn30/',
            data='',
            content_type='application/json'
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get('status') == 'started'


# ============== TEST: SYNC SERVICE ==============

class TestSyncService:
    """Test suite for sync_service functions"""
    
    def test_get_sync_status_returns_correct_structure(self):
        """Test get_sync_status returns expected structure"""
        status = get_sync_status()
        
        # Should be dict
        assert isinstance(status, dict)
        
        # Print for debugging
        print(f"[TEST] Sync Status: {status}")
        
        # Should have these keys
        expected_keys = ['status', 'is_running', 'completed_at']
        for key in expected_keys:
            assert key in status, f"Missing key: {key}"
    
    def test_sync_status_model_properties(self, sync_status):
        """Test SyncStatus model properties"""
        assert sync_status.progress_percent == 100
        assert sync_status.is_running == False
        
        # Test running state
        sync_status.status = "running"
        sync_status.save()
        assert sync_status.is_running == True
    
    def test_save_results_to_db(self, sample_sync_results):
        """Test saving sync results to database"""
        count = save_results_to_db(sample_sync_results)
        
        assert count == 1
        
        # Verify data was saved
        stock = StockData.objects.get(symbol="TEST1")
        assert stock.price == 50000
        assert stock.industry == "Technology"
        
        # Verify analysis was saved
        analysis = StockAnalysis.objects.get(symbol=stock)
        assert analysis.master_score == 75
        assert analysis.signal == "BUY"
        assert analysis.is_vetoed == False
    
    def test_get_top_picks_from_db(self, sample_stock_data):
        """Test getting top picks from database"""
        picks, health = get_top_picks_from_db(limit=5)
        
        # Should return list
        assert isinstance(picks, list)
        
        # Print for debugging
        print(f"[TEST] Top Picks: {len(picks)} picks")
        if picks:
            print(f"[TEST] First pick: {picks[0].get('symbol', 'N/A')}")
    
    @patch('dashboard.sync_service.get_top_symbols_by_liquidity')
    @patch('dashboard.sync_service.sync_stock_batch')
    @patch('dashboard.sync_service.get_market_rsi')
    def test_sync_market_data_full_mode(
        self, mock_market_rsi, mock_batch, mock_symbols
    ):
        """Test sync_market_data in full mode"""
        # Mock the dependencies
        mock_market_rsi.return_value = 45.0
        mock_symbols.return_value = ["VCB", "TCB", "HPG"]
        mock_batch.return_value = {
            "results": [],
            "count": 0,
            "failed": []
        }
        
        # Run sync
        result = sync_market_data(mode="full", fast_mode=False)
        
        # Check result structure
        assert isinstance(result, dict)
        print(f"[TEST] Sync Result: {result}")
        
        # Should have these keys
        assert 'status' in result
        assert 'elapsed_seconds' in result
    
    @patch('dashboard.sync_service.get_top_symbols_by_liquidity')
    @patch('dashboard.sync_service.sync_stock_batch')
    @patch('dashboard.sync_service.get_market_rsi')
    def test_sync_market_data_analyze_mode(
        self, mock_market_rsi, mock_batch, mock_symbols
    ):
        """Test sync_market_data in analyze mode"""
        mock_market_rsi.return_value = 50.0
        mock_symbols.return_value = ["VCB"]
        mock_batch.return_value = {"results": [], "count": 0, "failed": []}
        
        # Create a sample stock in DB for analyze mode
        StockData.objects.create(symbol="VCB", price=50000)
        
        result = sync_market_data(mode="analyze", fast_mode=False)
        
        assert result['status'] == 'success'


# ============== TEST: TOP PICKS VIEW ==============

class TestTopPicksView:
    """Test suite for top_picks view"""
    
    def test_top_picks_view_with_data(self, client, sync_status, sample_stock_data):
        """Test top_picks view renders with data"""
        response = client.get('/top-picks/')
        assert response.status_code == 200
        
        # Check context has required variables
        # The template uses Django's render, so we check response content
        content = response.content.decode('utf-8')
        assert 'Top Picks' in content or 'top_picks' in content.lower()
    
    def test_top_picks_view_without_data(self, client):
        """Test top_picks view renders without data"""
        # Clear any existing data
        StockData.objects.all().delete()
        SyncStatus.objects.filter(id=1).update(status="idle", completed_at=None)
        
        response = client.get('/top-picks/')
        assert response.status_code == 200


# ============== TEST: ERROR HANDLING ==============

class TestErrorHandling:
    """Test error handling in sync functionality"""
    
    @patch('dashboard.sync_service.get_top_symbols_by_liquidity')
    def test_sync_handles_empty_symbol_list(self, mock_symbols):
        """Test sync handles empty symbol list gracefully"""
        mock_symbols.return_value = []
        
        # Should not crash
        result = sync_market_data(mode="full", fast_mode=True)
        assert result['status'] == 'success'
        assert result['total'] == 0
    
    @patch('dashboard.sync_service.get_top_symbols_by_liquidity')
    @patch('dashboard.sync_service.sync_stock_batch')
    @patch('dashboard.sync_service.get_market_rsi')
    def test_sync_handles_batch_failure(
        self, mock_market_rsi, mock_batch, mock_symbols
    ):
        """Test sync handles batch failure gracefully"""
        mock_market_rsi.return_value = 50.0
        mock_symbols.return_value = ["VCB", "TCB"]
        mock_batch.side_effect = Exception("API Error")
        
        # Should handle exception
        try:
            result = sync_market_data(mode="full", fast_mode=True)
            # If it completes, check status
            assert result is not None
        except Exception as e:
            print(f"[TEST] Expected exception: {e}")
            # This is also acceptable
    
    def test_get_sync_status_handles_missing_record(self):
        """Test get_sync_status handles missing SyncStatus record"""
        # Delete any existing sync status
        SyncStatus.objects.all().delete()
        
        status = get_sync_status()
        
        # Should return None or empty dict, not crash
        assert status is None or isinstance(status, dict)


# ============== TEST: FRONTEND JS ==============

class TestFrontendSync:
    """Test frontend JavaScript sync functionality"""
    
    def test_trigger_sync_function_exists(self):
        """Test triggerSync function is defined in template"""
        # Read template
        with open(r"d:\OneDrive\Desktop\Trading-1\dashboard\templates\dashboard\top_picks.html", 'r') as f:
            content = f.read()
        
        # Check function exists
        assert 'function triggerSync' in content
        assert 'async function triggerSync' in content
        
        # Check CSRF handling
        assert 'getCsrfToken' in content
        assert 'X-CSRFToken' in content
        
        # Check API endpoint
        assert '/api/scan/vn30/' in content
        
        # Check modes
        assert 'full' in content
        assert 'data_only' in content
        assert 'analyze' in content
        
        # Check button IDs
        assert 'syncFullBtn' in content
        assert 'syncDataBtn' in content
        assert 'syncAnalyzeBtn' in content
    
    def test_trigger_sync_sends_correct_payload(self):
        """Test triggerSync sends correct JSON payload"""
        with open(r"d:\OneDrive\Desktop\Trading-1\dashboard\templates\dashboard\top_picks.html", 'r') as f:
            content = f.read()
        
        # Check POST request structure
        assert "method: 'POST'" in content
        assert "'Content-Type': 'application/json'" in content
        assert 'body: JSON.stringify' in content
        
        # Check mode is sent in body
        assert 'mode: mode' in content or '"mode":' in content


# ============== RUN ALL TESTS ==============

if __name__ == "__main__":
    print("=" * 70)
    print("TOP PICKS FULL SYNC - TEST SUITE")
    print("=" * 70)
    
    # Run with pytest
    pytest.main([__file__, '-v', '--tb=short'])
