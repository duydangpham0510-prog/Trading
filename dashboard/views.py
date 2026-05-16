from __future__ import annotations

import os
import sys
import json
import time
import sqlite3
from datetime import date, datetime
from functools import wraps

from django.http import HttpRequest, HttpResponse, JsonResponse  # pyright: ignore[reportMissingImports]
from django.shortcuts import render  # pyright: ignore[reportMissingImports]
from django.db import OperationalError  # pyright: ignore[reportMissingImports]
from django.views.decorators.csrf import csrf_exempt  # pyright: ignore[reportMissingImports]

from .forms import DynamicFunctionForm
from .models import ExecutionResult, FunctionDefinition, FunctionGroup, UserPreset, VN30_SYMBOLS
from .services import get_function_definition, iter_registry_functions, run_registry_function
from dashboard.sync_service import sync_market_data, get_top_picks_from_db, get_sync_status, compute_core_logic, INDUSTRY_CONFIG


def retry_on_db_lock(max_retries: int = 3, delay: float = 0.5):
    """Decorator to retry database operations on lock errors."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except OperationalError as e:
                    if "database is locked" in str(e) and attempt < max_retries - 1:
                        last_error = e
                        time.sleep(delay * (attempt + 1))
                        continue
                    raise
            raise last_error  # pyright: ignore[reportGeneralTypeIssues]
        return wrapper
    return decorator


def _seed_missing_registry_rows() -> None:
    @retry_on_db_lock(max_retries=3, delay=0.3)
    def _seed():
        for item in iter_registry_functions():
            group_data = item["group"]
            group, _ = FunctionGroup.objects.get_or_create(
                slug=group_data["slug"],
                defaults={"name": group_data["name"], "description": group_data.get("description", "")},
            )
            new_schema = item.get("param_schema", {})

            # Use update_or_create to ensure param_schema is always synced
            fd, created = FunctionDefinition.objects.update_or_create(
                function_id=item["function_id"],
                defaults={
                    "group": group,
                    "label": item["label"],
                    "description": item.get("description", ""),
                    "runner_path": item["runner_path"],
                    "param_schema": new_schema,
                    "output_type": item.get("output_type", "table"),
                    "is_active": item.get("status") != "disabled",
                },
            )
            # Always sync param_schema from registry (source of truth)
            if fd.param_schema != new_schema:
                fd.param_schema = new_schema
                fd.save(update_fields=["param_schema"])
    _seed()


def _serialize_params(params: dict) -> dict:
    """Convert date/datetime values to strings for JSON serialization."""
    def _conv(v):
        if isinstance(v, (date, datetime)):
            return v.isoformat()
        return v
    return {k: _conv(v) for k, v in params.items()}


def home(request: HttpRequest) -> HttpResponse:
    _seed_missing_registry_rows()

    selected_group = request.GET.get("group", "").strip()
    selected_status = request.GET.get("status", "").strip()
    query = request.GET.get("q", "").strip()
    selected_function_id = request.GET.get("function", "").strip()

    groups = FunctionGroup.objects.prefetch_related("functions").order_by("name")
    all_items = iter_registry_functions()

    # Start: all function IDs
    filtered_ids = [item["function_id"] for item in all_items]

    # Filter by group
    if selected_group:
        filtered_ids = [
            i["function_id"] for i in iter_registry_functions()
            if i["group"]["slug"] == selected_group
        ]

    # Filter by status
    if selected_status:
        filtered_ids = [
            i["function_id"] for i in iter_registry_functions()
            if i.get("status", "planned") == selected_status
            and i["function_id"] in filtered_ids
        ]

    # Filter by text search
    if query:
        filtered_ids = [
            i["function_id"] for i in iter_registry_functions()
            if (query.lower() in i["label"].lower() or query.lower() in i.get("description", "").lower())
            and i["function_id"] in filtered_ids
        ]

    # Only show functions that are in filtered_ids
    functions = FunctionDefinition.objects.filter(function_id__in=filtered_ids).order_by("group__name", "label")

    # Selected function: from URL param, or first in filtered list
    selected_function = (
        FunctionDefinition.objects.filter(function_id=selected_function_id).first()
        or (functions.first() if filtered_ids else None)
    )

    form = DynamicFunctionForm(selected_function.function_id) if selected_function else None

    return render(
        request,
        "dashboard/home.html",
        {
            "groups": groups,
            "functions": functions,
            "selected_function": selected_function,
            "form": form,
            "selected_group": selected_group,
            "selected_status": selected_status,
            "query": query,
        },
    )


@csrf_exempt
@retry_on_db_lock(max_retries=3, delay=0.5)
def run_function(request: HttpRequest, function_id: str) -> HttpResponse:
    _seed_missing_registry_rows()
    definition = get_function_definition(function_id)
    if definition is None:
        return render(request, "dashboard/result_partial.html", {"error": f"Không tìm thấy function: {function_id}"})

    form = DynamicFunctionForm(function_id, request.POST)
    if not form.is_valid():
        return render(request, "dashboard/result_partial.html", {"error": form.errors.as_json()})

    try:
        payload = run_registry_function(function_id, form.cleaned_data)
        function_obj = FunctionDefinition.objects.get(function_id=function_id)
        ExecutionResult.objects.create(function=function_obj, params=_serialize_params(form.cleaned_data), status="success", result_payload=payload)
        return render(request, "dashboard/result_partial.html", {"result": payload})
    except Exception as exc:
        function_obj = FunctionDefinition.objects.get(function_id=function_id)
        ExecutionResult.objects.create(function=function_obj, params=_serialize_params(form.cleaned_data), status="error", result_payload={"error": str(exc)})
        return render(request, "dashboard/result_partial.html", {"error": str(exc)})


def history(request: HttpRequest) -> HttpResponse:
    _seed_missing_registry_rows()
    executions = ExecutionResult.objects.select_related("function", "function__group").order_by("-created_at")[:100]
    return render(request, "dashboard/history.html", {"executions": executions})


def save_preset(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)

    function_id = request.POST.get("function_id", "").strip()
    name = request.POST.get("name", "").strip()
    params_raw = request.POST.get("params", "{}")

    if not function_id or not name:
        return render(request, "dashboard/result_partial.html", {"error": "Thiếu function_id hoặc tên preset."})

    import json
    try:
        params = json.loads(params_raw)
    except json.JSONDecodeError:
        params = {}

    function_obj = FunctionDefinition.objects.filter(function_id=function_id).first()
    if not function_obj:
        return render(request, "dashboard/result_partial.html", {"error": f"Không tìm thấy function: {function_id}"})

    preset = UserPreset.objects.create(function=function_obj, name=name, params=params)
    return render(request, "dashboard/result_partial.html", {"result": {"saved": True, "preset_id": preset.id, "name": preset.name}})


def load_presets(request: HttpRequest, function_id: str) -> HttpResponse:
    presets = UserPreset.objects.filter(function__function_id=function_id).order_by("-created_at")
    html_lines = []
    if presets:
        for p in presets:
            params_json = json.dumps(p.params)
            html_lines.append(
                f'<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #1e2b42;">'
                f'<div><strong>{p.name}</strong><br><span class="muted compact">{p.created_at.strftime("%Y-%m-%d %H:%M")}</span></div>'
                f'<div style="display:flex;gap:8px;">'
                f'<button class="btn-secondary" style="padding:6px 10px;font-size:12px;" onclick="loadPreset({params_json})">Áp dụng</button>'
                f'</div></div>'
            )
    else:
        html_lines.append('<p class="muted compact">Chưa có preset nào cho chức năng này.</p>')
    return HttpResponse("\n".join(html_lines), content_type="text/html")


def market_overview(request: HttpRequest) -> HttpResponse:
    """Market Overview Dashboard - Shows all products from Phase 1-5"""
    return render(request, "dashboard/market_overview.html", {})


@csrf_exempt
def top_picks(request: HttpRequest) -> HttpResponse:
    """
    Top Picks Dashboard - Database-First Architecture v7
    Mục tiêu: Tìm mã tốt nhất để đánh T+ (Swing Trading)

    v7 Features:
    - Database-First: Đọc từ SQLite thay vì gọi API trực tiếp
    - Sync Engine: ThreadPoolExecutor để đồng bộ song song
    - Status Indicator: Hiển thị thời gian cập nhật
    """
    # Lấy sync status
    sync_status = get_sync_status()
    is_data_available = sync_status and sync_status.get("completed_at")

    if is_data_available:
        # Đọc từ Database - CỰC NHANH
        top_picks = get_top_picks_from_db(limit=8)
        all_stocks = get_top_picks_from_db(limit=15)

        # Thống kê
        from .models import StockAnalysis
        total = StockAnalysis.objects.count()
        vetoed = StockAnalysis.objects.filter(is_vetoed=True).count()
        fast = StockAnalysis.objects.filter(is_fast_pick=True, is_vetoed=False).count()

        # Market RSI từ record đầu tiên
        market_rsi = top_picks[0]["market_rsi"] if top_picks else 50

        context = {
            "top_picks": top_picks,
            "all_stocks": all_stocks,
            "scan_time": sync_status.get("completed_at", "")[:19] if sync_status.get("completed_at") else "N/A",  # pyright: ignore[reportOptionalMemberAccess]
            "market_rsi": market_rsi,
            "market_status": "SELL ZONE" if market_rsi > 70 else "NEUTRAL",
            "bullish_count": StockAnalysis.objects.filter(signal__in=["BUY", "STRONG_BUY"]).count(),
            "vetoed_count": vetoed,
            "fast_count": fast,
            "total_scanned": total,
            "high_risk_count": StockAnalysis.objects.filter(is_high_risk=True).count(),
            "is_syncing": sync_status.get("is_running", False),  # pyright: ignore[reportOptionalMemberAccess]
            "sync_progress": sync_status.get("progress_percent", 0),  # pyright: ignore[reportOptionalMemberAccess]
            "has_market_warning": market_rsi > 70,
            "market_warning_message": f"⚠️ SELL ZONE - VNIndex RSI: {market_rsi:.0f}" if market_rsi > 70 else "",
            "has_hot_pick": any(p["master_score"] >= 80 for p in top_picks),
        }
    else:
        # Không có dữ liệu
        context = {
            "top_picks": [],
            "all_stocks": [],
            "scan_time": "Chưa đồng bộ",
            "market_rsi": 50,
            "market_status": "NEUTRAL",
            "bullish_count": 0,
            "vetoed_count": 0,
            "fast_count": 0,
            "total_scanned": 0,
            "high_risk_count": 0,
            "is_syncing": False,
            "sync_progress": 0,
            "has_market_warning": False,
            "market_warning_message": "",
            "has_hot_pick": False,
        }

    return render(request, "dashboard/top_picks.html", context)


@csrf_exempt
def scan_vn30_api(request: HttpRequest) -> HttpResponse:
    """
    API endpoint để trigger sync và lấy kết quả
    POST: Trigger sync với mode (full/data_only/analyze)
    GET: Lấy kết quả từ DB
    """
    import json

    if request.method == "POST":
        # Get mode from request
        try:
            body = json.loads(request.body) if request.body else {}
            mode = body.get("mode", "full")
        except:
            mode = "full"

        # Validate mode
        if mode not in ["full", "data_only", "analyze"]:
            mode = "full"

        # Trigger sync in background
        import threading

        def run_sync():
            # Full sync = fast_mode=False (đầy đủ), Data only = fast_mode=True (nhanh)
            fast_mode = (mode == "data_only")
            sync_market_data(mode=mode, fast_mode=fast_mode)

        thread = threading.Thread(target=run_sync)
        thread.daemon = True
        thread.start()

        mode_labels = {
            "full": "Đồng bộ + Phân tích",
            "data_only": "Chỉ lấy dữ liệu",
            "analyze": "Chỉ phân tích lại"
        }

        return JsonResponse({
            "status": "started",
            "mode": mode,
            "message": f"Đang {mode_labels.get(mode, 'đồng bộ')}..."
        })

    # GET: Lấy kết quả từ DB - CỰC NHANH
    sync_status = get_sync_status()
    top_picks = get_top_picks_from_db(limit=5)

    from .models import StockAnalysis
    total = StockAnalysis.objects.count()
    vetoed = StockAnalysis.objects.filter(is_vetoed=True).count()
    fast = StockAnalysis.objects.filter(is_fast_pick=True, is_vetoed=False).count()
    market_rsi = top_picks[0]["market_rsi"] if top_picks else 50

    return JsonResponse({
        "status": "success",
        "scan_time": sync_status.get("completed_at", "")[:19] if sync_status and sync_status.get("completed_at") else "N/A",
        "market_status": "SELL ZONE" if market_rsi > 70 else "NEUTRAL",
        "market_rsi": market_rsi,
        "top_picks": top_picks,
        "bullish_count": StockAnalysis.objects.filter(signal__in=["BUY", "STRONG_BUY"]).count(),
        "fast_count": fast,
        "vetoed_count": vetoed,
        "high_risk_count": StockAnalysis.objects.filter(is_high_risk=True).count(),
        "is_syncing": sync_status.get("is_running", False) if sync_status else False,
        "sync_progress": sync_status.get("progress_percent", 0) if sync_status else 0,
        "has_market_warning": market_rsi > 70,
        "market_warning_message": f"⚠️ SELL ZONE - VNIndex RSI: {market_rsi:.0f}" if market_rsi > 70 else "",
        "has_hot_pick": any(p["master_score"] >= 80 for p in top_picks),
    })


@csrf_exempt
def backtest(request: HttpRequest) -> HttpResponse:
    """Backtesting Dashboard - For validating predictions"""
    if request.method == "POST":
        # Handle AJAX backtest request
        symbol = request.POST.get("symbol", "VCB")
        start_date = request.POST.get("start_date", "")
        end_date = request.POST.get("end_date", "")
        strategy = request.POST.get("strategy", "ma_cross")
        capital = float(request.POST.get("capital", 10000000))
        
        try:
            result = run_backtest(symbol, start_date, end_date, strategy, capital)
            return JsonResponse(result)
        except Exception as e:
            return JsonResponse({"status": "error", "error": str(e)})
    
    symbol = request.GET.get("symbol", "VCB")
    start_date = request.GET.get("start_date", "")
    end_date = request.GET.get("end_date", "")
    
    return render(request, "dashboard/backtest.html", {
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
    })


def run_backtest(symbol: str, start_date: str, end_date: str, strategy: str, capital: float) -> dict:
    """
    Run backtest for a given symbol and strategy.
    Returns trading statistics and equity curve.
    """
    import pandas as pd  # pyright: ignore[reportMissingImports]
    from dashboard.analyzers import StockAnalyzer
    
    try:
        # Get historical data
        analyzer = StockAnalyzer(period_ta=90)
        ohlcv = analyzer._get_ohlcv(symbol)
        
        if ohlcv is None or len(ohlcv) < 50:
            return {"status": "error", "error": "Không đủ dữ liệu để backtest"}
        
        # Filter by date range if provided
        if start_date:
            ohlcv = ohlcv[ohlcv['time'] >= start_date]
        if end_date:
            ohlcv = ohlcv[ohlcv['time'] <= end_date]
        
        if len(ohlcv) < 50:
            return {"status": "error", "error": "Không đủ dữ liệu sau khi lọc"}
        
        # Generate signals based on strategy
        trades = []
        position = None
        equity_curve = [capital]
        wins = 0
        losses = 0
        
        df = ohlcv.copy()
        
        # Calculate indicators based on strategy
        if strategy == "ma_cross":
            df['sma_20'] = df['close'].rolling(20).mean()
            df['sma_50'] = df['close'].rolling(50).mean()
            
            for i in range(50, len(df)):
                row = df.iloc[i]
                prev = df.iloc[i-1]
                
                if prev['sma_20'] <= prev['sma_50'] and row['sma_20'] > row['sma_50']:
                    # Golden Cross - BUY
                    if position is None:
                        position = {
                            'entry_date': str(row['time'])[:10],
                            'entry_price': row['close'],
                            'type': 'LONG'
                        }
                elif prev['sma_20'] >= prev['sma_50'] and row['sma_20'] < row['sma_50']:
                    # Death Cross - SELL
                    if position is not None:
                        trade_return = (row['close'] - position['entry_price']) / position['entry_price'] * 100
                        trades.append({
                            'date': str(row['time'])[:10],
                            'type': 'BUY',
                            'entry_price': position['entry_price'],
                            'exit_price': row['close'],
                            'return': trade_return
                        })
                        if trade_return > 0:
                            wins += 1
                        else:
                            losses += 1
                        position = None
                
                # Calculate equity
                if position:
                    current_value = capital * (1 + (row['close'] - position['entry_price']) / position['entry_price'])
                else:
                    current_value = capital
                equity_curve.append(current_value)
        
        elif strategy == "rsi":
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
            
            for i in range(14, len(df)):
                row = df.iloc[i]
                prev = df.iloc[i-1]
                
                # RSI Oversold -> BUY, RSI Overbought -> SELL
                if prev['rsi'] < 30 and row['rsi'] >= 30:
                    if position is None:
                        position = {
                            'entry_date': str(row['time'])[:10],
                            'entry_price': row['close'],
                            'type': 'LONG'
                        }
                elif prev['rsi'] > 70 and row['rsi'] <= 70:
                    if position is not None:
                        trade_return = (row['close'] - position['entry_price']) / position['entry_price'] * 100
                        trades.append({
                            'date': str(row['time'])[:10],
                            'type': 'BUY',
                            'entry_price': position['entry_price'],
                            'exit_price': row['close'],
                            'return': trade_return
                        })
                        if trade_return > 0:
                            wins += 1
                        else:
                            losses += 1
                        position = None
                
                if position:
                    current_value = capital * (1 + (row['close'] - position['entry_price']) / position['entry_price'])
                else:
                    current_value = capital
                equity_curve.append(current_value)
        
        elif strategy == "macd":
            ema12 = df['close'].ewm(span=12, adjust=False).mean()
            ema26 = df['close'].ewm(span=26, adjust=False).mean()
            df['macd'] = ema12 - ema26
            df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
            
            for i in range(26, len(df)):
                row = df.iloc[i]
                prev = df.iloc[i-1]
                
                if prev['macd'] <= prev['signal'] and row['macd'] > row['signal']:
                    if position is None:
                        position = {
                            'entry_date': str(row['time'])[:10],
                            'entry_price': row['close'],
                            'type': 'LONG'
                        }
                elif prev['macd'] >= prev['signal'] and row['macd'] < row['signal']:
                    if position is not None:
                        trade_return = (row['close'] - position['entry_price']) / position['entry_price'] * 100
                        trades.append({
                            'date': str(row['time'])[:10],
                            'type': 'BUY',
                            'entry_price': position['entry_price'],
                            'exit_price': row['close'],
                            'return': trade_return
                        })
                        if trade_return > 0:
                            wins += 1
                        else:
                            losses += 1
                        position = None
                
                if position:
                    current_value = capital * (1 + (row['close'] - position['entry_price']) / position['entry_price'])
                else:
                    current_value = capital
                equity_curve.append(current_value)
        
        # Close any open position at the end
        if position is not None:
            last_row = df.iloc[-1]
            trade_return = (last_row['close'] - position['entry_price']) / position['entry_price'] * 100
            trades.append({
                'date': str(last_row['time'])[:10],
                'type': 'CLOSE',
                'entry_price': position['entry_price'],
                'exit_price': last_row['close'],
                'return': trade_return
            })
            if trade_return > 0:
                wins += 1
            else:
                losses += 1
        
        # Calculate statistics
        total_trades = wins + losses
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        
        returns = [t['return'] for t in trades] if trades else [0]
        avg_return = sum(returns) / len(returns) if returns else 0
        total_return = (equity_curve[-1] - capital) / capital * 100 if equity_curve else 0
        
        # Profit factor
        gross_profit = sum(r for r in returns if r > 0)
        gross_loss = abs(sum(r for r in returns if r < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # Max drawdown
        peak = capital
        max_drawdown = 0
        for value in equity_curve:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown
        
        # Sharpe ratio (simplified)
        import statistics
        if len(returns) > 1:
            returns_std = statistics.stdev(returns)
            sharpe_ratio = (sum(returns) / len(returns)) / returns_std if returns_std > 0 else 0
        else:
            sharpe_ratio = 0
        
        return {
            "status": "success",
            "symbol": symbol,
            "strategy": strategy,
            "total_trades": total_trades,
            "win_trades": wins,
            "loss_trades": losses,
            "win_rate": win_rate,
            "total_return": total_return,
            "avg_return": avg_return,
            "profit_factor": profit_factor,
            "max_drawdown": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "equity_curve": equity_curve,
            "trades": trades[-20:]  # Last 20 trades
        }
        
    except Exception as e:
        return {"status": "error", "error": str(e)}


def stock_list(request: HttpRequest) -> HttpResponse:
    """Trang xem tất cả cổ phiếu với thông tin phân tích chi tiết"""
    from .models import StockData, StockAnalysis

    # Lấy filter từ query params
    filter_type = request.GET.get("filter", "all")
    sort_by = request.GET.get("sort", "master_score")
    search = request.GET.get("search", "").upper()
    min_score = int(request.GET.get("min_score", 0))
    market_filter = request.GET.get("market", "all")  # VN30, MIDCAP, SMALL, ALL

    # Query cơ bản
    analyses = StockAnalysis.objects.select_related("symbol").all()

    # Filter by signal/type
    if filter_type == "buy":
        analyses = analyses.filter(signal__in=["BUY", "STRONG_BUY"])
    elif filter_type == "veto":
        analyses = analyses.filter(is_vetoed=True)
    elif filter_type == "fast":
        analyses = analyses.filter(is_fast_pick=True, is_vetoed=False)
    elif filter_type == "high_risk":
        analyses = analyses.filter(is_high_risk=True)
    elif filter_type == "qualified":
        analyses = analyses.filter(criteria_met__gte=7)

    # Filter by market group (VN30, MIDCAP, SMALL)
    if market_filter == "vn30":
        analyses = analyses.filter(symbol__symbol__in=list(VN30_SYMBOLS))
    elif market_filter == "midcap":
        analyses = analyses.filter(symbol__market_group="MIDCAP")
    elif market_filter == "small":
        analyses = analyses.filter(symbol__market_group="SMALL")

    # Filter by industry - sử dụng get_industry() method từ model
    industry_filter = request.GET.get("industry", "all")
    if industry_filter and industry_filter != "all":
        # Lấy tất cả stock có trong danh sách filter
        from dashboard.models import StockData
        matching_symbols = []
        for s in StockData.objects.only('symbol').all():
            ind = s.industry or s.get_industry()
            if industry_filter.lower() in ind.lower():
                matching_symbols.append(s.symbol)
        analyses = analyses.filter(symbol__symbol__in=matching_symbols)

    # Search
    if search:
        analyses = analyses.filter(symbol__symbol__icontains=search)

    # Min score filter
    if min_score > 0:
        analyses = analyses.filter(master_score__gte=min_score)

    # Sort
    sort_fields = {
        "master_score": "-master_score",
        "rsi": "-symbol__rsi",
        "criteria": "-criteria_met",
        "rr": "-risk_reward_ratio",
        "price": "-symbol__price",
        "volume": "-symbol__volume",
        "change": "-symbol__change_percent",
    }
    order_field = sort_fields.get(sort_by, "-master_score")
    analyses = analyses.order_by(order_field)

    # Build stocks list
    stocks = []
    for a in analyses[:200]:  # Limit to 200 for performance
        s = a.symbol
        stocks.append({
            "symbol": s.symbol,
            "company_name": s.company_name or s.symbol,
            "industry": s.industry or s.get_industry(),
            "market_group": s.market_group or s.get_market_group(),
            "price": s.price,
            "change_percent": s.change_percent,
            "volume": s.volume,
            "volume_ratio": s.volume_ratio,
            # Technical
            "rsi": s.rsi,
            "adx": s.adx,
            "cmf": s.cmf,
            "atr": s.atr,
            "sma_10": s.sma_10,
            "sma_20": s.sma_20,
            "sma_50": s.sma_50,
            "macd": s.macd,
            "macd_signal": s.macd_signal,
            "bb_upper": s.bb_upper,
            "bb_middle": s.bb_middle,
            "bb_lower": s.bb_lower,
            "bb_percent": s.bb_percent,
            # Advanced TA
            "mfi": s.mfi,
            "vwap": s.vwap,
            "vwap_status": s.vwap_status,
            "ichimoku_tenkan": s.ichimoku_tenkan,
            "ichimoku_kijun": s.ichimoku_kijun,
            "ichimoku_status": s.ichimoku_status,
            "supertrend": s.supertrend,
            "supertrend_signal": s.supertrend_signal,
            # Fundamental
            "roe": s.roe,
            "pe": s.pe,
            "pb": s.pb,
            "f_score": s.f_score,
            "profit_growth": getattr(s, 'profit_growth', None),
            # Fair Value (from sync_service) - tính toán trong view
            "fv_daily": getattr(a, 'fv_daily', 0) or 0,
            "fv_weekly": getattr(a, 'fv_weekly', 0) or 0,
            "valuation_status": getattr(a, 'valuation_status', 'N/A'),
            "intrinsic_value": getattr(a, 'intrinsic_value', 0),
            # Analysis
            "master_score": a.master_score,
            "technical_score": a.technical_score,
            "fundamental_score": a.fundamental_score,
            "signal": a.signal,
            "criteria_met": a.criteria_met,
            "criteria_list": a.criteria_list,
            "risk_reward_ratio": a.risk_reward_ratio,
            # Target Yield
            "target_yield_pct": getattr(a, 'target_yield_pct', None) or round((a.take_profit - (a.entry_price or s.price)) / (a.entry_price or s.price) * 100, 2) if a.take_profit and (a.entry_price or s.price) > 0 else 0,
            # Score breakdown
            "base_master_score": getattr(a, 'base_master_score', a.master_score),
            "market_weight": getattr(a, 'market_weight', 0),
            "is_vetoed": a.is_vetoed,
            "veto_reason": a.veto_reason,
            "is_fast_pick": a.is_fast_pick,
            "is_high_risk": a.is_high_risk,
            "is_market_high_risk": getattr(a, 'is_market_high_risk', False),
            "stock_risk_level": getattr(a, 'stock_risk_level', 'Medium'),
            "stock_risk_reason": getattr(a, 'stock_risk_reason', ''),
            "is_safe_entry": getattr(a, 'is_safe_entry', False),
            "has_high_resistance": getattr(a, 'has_high_resistance', False),
            "avg_volume_value": getattr(a, 'avg_volume_value', 0),
            "trend_factor": getattr(a, 'trend_factor', 0.6),
            # Smart Money & Industry
            "foreign_buy_streak": getattr(a, 'foreign_buy_streak', 0),
            "foreign_bonus": getattr(a, 'foreign_bonus', 0),
            "industry_performance": getattr(a, 'industry_performance', 0),
            "is_industry_leader": getattr(a, 'is_industry_leader', True),
            # Real R:R
            "hard_risk_pct": getattr(a, 'hard_risk_pct', 0),
            "support_price": getattr(a, 'support_price', 0),
            "trend": a.trend,
            "breakout_status": a.breakout_status,
            "entry_price": a.entry_price,
            "stop_loss": a.stop_loss,
            "take_profit": a.take_profit,
            "estimated_days_to_target": a.estimated_days_to_target,
            "timeframe_label": a.timeframe_label,
            "timeframe_color": a.timeframe_color,
            "expected_profit_per_day": a.expected_profit_per_day,
            "upside_per_day": a.upside_per_day,
            "market_rsi": a.market_rsi,
            # Early Exit & Money Management
            "pe_industry_avg": getattr(a, 'pe_industry_avg', 0),
            "early_exit_trigger_pct": getattr(a, 'early_exit_trigger_pct', 2.0),
            "early_exit_drop_pct": getattr(a, 'early_exit_drop_pct', 0.7),
            "optimal_position_size": getattr(a, 'optimal_position_size', 0),
        })

    # Summary stats
    total = StockAnalysis.objects.count()
    buy_count = StockAnalysis.objects.filter(signal__in=["BUY", "STRONG_BUY"]).count()
    veto_count = StockAnalysis.objects.filter(is_vetoed=True).count()
    fast_count = StockAnalysis.objects.filter(is_fast_pick=True, is_vetoed=False).count()
    qualified_count = StockAnalysis.objects.filter(criteria_met__gte=7).count()

    # Get last sync time
    from .models import SyncStatus
    last_sync_obj = SyncStatus.objects.order_by('-started_at').first()
    last_sync = last_sync_obj.started_at.strftime('%H:%M:%S - %d/%m/%Y') if last_sync_obj else None

    context = {
        "stocks": stocks,
        "total": total,
        "buy_count": buy_count,
        "veto_count": veto_count,
        "fast_count": fast_count,
        "qualified_count": qualified_count,
        "current_filter": filter_type,
        "current_sort": sort_by,
        "current_market": market_filter,
        "current_industry": industry_filter,
        "search_value": search,
        "min_score_value": min_score,
        "last_sync": last_sync,
    }

    return render(request, "dashboard/stock_list.html", context)


def export_stocks_csv(request: HttpRequest) -> HttpResponse:
    """Export tất cả stocks ra CSV"""
    import csv
    from django.http import HttpResponse  # pyright: ignore[reportMissingImports]
    from .models import StockData, StockAnalysis

    analyses = StockAnalysis.objects.select_related("symbol").all()

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    # Add BOM for UTF-8 Excel compatibility
    response.write('\ufeff')
    response["Content-Disposition"] = f'attachment; filename="stocks_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        "Symbol", "Company", "Industry", "Market Group", "Price", "Change%", "Volume (B)", "Volume Ratio",
        "RSI", "ADX", "CMF", "ATR", "MFI", "SMA10", "SMA20", "SMA50", "VWAP", "Ichimoku", "SuperTrend",
        "ROE", "P/E", "P/B", "F-Score", "Profit Growth", "Profit Growth Note", "Is New Listing",
        "Master Score", "Base Score", "Market Weight", "Tech Score", "Fund Score", "Signal",
        "Target Yield %", "R:R Ratio", "Hard Risk %", "Est. Days", "Timeframe", "Trend Factor",
        "Entry", "Stop Loss", "Take Profit", "Support Price", "Profit/Day",
        "FV Daily", "FV Weekly", "Valuation Status",
        "VETO Label", "Is Vetoed", "Veto Reason", "Is Fast Pick", "Is Safe Entry", "Has High Resistance",
        "Foreign Streak", "Foreign Bonus", "Industry Perf", "Is Industry Leader",
        "Is Market High Risk", "Stock Risk Level", "Stock Risk Reason",
        "Market RSI", "Trend", "Breakout Status"
    ])

    for a in analyses:
        s = a.symbol
        avg_vol_b = getattr(a, 'avg_volume_value', 0) or (s.volume_ratio * s.price * 1e6 / 1e9 if s.volume_ratio and s.price else 0)

        # Calculate FV Daily and FV Weekly based on Industry Config
        industry = s.industry or 'Default'
        industry_key = next((k for k in INDUSTRY_CONFIG if k.lower() in industry.lower()), 'Default')
        config = INDUSTRY_CONFIG.get(industry_key, INDUSTRY_CONFIG['Default'])

        # fv_daily = (vwap * 0.6) + (sma10 * 0.4)
        vwap_val = s.vwap or s.price or 0
        sma10_val = s.sma_10 or s.price or 0
        fv_daily = round((vwap_val * 0.6) + (sma10_val * 0.4), 2)

        # intrinsic_value based on industry type
        price_val = s.price or 0
        if config['type'] == 'PB' and s.pb and s.pb > 0:
            intrinsic_value = round((config['target'] / s.pb) * price_val, 2)
        elif s.pe and s.pe > 0:
            intrinsic_value = round((config['target'] / s.pe) * price_val, 2)
        else:
            intrinsic_value = price_val

        # fv_weekly = weighted average of intrinsic_value and take_profit
        tech_score = a.technical_score or 50
        fund_score = a.fundamental_score or 50
        take_profit = a.take_profit or price_val
        fv_weekly = round(((intrinsic_value * fund_score) + (take_profit * tech_score)) / (fund_score + tech_score), 2)

        # Risk adjustment if market RSI > 75
        market_rsi = a.market_rsi or 50
        if market_rsi > 75:
            fv_weekly = round(fv_weekly * 0.9, 2)

        # Valuation Status - Nếu VETO thì hiển thị RISK
        if a.is_vetoed:
            valuation_status = "RISK"
        else:
            valuation_status = "Rẻ" if price_val < fv_weekly else "Đắt"
        
        # VETO label
        veto_label = "🚫 VETOED" if a.is_vetoed else ""
        
        writer.writerow([
            s.symbol, s.company_name, s.industry or s.get_industry(), s.market_group or s.get_market_group(),
            s.price, s.change_percent,
            f"{avg_vol_b:.1f}", s.volume_ratio,
            s.rsi, s.adx, s.cmf, s.atr, s.mfi, s.sma_10, s.sma_20, s.sma_50, s.vwap, s.ichimoku_status, s.supertrend_signal,
            s.roe, s.pe, s.pb, s.f_score, 
            getattr(s, 'profit_growth', None), getattr(s, 'profit_growth_note', 'N/A'), 
            "Yes" if getattr(s, 'is_new_listing', False) else "No",
            a.master_score, getattr(a, 'base_master_score', a.master_score), getattr(a, 'market_weight', 0),
            a.technical_score, a.fundamental_score, a.signal,
            getattr(a, 'target_yield_pct', 0) or round((a.take_profit - (a.entry_price or s.price)) / (a.entry_price or s.price) * 100, 2) if a.take_profit and (a.entry_price or s.price) > 0 else 0,
            a.risk_reward_ratio, getattr(a, 'hard_risk_pct', 0),
            a.estimated_days_to_target, a.timeframe_label, getattr(a, 'trend_factor', 0.6),
            a.entry_price, a.stop_loss, a.take_profit, getattr(a, 'support_price', 0), a.expected_profit_per_day,
            fv_daily, fv_weekly, valuation_status,
            veto_label, "Yes" if a.is_vetoed else "No", a.veto_reason,
            "Yes" if a.is_fast_pick else "No",
            "Yes" if getattr(a, 'is_safe_entry', False) else "No",
            "Yes" if getattr(a, 'has_high_resistance', False) else "No",
            getattr(a, 'foreign_buy_streak', 0), getattr(a, 'foreign_bonus', 0),
            getattr(a, 'industry_performance', 0), "Yes" if getattr(a, 'is_industry_leader', True) else "No",
            "Yes" if getattr(a, 'is_market_high_risk', False) else "No",
            getattr(a, 'stock_risk_level', 'Medium'),
            getattr(a, 'stock_risk_reason', ''),
            a.market_rsi, a.trend, a.breakout_status
        ])

    return response


def export_stock_detail_csv(request: HttpRequest, symbol: str) -> HttpResponse:
    """Export chi tiết một mã cổ phiếu ra CSV với cấu trúc theo Sections"""
    import csv
    from django.http import HttpResponse, Http404  # pyright: ignore[reportMissingImports]
    from .models import StockData, StockAnalysis

    try:
        stock = StockData.objects.get(symbol=symbol.upper())
        analysis = StockAnalysis.objects.get(symbol=stock)
    except (StockData.DoesNotExist, StockAnalysis.DoesNotExist):
        raise Http404(f"Không tìm thấy mã {symbol}")

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response.write('\ufeff')
    response["Content-Disposition"] = f'attachment; filename="{symbol}_detail_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'

    writer = csv.writer(response)

    # Section 0: VETO WARNING (nếu có)
    if analysis.is_vetoed:
        writer.writerow(["🚫 VETOED", analysis.veto_reason or "Lý do không xác định"])
        writer.writerow([])

    # Section 1: THÔNG TIN CƠ BẢN
    writer.writerow(["=== THÔNG TIN CƠ BẢN ==="])
    writer.writerow(["Mã", stock.symbol])
    writer.writerow(["Công ty", stock.company_name])
    writer.writerow(["Ngành", stock.industry or stock.get_industry()])
    writer.writerow(["Nhóm", stock.market_group or stock.get_market_group()])
    writer.writerow(["Giá", stock.price])
    writer.writerow(["Thay đổi %", stock.change_percent])
    writer.writerow(["Khối lượng", stock.volume])
    writer.writerow(["Tỷ lệ khối lượng", stock.volume_ratio])

    # Section 2: DỰ BÁO GIÁ TRỊ HỢP LÝ (WEALTH GUARD)
    writer.writerow([])
    writer.writerow(["=== DỰ BÁO GIÁ TRỊ HỢP LÝ (WEALTH GUARD) ==="])

    # Calculate FV Daily and FV Weekly
    industry = stock.industry or 'Default'
    industry_key = next((k for k in INDUSTRY_CONFIG if k.lower() in industry.lower()), 'Default')
    config = INDUSTRY_CONFIG.get(industry_key, INDUSTRY_CONFIG['Default'])

    price_val = stock.price or 0
    vwap_val = stock.vwap or price_val
    sma10_val = stock.sma_10 or price_val

    # fv_daily = (vwap * 0.6) + (sma10 * 0.4)
    fv_daily = round((vwap_val * 0.6) + (sma10_val * 0.4), 2)

    # intrinsic_value based on industry type
    if config['type'] == 'PB' and stock.pb and stock.pb > 0:
        intrinsic_value = round((config['target'] / stock.pb) * price_val, 2)
    elif stock.pe and stock.pe > 0:
        intrinsic_value = round((config['target'] / stock.pe) * price_val, 2)
    else:
        intrinsic_value = price_val

    # fv_weekly = weighted average
    tech_score = analysis.technical_score or 50
    fund_score = analysis.fundamental_score or 50
    take_profit = analysis.take_profit or price_val
    fv_weekly = round(((intrinsic_value * fund_score) + (take_profit * tech_score)) / (fund_score + tech_score), 2)

    # Risk adjustment if market RSI > 75
    market_rsi = analysis.market_rsi or 50
    if market_rsi > 75:
        fv_weekly = round(fv_weekly * 0.9, 2)

    # Valuation Status - Nếu VETO thì hiển thị RISK
    if analysis.is_vetoed:
        valuation_status = "RISK"
    else:
        valuation_status = "Rẻ" if price_val < fv_weekly else "Đắt"

    writer.writerow(["FV Trong Ngày (Daily)", fv_daily])
    writer.writerow(["FV Trong Tuần (Weekly)", fv_weekly])
    writer.writerow(["Trạng Thái Định Giá", valuation_status])
    writer.writerow(["Giá Trị Nội Tại (Intrinsic)", intrinsic_value])
    writer.writerow(["Loại Định Giá Ngành", config['type']])
    writer.writerow(["Target Ngành", config['target']])

    # Section 3: ĐIỂM PHÂN TÍCH
    writer.writerow([])
    writer.writerow(["=== ĐIỂM PHÂN TÍCH ==="])
    writer.writerow(["Master Score", analysis.master_score])
    writer.writerow(["Technical Score", analysis.technical_score])
    writer.writerow(["Fundamental Score", analysis.fundamental_score])
    writer.writerow(["Signal", analysis.signal])
    writer.writerow(["Xu hướng", analysis.trend])
    writer.writerow(["Criteria đạt", analysis.criteria_met])
    writer.writerow(["Criteria chi tiết", ", ".join(analysis.criteria_list) if analysis.criteria_list else "N/A"])

    writer.writerow([])
    writer.writerow(["=== MỨC GIAO DỊCH ==="])
    writer.writerow(["Entry Price", analysis.entry_price])
    writer.writerow(["Stop Loss", analysis.stop_loss])
    writer.writerow(["Take Profit", analysis.take_profit])
    writer.writerow(["R:R Ratio", analysis.risk_reward_ratio])
    writer.writerow(["Est. Days", analysis.estimated_days_to_target])
    writer.writerow(["Timeframe", analysis.timeframe_label])
    writer.writerow(["Lợi nhuận/ngày", analysis.expected_profit_per_day])
    writer.writerow(["% Upside/ngày", analysis.upside_per_day])

    writer.writerow([])
    writer.writerow(["=== CHỈ BÁO KỸ THUẬT ==="])
    writer.writerow(["RSI (14)", stock.rsi])
    writer.writerow(["ADX", stock.adx])
    writer.writerow(["+DI", stock.plus_di])
    writer.writerow(["-DI", stock.minus_di])
    writer.writerow(["CMF", stock.cmf])
    writer.writerow(["MFI", stock.mfi])
    writer.writerow(["ATR", stock.atr])

    writer.writerow([])
    writer.writerow(["=== TRUNG BÌNH ĐỘNG ==="])
    writer.writerow(["SMA 10", stock.sma_10])
    writer.writerow(["SMA 20", stock.sma_20])
    writer.writerow(["SMA 50", stock.sma_50])

    writer.writerow([])
    writer.writerow(["=== BOLLINGER BANDS ==="])
    writer.writerow(["BB Upper", stock.bb_upper])
    writer.writerow(["BB Middle", stock.bb_middle])
    writer.writerow(["BB Lower", stock.bb_lower])
    writer.writerow(["BB Position %", stock.bb_percent])

    writer.writerow([])
    writer.writerow(["=== MACD ==="])
    writer.writerow(["MACD", stock.macd])
    writer.writerow(["MACD Signal", stock.macd_signal])

    writer.writerow([])
    writer.writerow(["=== CHỈ BÁO NÂNG CAO ==="])
    writer.writerow(["VWAP", stock.vwap])
    writer.writerow(["VWAP Status", stock.vwap_status])
    writer.writerow(["Ichimoku Tenkan", stock.ichimoku_tenkan])
    writer.writerow(["Ichimoku Kijun", stock.ichimoku_kijun])
    writer.writerow(["Ichimoku Status", stock.ichimoku_status])
    writer.writerow(["SuperTrend", stock.supertrend])
    writer.writerow(["SuperTrend Signal", stock.supertrend_signal])

    writer.writerow([])
    writer.writerow(["=== SỨC KHỎE TÀI CHÍNH ==="])
    writer.writerow(["F-Score", stock.f_score])
    writer.writerow(["ROE", stock.roe])
    writer.writerow(["P/E", stock.pe])
    writer.writerow(["P/B", stock.pb])
    writer.writerow(["Tăng trưởng LN quý", getattr(stock, 'profit_growth', None)])

    writer.writerow([])
    writer.writerow(["=== TRẠNG THÁI ==="])
    writer.writerow(["Is Vetoed", "Yes" if analysis.is_vetoed else "No"])
    writer.writerow(["Veto Reason", analysis.veto_reason])
    writer.writerow(["Is Fast Pick", "Yes" if analysis.is_fast_pick else "No"])
    writer.writerow(["Is High Risk", "Yes" if analysis.is_high_risk else "No"])
    writer.writerow(["Breakout Status", analysis.breakout_status])
    writer.writerow(["Market RSI", analysis.market_rsi])

    writer.writerow([])
    writer.writerow([f"Export lúc: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"])

    return response


def strategy_lab(request: HttpRequest) -> HttpResponse:
    """Strategy Lab - Live Simulation & Backtesting"""
    # Lấy danh sách symbols từ DB
    from .models import StockData, VN30_SYMBOLS
    
    # Lấy VN30 và MIDCAP stocks
    all_symbols = list(VN30_SYMBOLS)
    
    # Thêm các mã từ DB
    db_symbols = StockData.objects.values_list('symbol', flat=True)
    for s in db_symbols:
        if s not in all_symbols:
            all_symbols.append(s)
    
    # Sắp xếp
    all_symbols = sorted(set(all_symbols))
    
    return render(request, "dashboard/strategy_lab.html", {
        "symbols": all_symbols
    })


@csrf_exempt
def api_get_stock_data(request: HttpRequest) -> JsonResponse:
    """
    API endpoint to get stock data from database for simulation.
    Returns all technical and fundamental data for a given symbol.
    """
    try:
        from .models import StockData, StockAnalysis
        
        symbol = request.GET.get("symbol", "").strip().upper()
        if not symbol:
            return JsonResponse({"error": "Symbol is required"}, status=400)
        
        # Lấy data từ DB
        try:
            stock = StockData.objects.get(symbol=symbol)
        except StockData.DoesNotExist:
            return JsonResponse({"error": f"Symbol {symbol} not found in database"}, status=404)
        
        # Lấy analysis
        try:
            analysis = StockAnalysis.objects.get(symbol=stock)
        except StockAnalysis.DoesNotExist:
            analysis = None
        
        # Calculate price distance to SMA50
        price = stock.price or 0
        sma_50 = stock.sma_50 or 0
        price_dist = ((price - sma_50) / sma_50 * 100) if sma_50 > 0 else 0
        
        # Build response
        data = {
            "symbol": stock.symbol,
            "company_name": stock.company_name,
            "price": price,
            "change_percent": stock.change_percent,
            # Technical
            "cmf": round(stock.cmf or 0, 3),
            "rsi": round(stock.rsi or 50, 1),
            "adx": round(stock.adx or 25, 1),
            "atr": round(stock.atr or 0, 2),
            "sma_10": round(stock.sma_10 or 0, 2),
            "sma_20": round(stock.sma_20 or 0, 2),
            "sma_50": round(sma_50, 2),
            "price_dist": round(price_dist, 1),  # % price is from SMA50
            # Fundamental
            "roe": round(stock.roe or 15, 1),
            "f_score": stock.f_score or 5,
            "pe": round(stock.pe or 15, 1),
            "pb": round(stock.pb or 1.5, 2),
            # Analysis
            "market_rsi": round(analysis.market_rsi or 50, 1) if analysis else 50,
            "master_score": analysis.master_score if analysis else 50,
            "signal": analysis.signal if analysis else "HOLD",
            "is_vetoed": analysis.is_vetoed if analysis else False,
            "veto_reason": analysis.veto_reason if analysis else "",
            "risk_reward_ratio": round(analysis.risk_reward_ratio, 2) if analysis else 1.5,
        }
        
        return JsonResponse({"status": "success", "data": data})
        
    except Exception as e:
        import traceback
        return JsonResponse({"error": str(e), "trace": traceback.format_exc()}, status=500)


@csrf_exempt
def api_get_all_symbols(request: HttpRequest) -> JsonResponse:
    """
    API endpoint to get all available symbols (VN30 + MIDCAP).
    """
    try:
        from .models import StockData, VN30_SYMBOLS
        
        # Lấy VN30 symbols
        symbols = list(VN30_SYMBOLS)
        
        # Thêm các mã từ DB không có trong VN30
        db_symbols = StockData.objects.values_list('symbol', flat=True)
        for s in db_symbols:
            if s not in symbols:
                symbols.append(s)
        
        # Sắp xếp
        symbols = sorted(set(symbols))
        
        return JsonResponse({
            "status": "success",
            "symbols": symbols,
            "count": len(symbols)
        })
        
    except Exception as e:
        import traceback
        return JsonResponse({"error": str(e), "trace": traceback.format_exc()}, status=500)


def api_simulate(request: HttpRequest) -> JsonResponse:
    """
    API endpoint for Live Simulation.
    Kết nối trực tiếp với simulator.py (Logic V4).
    """
    try:
        from .models import StockData, StockAnalysis
        from .analyzers.simulator import SimParams, simulate_trade, result_to_dict
        
        symbol = request.GET.get("symbol", "").strip().upper()
        if not symbol:
            return JsonResponse({"error": "Symbol is required"}, status=400)
        
        # Lấy override params từ sliders
        params = SimParams()
        
        price_adj = request.GET.get("price_adj")  # -20 to +20
        if price_adj:
            params.price_adj_pct = float(price_adj)
        
        cmf_val = request.GET.get("cmf")  # -1.0 to 1.0
        if cmf_val:
            params.cmf = float(cmf_val)
        
        rsi_val = request.GET.get("rsi")  # 20 to 90
        if rsi_val:
            params.rsi = float(rsi_val)
        
        adx_val = request.GET.get("adx")  # 0 to 60
        if adx_val:
            params.adx = float(adx_val)
        
        market_rsi_val = request.GET.get("market_rsi")  # 20 to 90
        if market_rsi_val:
            params.market_rsi = float(market_rsi_val)
        
        f_score_val = request.GET.get("f_score")  # 0 to 9
        if f_score_val:
            params.f_score = int(f_score_val)
        
        roe_val = request.GET.get("roe")  # 0 to 50
        if roe_val:
            params.roe = float(roe_val)
        
        # Lấy base data từ DB
        try:
            stock = StockData.objects.get(symbol=symbol)
        except StockData.DoesNotExist:
            return JsonResponse({"error": f"Symbol {symbol} not found in database"}, status=404)
        
        # Build base_data dict
        base_data = {
            "price": stock.price,
            "cmf": stock.cmf or 0.0,
            "rsi": stock.rsi or 50.0,
            "adx": stock.adx or 25.0,
            "atr": stock.atr or (stock.price * 0.02),
            "sma_20": stock.sma_20 or 0.0,
            "sma_50": stock.sma_50 or 0.0,
            "sma_200": getattr(stock, 'sma_200', 0.0) or 0.0,
            "volume_ratio": stock.volume_ratio or 1.0,
            "f_score": stock.f_score or 5,
            "roe": stock.roe or 10.0,
            "pe": stock.pe or 15.0,
            "pb": stock.pb or 1.5,
        }
        
        # Lấy market RSI từ analysis
        try:
            analysis = StockAnalysis.objects.get(symbol=stock)
            base_data["market_rsi"] = analysis.market_rsi or 50.0
        except StockAnalysis.DoesNotExist:
            base_data["market_rsi"] = 50.0
        
        # Chạy simulation
        result = simulate_trade(symbol, base_data, params)
        return JsonResponse(result_to_dict(result))
        
    except Exception as e:
        import traceback
        return JsonResponse({"error": str(e), "trace": traceback.format_exc()}, status=500)


def api_backtest(request: HttpRequest) -> JsonResponse:
    """
    API endpoint for Historical Backtesting.
    Runs analysis at a past date and compares with actual results.
    """
    try:
        from datetime import timedelta
        import pandas as pd  # pyright: ignore[reportMissingImports]
        from django.http import JsonResponse  # pyright: ignore[reportMissingImports]
        from .models import StockData
        from .sync_service import calculate_technical_indicators, get_stock_data_from_vnstock  # pyright: ignore[reportAttributeAccessIssue]
        
        symbol = request.GET.get("symbol", "").strip().upper()
        start_date = request.GET.get("start_date", "").strip()  # Format: YYYY-MM-DD
        lookback_days = int(request.GET.get("lookback", 60))  # Days of history needed
        forward_days = int(request.GET.get("forward", 20))  # Days to forward test
        
        if not symbol:
            return JsonResponse({"error": "Symbol is required"}, status=400)
        
        if not start_date:
            return JsonResponse({"error": "start_date is required (YYYY-MM-DD)"}, status=400)
        
        # Parse start date
        try:
            from datetime import datetime
            backtest_date = datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            return JsonResponse({"error": "Invalid date format. Use YYYY-MM-DD"}, status=400)
        
        # Calculate date range for historical data
        data_start = backtest_date - timedelta(days=lookback_days)
        
        # Get historical price data
        df = get_stock_data_from_vnstock(
            symbol,
            start=data_start.strftime("%Y-%m-%d"),
            end=backtest_date.strftime("%Y-%m-%d")
        )
        
        if df is None or len(df) < 50:
            return JsonResponse({"error": f"Insufficient historical data for {symbol}"}, status=404)
        
        # Get the last available data point on or before backtest_date
        df['time'] = pd.to_datetime(df['time'])
        df = df[df['time'] <= backtest_date].sort_values('time')
        
        if len(df) < 20:
            return JsonResponse({"error": f"Not enough data points before {start_date}"}, status=404)
        
        # Calculate indicators at that point
        tech = calculate_technical_indicators(df)
        
        entry_price = tech["price"]
        support_price = tech["sma_50"] if tech["sma_50"] > 0 else entry_price * 0.97
        hard_risk_pct = ((entry_price - support_price) / entry_price) * 100 if entry_price > 0 else 3
        
        # Target = entry + 5%
        target_price = entry_price * 1.05
        
        # Stop loss = support
        stop_loss = support_price
        
        # Get forward data to check results
        forward_end = backtest_date + timedelta(days=forward_days)
        df_forward = get_stock_data_from_vnstock(
            symbol,
            start=backtest_date.strftime("%Y-%m-%d"),
            end=forward_end.strftime("%Y-%m-%d")
        )
        
        results = {
            "symbol": symbol,
            "backtest_date": start_date,
            "entry_price": entry_price,
            "target_price": round(target_price, 2),
            "stop_loss": round(stop_loss, 2),
            "hard_risk_pct": round(hard_risk_pct, 2),
            "entry_tech": {
                "rsi": tech["rsi"],
                "cmf": tech["cmf"],
                "adx": tech["adx"],
                "sma_50": tech["sma_50"],
                "atr": tech["atr"],
            },
            "forward_test": {}
        }
        
        if df_forward is not None and len(df_forward) > 1:
            df_forward['time'] = pd.to_datetime(df_forward['time'])
            df_forward = df_forward[df_forward['time'] > backtest_date].sort_values('time')
            
            forward_highs = df_forward['close'].cummax()
            forward_lows = df_forward['close'].cummin()
            
            # Check outcomes
            hit_target_idx = df_forward[forward_highs >= target_price].index
            hit_stop_idx = df_forward[forward_lows <= stop_loss].index
            
            days_to_target = None
            days_to_stop = None
            outcome = "NO_RESULT"
            
            if len(hit_target_idx) > 0 and len(hit_stop_idx) > 0:
                if hit_target_idx[0] < hit_stop_idx[0]:
                    outcome = "WIN_TARGET"
                    days_to_target = (pd.to_datetime(df_forward.loc[hit_target_idx[0], 'time']) - backtest_date).days
                else:
                    outcome = "LOSS_STOP"
                    days_to_stop = (pd.to_datetime(df_forward.loc[hit_stop_idx[0], 'time']) - backtest_date).days
            elif len(hit_target_idx) > 0:
                outcome = "WIN_TARGET"
                days_to_target = (pd.to_datetime(df_forward.loc[hit_target_idx[0], 'time']) - backtest_date).days
            elif len(hit_stop_idx) > 0:
                outcome = "LOSS_STOP"
                days_to_stop = (pd.to_datetime(df_forward.loc[hit_stop_idx[0], 'time']) - backtest_date).days
            else:
                # Price still in between
                final_price = df_forward['close'].iloc[-1]
                if final_price > entry_price:
                    outcome = "PENDING_PROFIT"
                else:
                    outcome = "PENDING_LOSS"
            
            results["forward_test"] = {
                "outcome": outcome,
                "days_to_target": days_to_target,
                "days_to_stop": days_to_stop,
                "final_price": round(df_forward['close'].iloc[-1], 2),
                "final_date": df_forward['time'].iloc[-1].strftime("%Y-%m-%d"),
                "max_profit_pct": round((df_forward['close'].max() - entry_price) / entry_price * 100, 2),
                "max_loss_pct": round((entry_price - df_forward['close'].min()) / entry_price * 100, 2),
                "price_history": df_forward[['time', 'close']].to_dict('records')
            }
        
        return JsonResponse(results)
        
    except Exception as e:
        import traceback
        return JsonResponse({"error": str(e), "trace": traceback.format_exc()}, status=500)


# ============== WEALTH GUARD LOGIC BACKTEST ==============

def wealth_guard_backtest(request: HttpRequest) -> HttpResponse:
    """Trang Backtest Time-series: Xem lịch sử của 1 mã bất kỳ trong toàn bộ DB"""
    from .models import StockData, VN30_SYMBOLS
    from datetime import datetime, timedelta
    
    # 1. Mặc định backtest 3 tháng gần nhất
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
    
    # 2. LẤY TOÀN BỘ MÃ CỔ PHIẾU ĐÃ QUÉT
    # Lấy VN30 làm gốc
    all_symbols = list(VN30_SYMBOLS)
    
    # Kéo thêm toàn bộ mã từ bảng StockData (Giống cách ông làm ở strategy_lab)
    db_symbols = StockData.objects.values_list('symbol', flat=True)
    for s in db_symbols:
        if s not in all_symbols:
            all_symbols.append(s)
            
    # Sắp xếp theo thứ tự A-Z
    all_symbols = sorted(set(all_symbols))
    
    context = {
        "symbols": all_symbols, 
        "default_start": start_date,
        "default_end": end_date,
    }
    return render(request, "dashboard/wealth_guard_backtest.html", context)
@csrf_exempt
def api_wealth_guard_data(request: HttpRequest) -> JsonResponse:
    """
    API endpoint để lấy dữ liệu lịch sử cho Wealth Guard Backtest.
    Trả về 5 năm dữ liệu với đầy đủ thông số kỹ thuật và cơ bản.
    Sử dụng vnstock_data/vnstock như strategy_lab.
    
    Nâng cấp v2:
    - High, Low cho TP/SL check
    - ROE, F_Score cho VETO logic
    - CMF, MFI, Foreign_Buy cho Smart Money analysis
    """
    try:
        import pandas as pd  # pyright: ignore[reportMissingImports]
        import numpy as np  # pyright: ignore[reportMissingImports]
        
        symbol = request.GET.get("symbol", "").strip().upper()
        limit = int(request.GET.get("limit", 1250))  # ~5 years
        
        if not symbol:
            return JsonResponse({"error": "Symbol is required"}, status=400)
        
        # ===== LẤY DỮ LIỆU OHLCV =====
        ohlcv = None
        
        # Thử vnstock_data trước
        try:
            from vnstock_data import Market  # pyright: ignore[reportMissingImports]
            mkt = Market()
            end = pd.Timestamp.today().strftime("%Y-%m-%d")
            start = (pd.Timestamp.today() - pd.DateOffset(days=limit + 60)).strftime("%Y-%m-%d")
            
            df_raw = mkt.equity(symbol).ohlcv(start=start, end=end, interval="1D")
            
            if df_raw is not None and len(df_raw) > 0:
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    if col in df_raw.columns:
                        df_raw[col] = pd.to_numeric(df_raw[col], errors='coerce')
                
                price_cols = ['open', 'high', 'low', 'close']
                for col in price_cols:
                    if col in df_raw.columns:
                        df_raw[col] = df_raw[col] * 1000
                
                if 'time' in df_raw.columns:
                    df_raw['time'] = pd.to_datetime(df_raw['time'])
                elif df_raw.index.name == 'time':
                    df_raw = df_raw.reset_index()
                
                ohlcv = df_raw
        except Exception as e:
            print(f"[WealthGuard] vnstock_data error: {e}")
        
        # Fallback: thử vnstock
        if ohlcv is None or len(ohlcv) < 20:
            try:
                from vnstock.explorer.vci.quote import Quote
                
                q = Quote(symbol=symbol, show_log=False)
                end = pd.Timestamp.today().strftime("%Y-%m-%d")
                start = (pd.Timestamp.today() - pd.DateOffset(days=limit + 60)).strftime("%Y-%m-%d")
                
                df_raw = q.history(start=start, end=end, interval='1D')
                
                if df_raw is not None and len(df_raw) > 0:
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        if col in df_raw.columns:
                            df_raw[col] = pd.to_numeric(df_raw[col], errors='coerce')
                    
                    price_cols = ['open', 'high', 'low', 'close']
                    for col in price_cols:
                        if col in df_raw.columns:
                            df_raw[col] = df_raw[col] * 1000
                    
                    if 'time' in df_raw.columns:
                        df_raw['time'] = pd.to_datetime(df_raw['time'])
                    elif df_raw.index.name == 'time':
                        df_raw = df_raw.reset_index()
                    
                    ohlcv = df_raw
            except Exception as e:
                print(f"[WealthGuard] vnstock error: {e}")
        
        if ohlcv is None or len(ohlcv) < 20:
            return JsonResponse({"error": f"Không lấy được dữ liệu cho {symbol}. Vui lòng thử mã khác."}, status=400)
        
        if 'time' in ohlcv.columns:
            ohlcv = ohlcv.sort_values('time').reset_index(drop=True)
        
        # ===== TÍNH INDICATORS =====
        df = ohlcv.copy()
        
        # SMA
        df['sma_10'] = df['close'].rolling(10).mean()
        df['sma_20'] = df['close'].rolling(20).mean()
        df['sma_50'] = df['close'].rolling(50).mean()
        
        # VWAP
        df['typical'] = (df['high'] + df['low'] + df['close']) / 3
        df['vol'] = df['volume'].fillna(0)
        df['vwap'] = (df['typical'] * df['vol']).rolling(14).sum() / df['vol'].rolling(14).sum()
        df['vwap'] = df['vwap'].fillna(df['close'])
        
        # RSI
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        df['rsi'] = df['rsi'].fillna(50)
        
        # CMF (Chaikin Money Flow)
        mf_multiplier = ((df['close'] - df['low']) - (df['high'] - df['close'])) / (df['high'] - df['low'])
        mf_multiplier = mf_multiplier.fillna(0)
        mf_volume = mf_multiplier * df['volume']
        df['cmf'] = mf_volume.rolling(20).sum() / df['volume'].rolling(20).sum()
        df['cmf'] = df['cmf'].fillna(0)
        
        # MFI (Money Flow Index)
        tp = (df['high'] + df['low'] + df['close']) / 3
        mf = tp * df['volume']
        pos_flow = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
        neg_flow = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
        mfi_ratio = pos_flow / (neg_flow + 1e-10)
        df['mfi'] = 100 - (100 / (1 + mfi_ratio))
        df['mfi'] = df['mfi'].fillna(50)
        
        # Foreign Buy Streak (simulate based on price momentum)
        price_change = df['close'].pct_change(5).fillna(0)
        df['foreign_buy'] = (price_change > 0).rolling(3).sum()
        df['foreign_buy'] = df['foreign_buy'].fillna(0)
        
        # Ichimoku (9, 26, 52 periods)
        def calc_ichimoku(high, low, close, period):
            hh = high.rolling(period).max()
            ll = low.rolling(period).min()
            return (hh + ll) / 2
        
        df['ichimoku_tenkan'] = calc_ichimoku(df['high'], df['low'], df['close'], 9)
        df['ichimoku_kijun'] = calc_ichimoku(df['high'], df['low'], df['close'], 26)
        
        # Ichimoku status (Bullish = price above both, Bearish = below both)
        df['ichimoku_status'] = 'neutral'
        above_both = (df['close'] > df['ichimoku_tenkan']) & (df['close'] > df['ichimoku_kijun'])
        below_both = (df['close'] < df['ichimoku_tenkan']) & (df['close'] < df['ichimoku_kijun'])
        df.loc[above_both, 'ichimoku_status'] = 'bullish'
        df.loc[below_both, 'ichimoku_status'] = 'bearish'
        
        # MACD (12, 26, 9)
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        df['macd'] = ema12 - ema26
        df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']
        # MACD status
        df['macd_status'] = 'neutral'
        df.loc[(df['macd'] > df['macd_signal']) & (df['macd'] > 0), 'macd_status'] = 'bullish'
        df.loc[(df['macd'] < df['macd_signal']) & (df['macd'] < 0), 'macd_status'] = 'bearish'
        
        # Supertrend (ATR-based, multiplier 3)
        atr_period = 10
        df['atr_st'] = (df['high'] - df['low']).rolling(atr_period).mean()
        hl2 = (df['high'] + df['low']) / 2
        df['supertrend_upper'] = hl2 + 3 * df['atr_st']
        df['supertrend_lower'] = hl2 - 3 * df['atr_st']
        df['supertrend_signal'] = 'neutral'
        df.loc[df['close'] > df['supertrend_upper'].shift(1), 'supertrend_signal'] = 'buy'
        df.loc[df['close'] < df['supertrend_lower'].shift(1), 'supertrend_signal'] = 'sell'
        
        # Bollinger Bands
        bb_period = 20
        bb_std = df['close'].rolling(bb_period).std()
        bb_mid = df['close'].rolling(bb_period).mean()
        df['bb_upper'] = bb_mid + 2 * bb_std
        df['bb_lower'] = bb_mid - 2 * bb_std
        df['bb_percent'] = ((df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])) * 100
        df['bb_percent'] = df['bb_percent'].fillna(50)
        
        # Volume Ratio (current vol vs 20-day avg)
        df['volume_ratio'] = df['volume'] / df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume_ratio'].fillna(1.0)
        
        # VWAP Status
        df['vwap_status'] = 'neutral'
        df.loc[df['close'] > df['vwap'], 'vwap_status'] = 'above'
        df.loc[df['close'] < df['vwap'], 'vwap_status'] = 'below'
        
        # ROE & F-Score simulation (sử dụng trend-based simulation)
        # Trong thực tế nên load từ financial data API
        df['roe'] = 20.0  # Default simulation
        df['f_score'] = 6  # Default simulation
        
        # VN-Index RSI (Market RSI) - Calculate from proxy or fetch real data
        venv_site = os.path.expanduser(r"~/.venv/Lib/site-packages")
        market_rsi_val = 50  # Default
        
        try:
            if venv_site not in sys.path:
                sys.path.insert(0, venv_site)
            
            from vnstock_data import Quote  # pyright: ignore[reportMissingImports]
            import pandas as pd  # pyright: ignore[reportMissingImports]
            
            # Fetch VN-Index data for market RSI
            try:
                quote = Quote(source='VCI', symbol='VNINDEX')
                vndx_df = quote.history(start="2019-01-01", end="2026-12-31", interval="1D")
                
                if vndx_df is not None and not vndx_df.empty:
                    # Calculate RSI on VN-Index
                    delta = vndx_df['close'].diff()
                    gain = delta.where(delta > 0, 0).rolling(14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
                    rs = gain / (loss + 1e-10)
                    vndx_df['market_rsi'] = 100 - (100 / (1 + rs))
                    
                    # Create lookup dict
                    vndx_rsi = {}
                    for _, row in vndx_df.iterrows():
                        if pd.notna(row['market_rsi']):
                            date_str = str(row['time'])[:10]
                            vndx_rsi[date_str] = row['market_rsi']
                    
                    print(f"[BacktestAPI] Loaded {len(vndx_rsi)} VN-Index RSI data points")
            except Exception as e:
                print(f"[BacktestAPI] Could not fetch VN-Index: {e}")
        except Exception as e:
            print(f"[BacktestAPI] Market RSI setup error: {e}")
        
        # Market RSI proxy (sẽ được override bởi VN-Index RSI thực)
        df['market_rsi'] = 50  # Default, sẽ update từ VN-Index
        df['_market_rsi_override'] = False
        
        # Lấy industry từ DB
        industry = 'Default'
        pe_val = 15.0
        pb_val = 1.5
        roe_val = 20.0
        try:
            from .models import StockData
            stock_db = StockData.objects.get(symbol=symbol)
            industry = stock_db.industry or 'Default'
            pe_val = stock_db.pe or 15.0
            pb_val = stock_db.pb or 1.5
            roe_val = stock_db.roe or 20.0
        except:
            pass
        
        industry_key = next((k for k in INDUSTRY_CONFIG if k.lower() in industry.lower()), 'Default')
        config = INDUSTRY_CONFIG.get(industry_key, INDUSTRY_CONFIG['Default'])
        
        # ===== FETCH QUARTERLY FINANCIAL DATA FOR VETO =====
        quarterly_data = {}  # quarter -> {roe, f_score, is_vetoed, veto_reason}
        
        try:
            from .models import QuarterlyFinancial
            qf_records = QuarterlyFinancial.objects.filter(symbol=symbol).order_by('-quarter_date')
            for qf in qf_records:
                quarterly_data[qf.quarter] = {
                    'roe': qf.roe,
                    'f_score': qf.f_score,
                    'is_vetoed': qf.is_vetoed,
                    'veto_reason': qf.veto_reason
                }
        except Exception as e:
            print(f"[BacktestAPI] Could not fetch QuarterlyFinancial: {e}")
        
        # Function to get quarter from date
        def get_quarter(dt_str):
            try:
                dt = datetime.strptime(dt_str, '%Y-%m-%d')
                q = (dt.month - 1) // 3 + 1
                return f"{dt.year}-Q{q}"
            except:
                return None
        
        # ===== BUILD DATA ARRAY ===== (REFACTORED to use compute_core_logic)
        data_array = []
        
        # Prepare fund_data from DB values (static for historical backtest)
        fund_data = {
            'roe': roe_val,
            'pe': pe_val,
            'pb': pb_val,
            'f_score': 6,  # Default
            'industry': industry,
            'pe_industry_avg': None,
            'foreign_buy_streak': 0,
            'industry_performance': 0,
            'is_industry_leader': True,
        }
        
        for idx in range(len(df)):
            if idx < 50:  # Need 50 bars for SMA50
                continue
                
            row = df.iloc[idx]
            
            # Get date string
            time_val = row['time'] if 'time' in df.columns else idx
            if hasattr(time_val, 'strftime'):
                date_str = time_val.strftime('%Y-%m-%d')
            else:
                date_str = str(time_val)
            
            # Build tech dict from calculated indicators
            tech = {
                'price': float(row['close']) if pd.notna(row['close']) else 0,
                'change_percent': 0,
                'volume': int(row['volume']) if pd.notna(row['volume']) else 0,
                'rsi': float(row['rsi']) if pd.notna(row.get('rsi')) else 50,
                'mfi': float(row['mfi']) if pd.notna(row.get('mfi')) else 50,
                'adx': float(row.get('adx', 25)) if pd.notna(row.get('adx')) else 25,
                'plus_di': float(row.get('plus_di', 0)) if pd.notna(row.get('plus_di')) else 0,
                'minus_di': float(row.get('minus_di', 0)) if pd.notna(row.get('minus_di')) else 0,
                'cmf': float(row['cmf']) if pd.notna(row['cmf']) else 0,
                'atr': float(row.get('atr', 0)) if pd.notna(row.get('atr')) else 0,
                'sma_10': float(row['sma_10']) if pd.notna(row['sma_10']) else float(row['close']),
                'sma_20': float(row['sma_20']) if pd.notna(row['sma_20']) else float(row['close']),
                'sma_50': float(row['sma_50']) if pd.notna(row['sma_50']) else float(row['close']),
                'sma_200': float(row.get('sma_200', 0)) if pd.notna(row.get('sma_200')) else 0,
                'bb_upper': float(row.get('bb_upper', 0)) if pd.notna(row.get('bb_upper')) else 0,
                'bb_middle': float(row.get('bb_middle', 0)) if pd.notna(row.get('bb_middle')) else 0,
                'bb_lower': float(row.get('bb_lower', 0)) if pd.notna(row.get('bb_lower')) else 0,
                'bb_percent': float(row.get('bb_percent', 50)) if pd.notna(row.get('bb_percent')) else 50,
                'macd': float(row.get('macd', 0)) if pd.notna(row.get('macd')) else 0,
                'macd_signal': float(row.get('macd_signal', 0)) if pd.notna(row.get('macd_signal')) else 0,
                'volume_ratio': float(row.get('volume_ratio', 1.0)) if pd.notna(row.get('volume_ratio')) else 1.0,
                'vwap': float(row['vwap']) if pd.notna(row['vwap']) else float(row['close']),
                'vwap_status': str(row.get('vwap_status', 'neutral')).lower() if pd.notna(row.get('vwap_status')) else 'neutral',
                'ichimoku_tenkan': float(row.get('ichimoku_tenkan', 0)) if pd.notna(row.get('ichimoku_tenkan')) else 0,
                'ichimoku_kijun': float(row.get('ichimoku_kijun', 0)) if pd.notna(row.get('ichimoku_kijun')) else 0,
                'ichimoku_status': str(row.get('ichimoku_status', 'neutral')).lower() if pd.notna(row.get('ichimoku_status')) else 'neutral',
                'supertrend': float(row.get('supertrend', 0)) if pd.notna(row.get('supertrend')) else 0,
                'supertrend_signal': str(row.get('supertrend_signal', 'neutral')).lower() if pd.notna(row.get('supertrend_signal')) else 'neutral',
            }
            
            # Calculate ATR if not present
            if tech['atr'] <= 0 and idx >= 14:
                try:
                    high_curr = float(row['high'])
                    low_curr = float(row['low'])
                    close_prev = float(df.iloc[idx-1]['close']) if pd.notna(df.iloc[idx-1]['close']) else high_curr
                    tr1 = high_curr - low_curr
                    tr2 = abs(high_curr - close_prev)
                    tr3 = abs(low_curr - close_prev)
                    tr = max(tr1, tr2, tr3)
                    atr_sum = tr
                    for j in range(idx-13, idx):
                        h = float(df.iloc[j]['high']) if pd.notna(df.iloc[j]['high']) else float(df.iloc[j]['close'])
                        l = float(df.iloc[j]['low']) if pd.notna(df.iloc[j]['low']) else float(df.iloc[j]['close'])
                        c = float(df.iloc[j-1]['close']) if j > 0 and pd.notna(df.iloc[j-1]['close']) else h
                        atr_sum += max(h - l, abs(h - c), abs(l - c))
                    tech['atr'] = atr_sum / 14
                except:
                    pass
            
            # Get market RSI (VN-Index at that time)
            market_rsi_val = 50
            if 'vndx_rsi' in dir() and date_str in vndx_rsi:
                market_rsi_val = vndx_rsi[date_str]
            
            # Prepare fund_data with quarterly override if available
            fund_data_with_quarterly = dict(fund_data)
            try:
                dt_obj = datetime.strptime(date_str, '%Y-%m-%d')
                quarter = f"{dt_obj.year}-Q{(dt_obj.month - 1) // 3 + 1}"
                if quarter in quarterly_data:
                    qd = quarterly_data[quarter]
                    fund_data_with_quarterly['roe'] = qd.get('roe') or fund_data['roe']
                    fund_data_with_quarterly['f_score'] = qd.get('f_score') or fund_data['f_score']
            except:
                pass
            
            # Call compute_core_logic
            result = compute_core_logic(
                symbol=symbol,
                tech=tech,
                fund_data=fund_data_with_quarterly,
                market_rsi=market_rsi_val,
                market_group='VN30',  # Assume VN30 for backtest
                df=df,
                quarterly_data=quarterly_data,
                date_str=date_str
            )
            
            # Build record from result
            record = {
                "Date": date_str,
                "Open": round(float(row['open']), 2) if pd.notna(row['open']) else 0,
                "High": round(float(row['high']), 2) if pd.notna(row['high']) else 0,
                "Low": round(float(row['low']), 2) if pd.notna(row['low']) else 0,
                "Close": round(float(row['close']), 2) if pd.notna(row['close']) else 0,
                "Volume": int(row['volume']) if pd.notna(row['volume']) else 0,
                "VWAP": round(result.get('vwap', 0), 2),
                "VWAP_Status": result.get('vwap_status', 'neutral'),
                "SMA10": round(result.get('sma_10', 0), 2),
                "SMA20": round(result.get('sma_20', 0), 2),
                "SMA50": round(result.get('sma_50', 0), 2),
                "SMA_Trend": result.get('trend', 'SIDEWAYS'),
                "RSI": round(result.get('rsi', 50), 1),
                "Market_RSI": round(result.get('market_rsi', 50), 1),
                "ADX": round(result.get('adx', 25), 1),
                "CMF": round(result.get('cmf', 0), 3),
                "MFI": round(result.get('mfi', 50), 1),
                "Foreign_Buy": 0,
                "PE": round(result.get('pe', 15), 1),
                "PB": round(result.get('pb', 1.5), 2),
                "ROE": round(result.get('roe', 20), 1),
                "F_Score": round(result.get('f_score', 6), 0),
                "Fundamental_Score": round(result.get('fundamental_score', 50), 0),
                "Technical_Score": round(result.get('technical_score', 50), 0),
                "Master_Score": result.get('master_score', 50),
                "Signal": result.get('signal', 'WAIT'),
                "Criteria": result.get('criteria_met', 0),
                "R_R": result.get('risk_reward_ratio', 1.5),
                "Timeframe": result.get('timeframe_label', 'SWING'),
                "Target_Yield": round(result.get('target_yield_pct', 0), 2),
                "Pct_Per_Day": round(result.get('expected_profit_per_day', 0), 2),
                "Est_Days": result.get('estimated_days_to_target', 15),
                "ATR": round(result.get('atr', 0), 2),
                "FV_Daily": round(result.get('fv_daily', 0), 2),
                "FV_Weekly": round(result.get('fv_weekly', 0), 2),
                "Take_Profit": result.get('take_profit', 0),
                "Stop_Loss": result.get('stop_loss', 0),
                "Is_Vetoed": result.get('is_vetoed', False),
                "Veto_Reason": result.get('veto_reason', ''),
                "Industry": result.get('industry', industry),
                # Additional indicators
                "Ichimoku_Status": result.get('ichimoku_status', 'neutral'),
                "Ichimoku_Tenkan": round(result.get('ichimoku_tenkan', 0), 2),
                "Ichimoku_Kijun": round(result.get('ichimoku_kijun', 0), 2),
                "Ichimoku_TK_Cross": 'neutral',
                "Supertrend_Signal": result.get('supertrend_signal', 'neutral'),
                "BB_Pos": round(result.get('bb_percent', 50), 1),
                "Vol_Ratio": round(result.get('volume_ratio', 1), 2),
                "MACD": round(result.get('macd', 0), 4),
                "MACD_Signal": round(result.get('macd_signal', 0), 4),
                "MACD_Status": 'neutral',
                "MACD_Histogram": 0,
                "Foreign_Streak": result.get('foreign_buy_streak', 0),
            }
            data_array.append(record)
        
        return JsonResponse({
            "status": "success",
            "symbol": symbol,
            "industry": industry,
            "industry_config": config,
            "total_records": len(data_array),
            "data": data_array
        })
        
    except Exception as e:
        import traceback
        return JsonResponse({"error": str(e), "trace": traceback.format_exc()}, status=500)


# ============== FETCH QUARTERLY FINANCIAL DATA ==============

@csrf_exempt
def fetch_quarterly_financial(request):
    """Fetch dữ liệu tài chính quý từ vnstock_data và lưu vào DB"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)
    
    try:
        data = json.loads(request.body)
        symbols = data.get('symbols', [])
        
        if not symbols:
            return JsonResponse({'error': 'No symbols provided'}, status=400)
        
        results = []
        
        for symbol in symbols:
            try:
                # Try vnstock_data first
                try:
                    from vnstock_data import Finance  # pyright: ignore[reportMissingImports]
                    finance = Finance(source='VCI', symbol=symbol)
                    
                    # Get ratio data
                    df_ratio = finance.ratio(period='quarter', limit=12)
                    
                    if df_ratio is not None and not df_ratio.empty:
                        for _, row in df_ratio.iterrows():
                            quarter = str(row.get('report_period', ''))
                            if not quarter:
                                continue
                            
                            # Extract ROE, F-Score components
                            roe = row.get('ROE', None) or row.get('roe', None)
                            if roe and isinstance(roe, str):
                                roe = float(roe.replace('%', ''))
                            
                            # Calculate F-Score
                            f_score_roc = 1 if row.get('roc_change', 0) > 0 else 0
                            f_score_roa = 1 if (row.get('roa', 0) or 0) > 0 else 0
                            
                            f_score = f_score_roc + f_score_roa
                            
                            # Save to DB
                            from .models import QuarterlyFinancial
                            
                            # Parse quarter
                            quarter_date = None
                            try:
                                if 'Q1' in quarter: quarter_date = f"{quarter[:4]}-03-31"
                                elif 'Q2' in quarter: quarter_date = f"{quarter[:4]}-06-30"
                                elif 'Q3' in quarter: quarter_date = f"{quarter[:4]}-09-30"
                                elif 'Q4' in quarter: quarter_date = f"{quarter[:4]}-12-31"
                            except:
                                pass
                            
                            if quarter_date:
                                qf, created = QuarterlyFinancial.objects.update_or_create(
                                    symbol=symbol,
                                    quarter=quarter,
                                    defaults={
                                        'quarter_date': quarter_date,
                                        'roe': roe,
                                        'f_score': f_score,
                                        'f_score_roc': f_score_roc,
                                        'f_score_roa': f_score_roa,
                                        'is_vetoed': roe < 15 if roe else False,
                                        'veto_reason': 'ROE < 15' if roe and roe < 15 else '',
                                        'vci_data': row.to_dict() if hasattr(row, 'to_dict') else {}
                                    }
                                )
                                
                                results.append({
                                    'symbol': symbol,
                                    'quarter': quarter,
                                    'roe': roe,
                                    'f_score': f_score,
                                    'saved': True
                                })
                    else:
                        results.append({'symbol': symbol, 'error': 'No data from vnstock_data'})
                        
                except ImportError:
                    # Fallback: try free vnstock
                    from vnstock import Finance
                    finance = Finance(symbol=symbol)  # pyright: ignore[reportCallIssue]
                    df = finance.ratio(period='quarter')
                    
                    results.append({
                        'symbol': symbol,
                        'note': 'Used free vnstock',
                        'data': df.tail(4).to_dict() if df is not None else None
                    })
                    
            except Exception as e:
                results.append({'symbol': symbol, 'error': str(e)})
        
        return JsonResponse({
            'status': 'success',
            'results': results,
            'total': len(results)
        })
        
    except Exception as e:
        import traceback
        return JsonResponse({'error': str(e), 'trace': traceback.format_exc()}, status=500)
