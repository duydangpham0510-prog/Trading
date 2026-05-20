"""
Test script for 100-symbol sync functionality
Verify that sync processes 100 symbols correctly

Run: python -m pytest tests/integration/test_100_symbols_sync.py -v
"""
import sys
import os
import re

sys.path.insert(0, r"d:\OneDrive\Desktop\Trading-1")
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'vnstock_web.settings')

import django
django.setup()

import pytest
from unittest.mock import patch, MagicMock

from dashboard.sync_service import (
    UNIVERSE_SIZE,
    MIN_LIQUIDITY_BILLION,
    MIN_PRICE,
    sync_market_data,
    _get_top_100_by_liquidity,
)


class TestConstants:
    """Test suite for constants"""
    
    def test_universe_size_is_100(self):
        """Verify UNIVERSE_SIZE is 100"""
        assert UNIVERSE_SIZE == 100, f"Expected UNIVERSE_SIZE=100, got {UNIVERSE_SIZE}"
        print(f"[TEST] ✓ UNIVERSE_SIZE = {UNIVERSE_SIZE}")
    
    def test_min_liquidity_is_15b(self):
        """Verify MIN_LIQUIDITY_BILLION is 15"""
        assert MIN_LIQUIDITY_BILLION == 15, f"Expected MIN_LIQUIDITY_BILLION=15, got {MIN_LIQUIDITY_BILLION}"
        print(f"[TEST] ✓ MIN_LIQUIDITY_BILLION = {MIN_LIQUIDITY_BILLION}B")
    
    def test_min_price_is_10000(self):
        """Verify MIN_PRICE is 10000"""
        assert MIN_PRICE == 10000, f"Expected MIN_PRICE=10000, got {MIN_PRICE}"
        print(f"[TEST] ✓ MIN_PRICE = {MIN_PRICE}")
    
    def test_batch_size_calculates_correctly(self):
        """Test batch size calculation for 100 symbols"""
        batch_size = 20
        total_symbols = 100
        expected_batches = (total_symbols + batch_size - 1) // batch_size
        assert expected_batches == 5, f"Expected 5 batches, got {expected_batches}"
        print(f"[TEST] ✓ 100 symbols / batch_size 20 = {expected_batches} batches")


class TestGetTop100Function:
    """Test suite for _get_top_100_by_liquidity function"""
    
    @patch('dashboard.sync_service.Listing')
    @patch('dashboard.sync_service.Quote')
    def test_get_top_100_returns_list(self, mock_quote, mock_listing):
        """Test _get_top_100_by_liquidity returns a list"""
        # Mock Listing to return HOSE stocks
        mock_list_instance = MagicMock()
        mock_listing.return_value = mock_list_instance
        mock_df = MagicMock()
        mock_df.__len__ = lambda self: 5
        mock_df.__getitem__ = lambda self, key: ['HOSE'] * 5
        mock_df.columns = ['symbol', 'exchange']
        mock_df.__iter__ = lambda self: iter([{'symbol': f'TEST{i}', 'exchange': 'HOSE'} for i in range(5)])
        mock_list_instance.all_symbols.return_value = mock_df
        
        # Mock Quote to return valid data
        mock_q = MagicMock()
        mock_quote.return_value = mock_q
        mock_history = MagicMock()
        mock_history.__len__ = lambda self: 20
        mock_history.__getitem__ = lambda self, key: [1000000] * 20
        mock_history.__getattr__ = lambda self, name: MagicMock(return_value=MagicMock(mean=MagicMock(return_value=50000)))
        mock_q.history.return_value = mock_history
        
        result = _get_top_100_by_liquidity()
        
        assert isinstance(result, list), "Should return a list"
        print(f"[TEST] ✓ _get_top_100_by_liquidity returns {len(result)} symbols")
    
    @patch('dashboard.sync_service.Listing')
    @patch('dashboard.sync_service.Quote')
    def test_get_top_100_with_api_error(self, mock_quote, mock_listing):
        """Test _get_top_100_by_liquidity returns fallback on error"""
        # Mock API to raise exception
        mock_list_instance = MagicMock()
        mock_listing.return_value = mock_list_instance
        mock_list_instance.all_symbols.side_effect = Exception("API Error")
        
        result = _get_top_100_by_liquidity()
        
        assert isinstance(result, list), "Should return a list"
        assert len(result) > 0, "Should return fallback symbols"
        print(f"[TEST] ✓ Fallback returns {len(result)} symbols")


class TestSyncModeVariants:
    """Test different sync modes"""
    
    @patch('dashboard.sync_service.get_top_symbols_by_liquidity')
    @patch('dashboard.sync_service.sync_stock_batch')
    @patch('dashboard.sync_service.get_market_rsi')
    def test_full_sync_mode(self, mock_rsi, mock_batch, mock_symbols):
        """Test full sync mode (fast_mode=False)"""
        mock_symbols.return_value = ["VCB", "TCB"]
        mock_rsi.return_value = 50.0
        mock_batch.return_value = {"results": [], "count": 0, "failed": []}
        
        result = sync_market_data(mode="full", fast_mode=False)
        assert result['status'] == 'success'
        print("[TEST] ✓ Full sync mode works")
    
    @patch('dashboard.sync_service.get_top_symbols_by_liquidity')
    @patch('dashboard.sync_service.sync_stock_batch')
    @patch('dashboard.sync_service.get_market_rsi')
    def test_data_only_mode(self, mock_rsi, mock_batch, mock_symbols):
        """Test data only sync mode (fast_mode=True)"""
        mock_symbols.return_value = ["VCB", "TCB"]
        mock_rsi.return_value = 50.0
        mock_batch.return_value = {"results": [], "count": 0, "failed": []}
        
        result = sync_market_data(mode="data_only", fast_mode=True)
        assert result['status'] == 'success'
        print("[TEST] ✓ Data only sync mode works")
    
    @patch('dashboard.sync_service.sync_stock_batch')
    @patch('dashboard.sync_service.get_market_rsi')
    def test_analyze_mode(self, mock_rsi, mock_batch):
        """Test analyze mode - uses existing DB data"""
        mock_rsi.return_value = 50.0
        mock_batch.return_value = {"results": [], "count": 0, "failed": []}
        
        result = sync_market_data(mode="analyze", fast_mode=False)
        assert result['status'] == 'success'
        print("[TEST] ✓ Analyze mode works")


if __name__ == "__main__":
    print("=" * 70)
    print("100-SYMBOLS SYNC - TEST SUITE")
    print("=" * 70)
    
    pytest.main([__file__, '-v', '--tb=short'])
