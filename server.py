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

import json

# ASGI / Starlette
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# ──────────────────────────────────────────────────────────────────────────────
# 0) 환경설정 / HTTP 클라이언트
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()

FMP_API_KEY = os.getenv("FMP_API_KEY")
if not FMP_API_KEY:
    raise RuntimeError("FMP_API_KEY가 비었습니다. .env 또는 Render 환경변수를 확인하세요.")

# 인증은 선택적으로만 강제합니다.
# - REQUIRE_MCP_AUTH=1 인 경우에만 /mcp 보호
# - 그 외에는 공개(개발/연결 편의를 위해)
REQUIRE_MCP_AUTH = os.getenv("REQUIRE_MCP_AUTH", "0") == "1"
PRODUCT_API_KEY = os.getenv("PRODUCT_API_KEY")  # 없을 수도 있음
if REQUIRE_MCP_AUTH and not PRODUCT_API_KEY:
    raise RuntimeError("REQUIRE_MCP_AUTH=1인데 PRODUCT_API_KEY가 없습니다.")

# CORS 허용 오리진(쉼표 구분). 기본: ChatGPT 도메인들.
CORS_ALLOW_ORIGINS = os.getenv(
    "CORS_ALLOW_ORIGINS",
    "https://chatgpt.com,https://chat.openai.com",
).split(",")

BASE_URL = "https://financialmodelingprep.com"
client = httpx.Client(base_url=BASE_URL, timeout=20.0)

# ──────────────────────────────────────────────────────────────────────────────
# 1) MCP 서버
# ──────────────────────────────────────────────────────────────────────────────
mcp = FastMCP("FMP Universal")

# ──────────────────────────────────────────────────────────────────────────────
# 2) 요금제/엔드포인트 카탈로그
# ──────────────────────────────────────────────────────────────────────────────
FMP_PLANS: Dict[str, Dict[str, Any]] = {
    "Basic(EOD)": {
        "timeframe": "End of Day",
        "notes": "기본 무상(또는 저가) 플랜. EOD 데이터 중심, 호출/히스토리 제한."
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
        "endpoint": "search-symbol",
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
        "tool_name": "fmp_quote_short",
        "service": "stable",
        "endpoint": "quote-short",
        "description": "간략 시세",
        "plan_hint": "Basic(EOD)",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL"}},
    },
    {
        "tool_name": "fmp_historical_price_full",
        "service": "stable",
        "endpoint": "historical-price-eod/full",
        "description": "EOD 히스토리(OHLCV) 전체",
        "plan_hint": "Basic(EOD)",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL", "from": "2023-01-01", "to": "2023-02-01"}},
    },
    {
        "tool_name": "fmp_historical_price_eod_light",  # 권장 추가
        "service": "stable",
        "endpoint": "historical-price-eod/light",
        "description": "EOD 히스토리(경량)",
        "plan_hint": "Basic(EOD)",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL", "from": "2024-01-01", "to": "2024-02-01"}},
    },


    # ── Fundamentals
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
        "tool_name": "fmp_financial_statement_full_as_reported",
        "service": "stable",
        "endpoint": "financial-statement-full-as-reported",
        "description": "As reported: 전체 재무제표",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL", "period": "annual", "limit": 1}},
    },
    {
        "tool_name": "fmp_cash_flow_statement_as_reported",
        "service": "stable",
        "endpoint": "cash-flow-statement-as-reported",
        "description": "As reported: 현금흐름표",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL", "period": "annual", "limit": 1}},
    },
    {
        "tool_name": "fmp_balance_sheet_statement_as_reported",
        "service": "stable",
        "endpoint": "balance-sheet-statement-as-reported",
        "description": "As reported: 대차대조표",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL", "period": "annual", "limit": 1}},
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
        "endpoint": "profile",
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
    {
        "tool_name": "fmp_profile_cik",
        "service": "stable",
        "endpoint": "profile-cik",
        "description": "회사 프로필(CIK 기반)",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"cik": "0000320193"}},
    },
    {
        "tool_name": "fmp_sec_profile",
        "service": "stable",
        "endpoint": "sec-profile",
        "description": "SEC 기반 회사 상세 프로필",
        "plan_hint": "Starter+",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL"}},
    },

    # ── Calendars
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

            tool.__doc__ = f"{_desc}  |  Plan hint: {_plan}"
            tool.__name__ = tool_name
            return tool

        dyn_tool = _factory()
        mcp.tool()(dyn_tool)

_register_catalog_tools()

# ──────────────────────────────────────────────────────────────────────────────
# 6) 액세스 점검/목록 도구
# ──────────────────────────────────────────────────────────────────────────────
def _check_access(item: Dict[str, Any]) -> Dict[str, Any]:
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
        msg = str(e)
        return {"ok": False, "error": msg[:200]}

@mcp.tool()
def list_fmp_endpoints(category: Optional[str] = None, run_check: bool = False) -> List[Dict[str, Any]]:
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
            row["access"] = _check_access(item)
        out.append(row)
    return out

@mcp.tool()
def test_endpoint_access(service: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        url_or_path = _norm_path(service, endpoint)
        data = _request_json("GET", url_or_path, params=params or {}, max_retries=1)
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
# 7) 단축 툴
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

# --- add near other tools (e.g., after #7 단축 툴) ---

@mcp.tool()
def search(query: str, limit: int = 5) -> str:
    """
    Deep Research / Connectors 규격: results 배열을 담은 JSON 문자열을 단일 text content로 반환
    """
    # FMP 검색으로 예시 구현
    # stable/search-name 또는 stable/search 중 하나 사용
    data = fmp_call(endpoint="search-name", service="stable",
                    params={"query": query, "limit": limit})

    results = []
    for row in (data or []):
        sym = row.get("symbol") or row.get("symbolName") or row.get("cik") or ""
        name = row.get("name") or row.get("companyName") or sym or "Unknown"
        if not sym:
            continue
        results.append({
            "id": sym,                               # fetch에서 사용할 고유 ID
            "title": f"{name} ({sym})",
            "url": f"https://financialmodelingprep.com/stable/profile?symbol={sym}"
        })

    payload = {"results": results}
    return json.dumps(payload, ensure_ascii=False)

@mcp.tool()
def fetch(id: str) -> str:
    """
    Deep Research / Connectors 규격: 단일 문서 객체(JSON 문자열) 반환
    - id: search 결과의 id (여기서는 티커 심볼)
    """
    sym = id.strip().upper()

    # 프로필/시세 일부를 모아 '문서의 본문 text' 구성
    profile = fmp_call(endpoint="profile", service="stable", params={"symbol": sym}, method="GET")
    quote   = fmp_call(endpoint="quote", service="stable", params={"symbol": sym}, method="GET")

    name = (profile[0].get("companyName") if isinstance(profile, list) and profile else None) or sym
    desc = (profile[0].get("description") if isinstance(profile, list) and profile else None) or ""
    price = (quote[0].get("price") if isinstance(quote, list) and quote else None)

    # 사람 읽기 좋은 텍스트 본문 작성
    text_lines = [
        f"Symbol: {sym}",
        f"Name: {name}",
        f"Price: {price}" if price is not None else "Price: N/A",
        "",
        desc or "No description.",
    ]
    doc = {
        "id": sym,
        "title": f"{name} ({sym})",
        "text": "\n".join(text_lines),
        "url": f"https://financialmodelingprep.com/stable/profile?symbol={sym}",
        "metadata": {"source": "FMP", "fetched_at": __import__('datetime').datetime.utcnow().isoformat() + "Z"},
    }
    return json.dumps(doc, ensure_ascii=False)


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

# ──────────────────────────────────────────────────────────────────────────────
# 9) 스트리머블 HTTP MCP 앱 생성 + CORS/인증/호환 미들웨어
# ──────────────────────────────────────────────────────────────────────────────

# 9-1) 라이브러리에서 제공하는 Starlette 앱
app: Starlette = mcp.streamable_http_app()

# 9-2) 헬스 체크 라우트
app.add_route("/health", health, methods=["GET"])

# 9-3) 프리플라이트 전용(일부 프록시 환경에서 필요)
def options_ok(_request: Request):
    return PlainTextResponse("", status_code=200)
app.add_route("/mcp", options_ok, methods=["OPTIONS"])
app.add_route("/mcp/", options_ok, methods=["OPTIONS"])

# 9-4) CORS (브라우저에서 직접 붙는 ChatGPT Connectors 지원)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ALLOW_ORIGINS if o.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept", "X-API-Key", "Mcp-Session-Id"],
    expose_headers=["Mcp-Session-Id"],
    max_age=86400,
)

# 9-5) Accept 헤더/SSE 및 트레일링 슬래시 호환용 ASGI 미들웨어
class SSEAcceptAndPathNormalizeMiddleware:
    """
    - GET /mcp 요청에서 Accept에 text/event-stream이 빠져 있어도 포함시켜 SSE 연결을 허용
    - /mcp/ → /mcp 로 내부 경로 정규화(리다이렉트 없이 처리)
    """
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        method = scope.get("method", "").upper()

        # path 정규화
        if path == "/mcp/":
            scope = dict(scope)
            scope["path"] = "/mcp"
            scope["raw_path"] = b"/mcp"

        # SSE Accept 보완
        if path == "/mcp" and method == "GET":
            headers = [(k.lower(), v) for (k, v) in scope.get("headers", [])]
            accept_idx = next((i for i, (k, _) in enumerate(headers) if k == b"accept"), None)
            if accept_idx is not None:
                k, v = headers[accept_idx]
                val = v.decode("latin-1").lower()
                if "text/event-stream" not in val:
                    val = (val + ",text/event-stream").strip(",")
                    headers[accept_idx] = (k, val.encode("latin-1"))
            else:
                headers.append((b"accept", b"text/event-stream"))
            scope = dict(scope)
            scope["headers"] = headers

        return await self.app(scope, receive, send)

app.add_middleware(SSEAcceptAndPathNormalizeMiddleware)  # type: ignore

# 9-6) 인증 미들웨어(선택 적용)
class MCPApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """
    /mcp 요청에 대해 서버 전용 API 키를 '선택적으로' 요구하는 미들웨어.
    - REQUIRE_MCP_AUTH=1 인 경우에만 강제
    - 허용: /health (무인증)
    - 허용: GET /mcp (SSE) — 초기 연결 호환을 위해 항상 허용
    - 키 전달 방법:
        1) Authorization: Bearer <key>
        2) X-API-Key: <key>
        3) (편의) ?api_key=<key>
    """
    def __init__(self, app: ASGIApp, api_key: Optional[str]):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        path = request.url.path.rstrip("/")
        method = request.method.upper()

        # 항상 허용
        if path == "/health":
            return await call_next(request)

        # 미강제 모드면 통과
        if not REQUIRE_MCP_AUTH:
            return await call_next(request)

        # GET /mcp(SSE)는 무조건 허용하여 초기 연결 실패를 방지
        if path == "/mcp" and method == "GET":
            return await call_next(request)

        # 나머지 /mcp* 는 인증
        if path.startswith("/mcp"):
            key = request.headers.get("x-api-key")
            if not key:
                auth = request.headers.get("authorization", "")
                if auth.lower().startswith("bearer "):
                    key = auth.split(" ", 1)[1]
            if not key:
                key = request.query_params.get("api_key")

            if not key or not self.api_key or not hmac.compare_digest(key, self.api_key):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)

        return await call_next(request)

app.add_middleware(MCPApiKeyAuthMiddleware, api_key=PRODUCT_API_KEY)

# ──────────────────────────────────────────────────────────────────────────────
# 10) 실행(로컬/Render)
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
