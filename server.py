# server.py
from __future__ import annotations

import os
import time
import random
from typing import Any, Dict, List, Optional, Callable

import httpx
from dotenv import load_dotenv
import sys
from mcp.server.fastmcp import FastMCP

import hmac
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


# ASGI (Render/원격 배포)
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.responses import PlainTextResponse

# ──────────────────────────────────────────────────────────────────────────────
# 0) 환경설정 / HTTP 클라이언트
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()
FMP_API_KEY = os.getenv("FMP_API_KEY")
if not FMP_API_KEY:
    raise RuntimeError("FMP_API_KEY가 비었습니다. .env 또는 Render 환경변수를 확인하세요.")

PRODUCT_API_KEY = os.getenv("PRODUCT_API_KEY")
if not PRODUCT_API_KEY:
    raise RuntimeError("PRODUCT_API_KEY가 비었습니다. .env 또는 Render 환경변수를 확인하세요.")

BASE_URL = "https://financialmodelingprep.com"
client = httpx.Client(base_url=BASE_URL, timeout=20.0)

# ──────────────────────────────────────────────────────────────────────────────
# 1) MCP 서버
# ──────────────────────────────────────────────────────────────────────────────
mcp = FastMCP("FMP Universal")

# ──────────────────────────────────────────────────────────────────────────────
# 2) 요금제/엔드포인트 카탈로그
#    - plan_hint는 문서/가격 비교표 기준의 "힌트"입니다.
#    - 실제 접근 가능 여부는 list_fmp_endpoints(run_check=True) 또는 test_endpoint_access로 확인.
#
# 참고(요금/개요):
# - Pricing 비교(개인용 Basic/Starter/Premium/Ultimate): https://site.financialmodelingprep.com/developer/docs/pricing
#   · Basic: End of Day 위주, 일일 호출 한도 낮음
#   · Starter+: Real-time(실시간) 제공, 분당 호출량 넉넉
#   · Premium/Ultimate: 장기 히스토리(30+년), 더 많은 데이터/속도
# - Stable 엔드포인트 문서 허브: https://site.financialmodelingprep.com/developer/docs
# ──────────────────────────────────────────────────────────────────────────────
FMP_PLANS: Dict[str, Dict[str, Any]] = {
    "Basic(EOD)": {
        "timeframe": "End of Day",
        "notes": "기본 무상(또는 저가) 플랜. EOD 데이터 중심, 호출/히스토리 제한."
        # </* noqa: E501 */>
    },
    "Starter+": {
        "timeframe": "Real-time",
        "notes": "실시간 시세/캘린더/뉴스 등 활성화. 일반 개인용 추천."
    },
    "Premium+": {
        "timeframe": "Real-time + Extended history",
        "notes": "히스토리 확장(30+년 등), 속도/호출 상향."
    },
    "Ultimate+": {
        "timeframe": "Real-time + Long history (max)",
        "notes": "최대 한도/속도/커버리지."
    },
}

# 카테고리별 대표 stable 엔드포인트들 (필요 시 자유롭게 추가/수정)
# - tool_name: MCP 툴 이름(중복 불가)
# - service: "stable" | "v3" | "v4" | "api"(=v3) | "raw"
# - endpoint: FMP 경로 (예: "quote", "income-statement")
# - description: MCP에 노출될 설명(요금제 힌트 포함)
# - plan_hint: "Basic(EOD)" | "Starter+" | "Premium+" | "Ultimate+"
# - default_params: 기본 쿼리 파라미터 (필요 시)
# - test: 접근 점검에 사용할 샘플(심볼/파라미터)
FMP_CATALOG: List[Dict[str, Any]] = [
    # ── Directory & Search
    {
        "tool_name": "fmp_search_name",
        "service": "stable",
        "endpoint": "search-name",
        "description": "회사 이름으로 티커 검색",
        "plan_hint": "Basic(EOD)",
        "default_params": {},
        "test": {"params": {"query": "Apple", "limit": 1}},
    },
    {
        "tool_name": "fmp_search",
        "service": "stable",
        "endpoint": "search",
        "description": "심볼/이름/ISIN/CIK/CUSIP 검색",
        "plan_hint": "Basic(EOD)",
        "default_params": {},
        "test": {"params": {"query": "AAPL", "limit": 1}},
    },
    {
        "tool_name": "fmp_available_industries",
        "service": "stable",
        "endpoint": "available-industries",
        "description": "사용 가능한 산업(Industries) 목록",
        "plan_hint": "Basic(EOD)",
        "default_params": {},
        "test": {"params": {}},
    },

    # ── Quotes & Prices
    {
        "tool_name": "fmp_quote",
        "service": "stable",
        "endpoint": "quote",
        "description": "실시간 주가(단일/다중 심볼)",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL"}},
    },
    {
        "tool_name": "fmp_historical_price_eod_full",
        "service": "stable",
        "endpoint": "historical-price-eod-full",
        "description": "EOD 히스토리(OHLCV) 전체",
        "plan_hint": "Basic(EOD)",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL", "from": "2023-01-01", "to": "2023-02-01"}},
    },

    # ── Fundamentals (Statements / Ratios / Metrics)
    {
        "tool_name": "fmp_income_statement",
        "service": "stable",
        "endpoint": "income-statement",
        "description": "손익계산서 (annual/quarter)",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL", "limit": 1}},
    },
    {
        "tool_name": "fmp_balance_sheet_statement",
        "service": "stable",
        "endpoint": "balance-sheet-statement",
        "description": "대차대조표 (annual/quarter)",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL", "limit": 1}},
    },
    {
        "tool_name": "fmp_cash_flow_statement",
        "service": "stable",
        "endpoint": "cash-flow-statement",
        "description": "현금흐름표 (annual/quarter)",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL", "limit": 1}},
    },
    {
        "tool_name": "fmp_key_metrics",
        "service": "stable",
        "endpoint": "key-metrics",
        "description": "핵심 지표(Valuation, Growth 등)",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL", "limit": 1}},
    },
    {
        "tool_name": "fmp_ratios",
        "service": "stable",
        "endpoint": "ratios",
        "description": "재무 비율",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL", "limit": 1}},
    },

    # ── Profiles / Reference
    {
        "tool_name": "fmp_profile_symbol",
        "service": "stable",
        "endpoint": "profile-symbol",
        "description": "회사 프로필(심볼 기준)",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL"}},
    },
    {
        "tool_name": "fmp_profile_bulk",
        "service": "stable",
        "endpoint": "profile-bulk",
        "description": "회사 프로필 벌크(파트 분할 지원)",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"part": 0}},
    },

    # ── Calendars (Earnings / Dividends / IPO / Splits)
    {
        "tool_name": "fmp_earnings_calendar",
        "service": "stable",
        "endpoint": "earnings-calendar",
        "description": "어닝 달력",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"from": "2025-01-01", "to": "2025-01-31"}},
    },
    {
        "tool_name": "fmp_dividends_calendar",
        "service": "stable",
        "endpoint": "dividends-calendar",
        "description": "배당 달력",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"from": "2025-01-01", "to": "2025-01-31"}},
    },
    {
        "tool_name": "fmp_ipo_calendar",
        "service": "stable",
        "endpoint": "ipo-calendar",
        "description": "IPO 달력",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"from": "2025-01-01", "to": "2025-01-31"}},
    },

    # ── News
    {
        "tool_name": "fmp_stock_news",
        "service": "stable",
        "endpoint": "stock-news",
        "description": "주식 뉴스",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"tickers": "AAPL", "limit": 1}},
    },

    # ── Indexes
    {
        "tool_name": "fmp_all_index_quotes",
        "service": "stable",
        "endpoint": "all-index-quotes",
        "description": "전체 주가지수 실시간 시세",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {}},
    },
    {
        "tool_name": "fmp_full_index_quotes",
        "service": "stable",
        "endpoint": "full-index-quotes",
        "description": "주가지수 시세(상세)",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"symbol": "^GSPC"}},
    },
]

# ──────────────────────────────────────────────────────────────────────────────
# 3) 내부 헬퍼: 경로 정규화 / 요청 / 재시도 / 페이지네이션
# ──────────────────────────────────────────────────────────────────────────────
def _norm_path(service: str, endpoint: str) -> str:
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    if endpoint.startswith("/"):
        return endpoint
    svc = service.lower().strip()
    if svc == "stable":
        return f"/stable/{endpoint}"
    if svc == "v3":
        return f"/api/v3/{endpoint}"
    if svc == "v4":
        return f"/api/v4/{endpoint}"
    if svc in {"api", "legacy"}:
        return f"/api/v3/{endpoint}"
    if svc == "raw":
        return f"/{endpoint}"
    return f"/stable/{endpoint}"

def _request_json(
    method: str,
    url_or_path: str,
    params: Optional[Dict[str, Any]] = None,
    max_retries: int = 3,
) -> Any:
    qp = dict(params or {})
    qp["apikey"] = FMP_API_KEY
    attempt = 0
    while True:
        try:
            resp = client.request(method, url_or_path, params=qp)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            # 429/5xx 지수 백오프
            if status in (429, 500, 502, 503, 504) and attempt < max_retries:
                time.sleep((2 ** attempt) + random.random())
                attempt += 1
                continue
            text = e.response.text[:500]
            raise RuntimeError(f"FMP 요청 실패(HTTP {status}): {text}")
        except Exception as e:
            if attempt < max_retries:
                time.sleep((2 ** attempt) + random.random())
                attempt += 1
                continue
            raise RuntimeError(f"네트워크 오류: {e}")

def _paginate(
    method: str,
    url_or_path: str,
    params: Dict[str, Any],
    paginate: bool,
    page_param: str,
    start_page: int,
    max_pages: int,
) -> Any:
    if not paginate:
        return _request_json(method, url_or_path, params)
    all_rows: List[Any] = []
    page = start_page
    for _ in range(max_pages):
        p = dict(params)
        p[page_param] = page
        chunk = _request_json(method, url_or_path, p)
        if not chunk:
            break
        if isinstance(chunk, list):
            if not chunk:
                break
            all_rows.extend(chunk)
        else:
            all_rows.append(chunk)
            break
        page += 1
    return all_rows

# ──────────────────────────────────────────────────────────────────────────────
# 4) 범용 호출 툴
# ──────────────────────────────────────────────────────────────────────────────
@mcp.tool()
def fmp_call(
    endpoint: str,
    service: str = "stable",
    params: Optional[Dict[str, Any]] = None,
    symbol: Optional[str] = None,
    paginate: bool = False,
    page_param: str = "page",
    start_page: int = 0,
    max_pages: int = 1,
    method: str = "GET",
) -> Any:
    """
    FMP 엔드포인트 범용 호출기.
    예) endpoint='key-metrics', service='stable', params={'symbol':'AAPL','limit':5}
    """
    url_or_path = _norm_path(service, endpoint)
    qp = dict(params or {})
    if symbol and "symbol" not in qp:
        qp["symbol"] = symbol
    return _paginate(method, url_or_path, qp, paginate, page_param, start_page, max_pages)

# ──────────────────────────────────────────────────────────────────────────────
# 5) 카탈로그 기반 동적 툴 등록
#    - 각 엔드포인트가 MCP 액션 목록에 개별 툴로 노출됩니다.
# ──────────────────────────────────────────────────────────────────────────────
def _register_catalog_tools():
    for item in FMP_CATALOG:
        tool_name = item["tool_name"]
        service = item["service"]
        endpoint = item["endpoint"]
        description = item["description"]
        plan_hint = item["plan_hint"]
        default_params = dict(item.get("default_params", {}))

        def _factory(_service=service, _endpoint=endpoint, _defaults=default_params, _desc=description, _plan=plan_hint):
            # 공통 시그니처(필요 파라미터는 params로 전달)
            def tool(
                params: Optional[Dict[str, Any]] = None,
                symbol: Optional[str] = None,
                paginate: bool = False,
                page_param: str = "page",
                start_page: int = 0,
                max_pages: int = 1,
                method: str = "GET",
            ) -> Any:
                qp = dict(_defaults)
                if params:
                    qp.update(params)
                return fmp_call(
                    endpoint=_endpoint,
                    service=_service,
                    params=qp,
                    symbol=symbol,
                    paginate=paginate,
                    page_param=page_param,
                    start_page=start_page,
                    max_pages=max_pages,
                    method=method,
                )

            # 문서 문자열에 요금제 힌트 노출
            tool.__doc__ = f"{_desc}  |  Plan hint: {_plan}"
            tool.__name__ = tool_name  # MCP 툴 이름으로 사용
            return tool

        # 동적 등록
        dyn_tool = _factory()
        # 데코레이터 방식으로 등록
        mcp.tool()(dyn_tool)

_register_catalog_tools()

# ──────────────────────────────────────────────────────────────────────────────
# 6) 액세스 점검/목록 도구
# ──────────────────────────────────────────────────────────────────────────────
def _check_access(item: Dict[str, Any]) -> Dict[str, Any]:
    """해당 엔드포인트가 현재 API 키로 접근 가능한지 간단 점검."""
    service = item["service"]
    endpoint = item["endpoint"]
    url_or_path = _norm_path(service, endpoint)

    params = {}
    test = item.get("test") or {}
    if "params" in test and isinstance(test["params"], dict):
        params.update(test["params"])

    try:
        _ = _request_json("GET", url_or_path, params=params, max_retries=1)
        return {"ok": True, "error": None}
    except Exception as e:
        # 오류메시지 앞부분만
        msg = str(e)
        return {"ok": False, "error": msg[:200]}

@mcp.tool()
def list_fmp_endpoints(category: Optional[str] = None, run_check: bool = False) -> List[Dict[str, Any]]:
    """
    FMP 카탈로그 목록 반환.
    - category: 현재는 카탈로그가 간단하여 무시됨(필요 시 확장)
    - run_check=True면 각 엔드포인트에 대한 접근성(현재 키 기준)을 실시간으로 확인
    """
    out: List[Dict[str, Any]] = []
    for item in FMP_CATALOG:
        row = {
            "tool_name": item["tool_name"],
            "service": item["service"],
            "endpoint": item["endpoint"],
            "description": item["description"],
            "plan_hint": item["plan_hint"],
            "default_params": item.get("default_params", {}),
        }
        if run_check:
            row["access"] = _check_access(item)  # {"ok": bool, "error": str|None}
        out.append(row)
    return out

@mcp.tool()
def test_endpoint_access(service: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    임의 엔드포인트 접근성 테스트(현재 API 키 기준).
    예) service='stable', endpoint='quote', params={'symbol':'AAPL'}
    """
    try:
        url_or_path = _norm_path(service, endpoint)
        data = _request_json("GET", url_or_path, params=params or {}, max_retries=1)
        # 응답이 크면 요약
        small = data
        try:
            if isinstance(data, list) and len(data) > 3:
                small = data[:3]
        except Exception:
            pass
        return {"ok": True, "sample": small}
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}

# ──────────────────────────────────────────────────────────────────────────────
# 7) 자주 쓰는 단축 툴(기존)
# ──────────────────────────────────────────────────────────────────────────────
@mcp.tool()
def search_name(query: str, limit: int = 10, exchange: Optional[str] = None) -> Any:
    """회사 이름으로 티커 찾기 (stable/search-name) | Plan hint: Basic(EOD)"""
    params = {"query": query, "limit": limit}
    if exchange:
        params["exchange"] = exchange
    return fmp_call(endpoint="search-name", service="stable", params=params)

@mcp.tool()
def get_quote(symbol: str) -> Any:
    """실시간 시세 (stable/quote) | Plan hint: Starter+"""
    return fmp_call(endpoint="quote", service="stable", params={"symbol": symbol})

@mcp.tool()
def get_income_statement(symbol: str, period: str = "annual", limit: int = 1) -> Any:
    """손익계산서 (stable/income-statement) | Plan hint: Starter+"""
    return fmp_call(
        endpoint="income-statement",
        service="stable",
        params={"symbol": symbol, "period": period, "limit": limit},
    )

# ──────────────────────────────────────────────────────────────────────────────
# 8) 리소스 & 헬스체크
# ──────────────────────────────────────────────────────────────────────────────
@mcp.resource("help://fmp-universal")
def help_doc() -> str:
    return (
        "FMP Universal MCP 도움말\n"
        "1) 범용 호출: fmp_call(endpoint, service='stable'|'v3'|'v4'|'api'|'raw', params={}, symbol?, ...)\n"
        "2) 카탈로그 툴: fmp_* (엔드포인트별 개별 액션, plan_hint 포함)\n"
        "3) 점검: list_fmp_endpoints(run_check=True) / test_endpoint_access()\n"
        "문서/가격: https://site.financialmodelingprep.com/developer/docs , /developer/docs/pricing\n"
    )

def health(_request):
    return PlainTextResponse("OK")

# 스트리머블 HTTP MCP를 /mcp 경로에 마운트
app = mcp.streamable_http_app()
app.add_route("/health", health)

class MCPApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """
    /mcp 요청에 대해 서버 전용 API 키를 요구하는 미들웨어.
    - 허용: /health (무인증)
    - 보호: /mcp 하위 경로 전부
    - 키 전달 방법:
        1) 헤더: X-API-Key: <key>
        2) 헤더: Authorization: Bearer <key>
        3) 쿼리: ?api_key=<key>   (권장하지 않지만 편의상 허용)
    """
    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        path = request.url.path.rstrip("/")

        # 1) 헬스체크는 항상 통과
        if path == "/health":
            return await call_next(request)

        # 2) /mcp 보호
        if path.startswith("/mcp"):
            key = request.headers.get("x-api-key")
            if not key:
                auth = request.headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    key = auth.split(" ", 1)[1]
            if not key:
                key = request.query_params.get("api_key")

            if not key or not hmac.compare_digest(key, self.api_key):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)

        return await call_next(request)

app.add_middleware(MCPApiKeyAuthMiddleware, api_key=PRODUCT_API_KEY)


# ──────────────────────────────────────────────────────────────────────────────
# 9) 실행(로컬/Render)
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
