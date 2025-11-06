# server.py
from __future__ import annotations

import os
import time
import random
import hmac
import json
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

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

# (변경) 서버/환경변수 FMP 키는 더 이상 사용하지 않습니다. 남겨두되 강제/폴백 제거.
FMP_API_KEY = os.getenv("FMP_API_KEY")  # not used as fallback anymore

# (변경) PRODUCT_API_KEY 개념은 제거합니다. 아래 두 변수는 더 이상 인증 강제에 쓰지 않습니다.
REQUIRE_MCP_AUTH = False  # os.getenv("REQUIRE_MCP_AUTH", "0") == "1"  # deprecated: not enforced
PRODUCT_API_KEY = None    # os.getenv("PRODUCT_API_KEY")  # deprecated: not used

# 쿼리스트링으로 /mcp 인증 허용 여부(로그 유출 위험). (deprecated with PRODUCT_API_KEY removal)
ALLOW_QUERY_API_KEY = False  # os.getenv("ALLOW_QUERY_API_KEY", "0") == "1"  # deprecated

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

# 세션별 사용자 FMP 키 저장 (Connectors/Deep Research에서 세션 단위 사용)
CURRENT_SESSION_ID: ContextVar[Optional[str]] = ContextVar("CURRENT_SESSION_ID", default=None)
SESSION_FMP_KEYS: Dict[str, str] = {}
# (추가) URL로 전달된 사용자 키를 세션 없이도 임시 사용할 수 있도록 기본 슬롯을 둡니다.
DEFAULT_FMP_KEY_FROM_URL: Optional[str] = None

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
        "tool_name": "fmp_historical_price_full",   # EOD 전체
        "service": "stable",
        "endpoint": "historical-price-eod/full",
        "description": "EOD 히스토리(OHLCV) 전체",
        "plan_hint": "Basic(EOD)",
        "default_params": {},
        "test": {"params": {"symbol": "AAPL", "from": "2023-01-01", "to": "2023-02-01"}},
    },
    {
        "tool_name": "fmp_historical_price_eod_light",
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
    # (변경) 서버 기본키 폴백 제거: apikey는 반드시 사전에 사용자 키로 설정되어 있어야 합니다.
    if "apikey" not in qp or not qp["apikey"]:
        raise RuntimeError("FMP apikey is missing. Provide ?apiKey=... (saved to session) or set via set_fmp_api_key().")

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
            # fmp_call에서 상태코드 분류를 위해 원본 예외 전달
            raise
        except Exception as e:
            if attempt < max_retries:
                time.sleep((2 ** attempt) + random.random())
                attempt += 1
                continue
            raise

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
# 3-1) 사용자 키 해석/오류 표준화
# ──────────────────────────────────────────────────────────────────────────────
def _resolve_user_fmp_key(qp: Dict[str, Any]) -> Optional[str]:
    # 1) 파라미터에 직접 포함
    for k in ("apiKey", "apikey", "api_key"):
        if k in qp and qp[k]:
            return str(qp[k]).strip()
    # 2) 세션 저장 키
    sid = CURRENT_SESSION_ID.get()
    if sid and sid in SESSION_FMP_KEYS:
        return SESSION_FMP_KEYS[sid]
    # 3) (보강) URL로 전달된 기본키가 있다면 사용
    if DEFAULT_FMP_KEY_FROM_URL:
        return DEFAULT_FMP_KEY_FROM_URL
    return None

def _plan_hint_for(service: str, endpoint: str) -> Optional[str]:
    for it in FMP_CATALOG:
        if it["service"] == service and it["endpoint"] == endpoint:
            return it.get("plan_hint")
    return None

def _classify_fmp_http_error(service: str, endpoint: str, status: int, body_text: str) -> Dict[str, Any]:
    t = (body_text or "").lower()
    plan_like = any(k in t for k in [
        "plan", "upgrade", "permission", "not allowed", "access", "payment", "quota", "rate limit"
    ])

    code = "UNKNOWN"
    needs_confirm = False
    suggested: List[str] = []

    if status == 401:
        code = "AUTH_INVALID"
        needs_confirm = True
        suggested.append("제공된 FMP API Key를 확인/갱신하세요.")
    elif status == 402:
        code = "PAYMENT_REQUIRED"
        needs_confirm = True
        suggested.append("요금제 결제/업그레이드가 필요합니다.")
    elif status == 403:
        code = "PLAN_OR_PERMISSION"
        needs_confirm = True
        suggested.append("현재 요금제로 접근 불가인 엔드포인트입니다.")
    elif status == 429:
        code = "RATE_LIMIT"
        suggested.append("호출 빈도를 낮추거나 요금제를 상향하세요.")
    elif status == 404:
        code = "NOT_FOUND"
        suggested.append("엔드포인트/심볼/파라미터를 재확인하세요.")
    elif status >= 500:
        code = "UPSTREAM_ERROR"
        suggested.append("잠시 후 재시도하세요.")

    plan_hint = _plan_hint_for(service, endpoint)
    if plan_like and status not in (404,):
        needs_confirm = True

    if plan_hint:
        suggested.append(f"이 호출의 권장 플랜 힌트: {plan_hint}")

    return {
        "code": code,
        "status": status,
        "needs_user_confirmation": needs_confirm,
        "message": (body_text or "")[:300],
        "plan_hint": plan_hint,
        "suggested_action": " / ".join(suggested) if suggested else None,
        "endpoint": endpoint,
        "service": service,
    }

def _error_payload_from_exception(e: Exception) -> Dict[str, Any]:
    try:
        msg = e.args[0] if e.args else ""
        if isinstance(msg, str) and msg.startswith("{"):
            return json.loads(msg)
    except Exception:
        pass
    return {"code": "CLIENT_ERROR", "message": str(e)[:500], "needs_user_confirmation": False}

# ──────────────────────────────────────────────────────────────────────────────
# 4) 범용 호출 툴 (사용자 API 키 필수)
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
    - 모든 호출은 '사용자 제공' FMP API 키를 사용(세션에 저장되거나 params에 포함)
    - 키가 없으면 _error 페이로드로 반환하여 LLM이 사용자에게 키 입력/확인을 요청할 수 있게 함
    - 요금제/권한 부족 등은 _error.needs_user_confirmation=True 로 표시
    """
    url_or_path = _norm_path(service, endpoint)
    qp = dict(params or {})
    if symbol and "symbol" not in qp:
        qp["symbol"] = symbol

    # 사용자 키 확인
    user_key = _resolve_user_fmp_key(qp)
    if not user_key:
        return {
            "_error": {
                "code": "MISSING_API_KEY",
                "needs_user_confirmation": False,
                "suggest_web_search": True,
                "message": "MCP URL에 ?apiKey=... 로 FMP 키를 전달해야 합니다. 현재 키가 없어 API로는 답변을 제공할 수 없으며, 공개 웹 검색으로 참고 값을 제시할 수 있습니다.",
                "explain_to_user": "MCP 서버 등록 시 URL 끝에 ?apiKey=<YOUR_FMP_KEY>를 포함해 주세요."
            }
        }

    qp["apikey"] = user_key  # 사용자 키 강제

    try:
        return _paginate(method, url_or_path, qp, paginate, page_param, start_page, max_pages)
    except httpx.HTTPStatusError as e:
        st = e.response.status_code
        body = e.response.text
        classified = _classify_fmp_http_error(service, endpoint, st, body)
        return {"_error": classified}
    except Exception as e:
        return {"_error": _error_payload_from_exception(e)}

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

        def _factory(_service=service, _endpoint=endpoint, _defaults=default_params, _desc=description, _plan=plan_hint, _name=tool_name):
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
            tool.__name__ = _name
            return tool

        dyn_tool = _factory()
        mcp.tool()(dyn_tool)

_register_catalog_tools()

# ──────────────────────────────────────────────────────────────────────────────
# 6) 액세스 점검/목록 도구 (사용자 키 필요)
# ──────────────────────────────────────────────────────────────────────────────
def _check_access(item: Dict[str, Any]) -> Dict[str, Any]:
    service = item["service"]
    endpoint = item["endpoint"]
    url_or_path = _norm_path(service, endpoint)

    params = {}
    test = item.get("test") or {}
    if "params" in test and isinstance(test["params"], dict):
        params.update(test["params"])

    # (변경) 사용자 키가 없으면 헬스 체크 불가
    user_key = _resolve_user_fmp_key({})
    if not user_key:
        return {
            "ok": False,
            "error": "No user FMP API key. Register MCP with ?apiKey=<YOUR_FMP_KEY> or call set_fmp_api_key()."
        }
    params = dict(params)
    params["apikey"] = user_key

    try:
        _ = _request_json("GET", url_or_path, params=params, max_retries=1)
        return {"ok": True, "error": None}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
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
        p = dict(params or {})
        # (변경) 사용자 키 필수
        user_key = _resolve_user_fmp_key({})
        if not user_key:
            return {"ok": False, "error": "No user FMP API key. Pass ?apiKey=... or set_fmp_api_key()."}
        p["apikey"] = user_key

        data = _request_json("GET", url_or_path, params=p, max_retries=1)
        small = data
        try:
            if isinstance(data, list) and len(data) > 3:
                small = data[:3]
        except Exception:
            pass
        return {"ok": True, "sample": small}
    except httpx.HTTPStatusError as e:
        return {"ok": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:500]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:500]}

# ──────────────────────────────────────────────────────────────────────────────
# 7) 단축 툴 + Deep Research 규격(search/fetch) + ping
# ──────────────────────────────────────────────────────────────────────────────
@mcp.tool()
def ping() -> Dict[str, Any]:
    """연결/세션 진단용 핑 도구"""
    sid = CURRENT_SESSION_ID.get()
    return {
        "ok": True,
        "session_id": sid,
        "session_has_fmp_key": bool(sid and sid in SESSION_FMP_KEYS),
    }

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

@mcp.tool()
def search(query: str, limit: int = 5) -> str:
    """
    Deep Research / Connectors 규격: results 배열을 담은 JSON 문자열을 단일 text content로 반환
    """
    data = fmp_call(endpoint="search-name", service="stable",
                    params={"query": query, "limit": limit})

    # 에러 패스스루 (문자열 JSON 반환)
    if isinstance(data, dict) and "_error" in data:
        return json.dumps(data, ensure_ascii=False)

    results = []
    for row in (data or []):
        sym = row.get("symbol") or row.get("symbolName") or row.get("cik") or ""
        name = row.get("name") or row.get("companyName") or sym or "Unknown"
        if not sym:
            continue
        results.append({
            "id": sym,  # fetch에서 사용할 고유 ID
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
    if isinstance(profile, dict) and "_error" in profile:
        return json.dumps(profile, ensure_ascii=False)

    quote = fmp_call(endpoint="quote", service="stable", params={"symbol": sym}, method="GET")
    if isinstance(quote, dict) and "_error" in quote:
        return json.dumps(quote, ensure_ascii=False)

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
# 7-1) 사용자 API 키 등록/삭제 툴
# ──────────────────────────────────────────────────────────────────────────────
@mcp.tool()
def set_fmp_api_key(api_key: str) -> Dict[str, Any]:
    """
    현재 MCP 세션에 사용자 FMP API 키를 등록합니다.
    이후 모든 fmp_* 호출에 이 키가 사용됩니다.
    """
    sid = CURRENT_SESSION_ID.get()
    if not sid:
        return {"ok": False, "_error": {"code": "NO_SESSION", "message": "세션 ID를 찾을 수 없습니다."}}
    key = (api_key or "").strip()
    if not key:
        return {"ok": False, "_error": {"code": "EMPTY_KEY", "message": "빈 API Key입니다."}}
    SESSION_FMP_KEYS[sid] = key
    return {"ok": True}

@mcp.tool()
def clear_fmp_api_key() -> Dict[str, Any]:
    """
    현재 MCP 세션에서 사용자 FMP API 키를 제거합니다.
    """
    sid = CURRENT_SESSION_ID.get()
    if not sid:
        return {"ok": False, "_error": {"code": "NO_SESSION", "message": "세션 ID를 찾을 수 없습니다."}}
    SESSION_FMP_KEYS.pop(sid, None)
    return {"ok": True}

# ──────────────────────────────────────────────────────────────────────────────
# 8) 리소스 & 헬스체크
# ──────────────────────────────────────────────────────────────────────────────
@mcp.resource("help://fmp-universal")
def help_doc() -> str:
    return (
        "FMP Universal MCP 도움말\n"
        "1) 사용자 키 전달(기본): MCP URL에 ?apiKey=<YOUR_FMP_KEY>\n"
        "   (선택) 세션 중 변경: set_fmp_api_key(api_key) / clear_fmp_api_key()\n"
        "2) 범용 호출: fmp_call(endpoint, service='stable'|'v3'|'v4'|'api'|'raw', params={}, symbol?, ...)\n"
        "3) 카탈로그 툴: fmp_* (엔드포인트별 개별 액션, plan_hint 포함)\n"
        "4) 점검: list_fmp_endpoints(run_check=True) / test_endpoint_access()\n"
        "5) 오류: _error.code/status/needs_user_confirmation/suggested_action/plan_hint 로 구조화 반환\n"
        "문서/가격: https://site.financialmodelingprep.com/developer/docs , /developer/docs/pricing\n"
    )

def health(_request):
    return PlainTextResponse("OK")

# 루트 인덱스(404 혼동 방지)
def index(_request: Request):
    info = {
        "name": "FMP Universal MCP",
        "status": "ok",
        "endpoints": {
            "mcp": "/mcp",
            "health": "/health",
            "well_known_oidc": "/.well-known/openid-configuration (not supported)",
            "well_known_oauth": "/.well-known/oauth-authorization-server (not supported)",
        },
        # (변경) PRODUCT_API_KEY 기반 서버 인증 제거 안내
        "auth": {
            "server_protection": "removed",
            "header_usage": "N/A (no PRODUCT_API_KEY)",
            "query_param_auth_allowed": False,
        },
        "fmp_key_flow": {
            "set_tool": "set_fmp_api_key(api_key)",
            "http_header_hint": "X-FMP-Api-Key + Mcp-Session-Id",
            "url_param_hint": "MCP 등록 시 ?apiKey=<YOUR_FMP_KEY>",
        },
        "note": "이 페이지는 루트 404 혼동을 줄이기 위한 인덱스입니다.",
    }
    return JSONResponse(info, status_code=200)

# OIDC/OAuth 자동탐색에 대한 명시적 안내(404 대신 의미있는 설명 제공)
def well_known_oidc(_request: Request):
    return JSONResponse(
        {"error": "oauth_not_supported", "message": "이 서버는 OAuth/OIDC 인증을 제공하지 않습니다. MCP 연결시 인증을 API Key(사용자 제공)로 설정하세요."},
        status_code=404,
    )

def well_known_oauth(_request: Request):
    return JSONResponse(
        {"error": "oauth_not_supported", "message": "이 서버는 OAuth/OIDC 인증을 제공하지 않습니다. Authorization 헤더 기반 서버 키는 사용하지 않습니다."},
        status_code=404,
    )

# ──────────────────────────────────────────────────────────────────────────────
# 9) 스트리머블 HTTP MCP 앱 생성 + CORS/인증/호환 미들웨어
# ──────────────────────────────────────────────────────────────────────────────
app: Starlette = mcp.streamable_http_app()

# 인덱스/헬스/웰노운 라우트
app.add_route("/", index, methods=["GET"])
app.add_route("/health", health, methods=["GET"])
app.add_route("/.well-known/openid-configuration", well_known_oidc, methods=["GET"])
app.add_route("/.well-known/oauth-authorization-server", well_known_oauth, methods=["GET"])

# (추가) 로컬 URL로 바로 테스트할 수 있는 HTTP 엔드포인트들
async def http_fmp_profile(request: Request):
    symbol = request.path_params.get("symbol", "").strip().upper()
    qp: Dict[str, Any] = {"symbol": symbol}
    # URL 또는 헤더에서 사용자 키 수집(있다면 params에 'apiKey'로 전달)
    api_key = request.query_params.get("apiKey") or request.headers.get("X-FMP-Api-Key")
    if api_key:
        qp["apiKey"] = api_key
    data = fmp_call(endpoint="profile", service="stable", params=qp, method="GET")
    return JSONResponse(data)

async def http_fmp_quote(request: Request):
    symbol = request.path_params.get("symbol", "").strip().upper()
    qp: Dict[str, Any] = {"symbol": symbol}
    api_key = request.query_params.get("apiKey") or request.headers.get("X-FMP-Api-Key")
    if api_key:
        qp["apiKey"] = api_key
    data = fmp_call(endpoint="quote", service="stable", params=qp, method="GET")
    return JSONResponse(data)

async def http_fmp_call(request: Request):
    # 신뢰 가능한 클라이언트 전용 간단 프록시: /fmp/call?path=/api/v3/profile/AAPL&apiKey=...
    path = request.query_params.get("path")
    if not path:
        return JSONResponse({"error": "path query parameter is required"}, status_code=400)
    qp: Dict[str, Any] = {}
    api_key = request.query_params.get("apiKey") or request.headers.get("X-FMP-Api-Key")
    if api_key:
        qp["apiKey"] = api_key
    # 다른 쿼리들도 그대로 전달(단, path/apiKey는 제외)
    for k, v in request.query_params.multi_items():
        if k not in {"path", "apiKey"}:
            qp[k] = v
    data = fmp_call(endpoint=path, service="raw", params=qp, method="GET")
    return JSONResponse(data)

app.add_route("/fmp/profile/{symbol}", http_fmp_profile, methods=["GET"])
app.add_route("/fmp/quote/{symbol}",   http_fmp_quote,   methods=["GET"])
app.add_route("/fmp/call",             http_fmp_call,    methods=["GET"])

# 프리플라이트 전용(일부 프록시 환경에서 필요)
def options_ok(_request: Request):
    return PlainTextResponse("", status_code=200)
app.add_route("/mcp", options_ok, methods=["OPTIONS"])
app.add_route("/mcp/", options_ok, methods=["OPTIONS"])

# CORS (브라우저에서 직접 붙는 ChatGPT Connectors 지원)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ALLOW_ORIGINS if o.strip()],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept", "X-API-Key", "Mcp-Session-Id", "X-FMP-Api-Key"],
    expose_headers=["Mcp-Session-Id"],
    max_age=86400,
)

# 세션 바인딩 (Mcp-Session-Id → ContextVar) + X-FMP-Api-Key / ?apiKey 자동 등록
class SessionBinderMiddleware(BaseHTTPMiddleware):
    """
    각 요청의 Mcp-Session-Id를 컨텍스트 변수에 바인딩하고,
    X-FMP-Api-Key(또는 apiKey, fmp_apikey, apikey 쿼리)가 있으면 해당 세션에 사용자 FMP 키를 자동 저장.
    """
    async def dispatch(self, request: Request, call_next):
        # 항상 먼저 사용자 키를 파악(세션ID 유무와 무관)
        user_fmp_key = (
            request.headers.get("X-FMP-Api-Key")
            or request.query_params.get("apiKey")
            or request.query_params.get("fmp_apikey")
            or request.query_params.get("apikey")
        )

        sid = request.headers.get("Mcp-Session-Id") or request.query_params.get("mcp_session_id")
        token = None
        if sid:
            token = CURRENT_SESSION_ID.set(sid)
            if user_fmp_key:
                SESSION_FMP_KEYS[sid] = user_fmp_key.strip()

        # 다음 미들웨어/핸들러 실행
        resp = await call_next(request)

        # 초기 SSE 등 응답 단계에서 세션 ID가 생기는 경우를 보강: 응답 헤더의 세션 ID로도 키 매핑
        resp_sid = resp.headers.get("Mcp-Session-Id")
        if resp_sid and user_fmp_key:
            SESSION_FMP_KEYS[resp_sid] = user_fmp_key.strip()

        # 세션 식별이 전혀 없었던 경우에도 이후 호출에서 쓰일 수 있도록 전역 기본키로 보관
        if user_fmp_key:
            global DEFAULT_FMP_KEY_FROM_URL
            DEFAULT_FMP_KEY_FROM_URL = user_fmp_key.strip()

        if token is not None:
            CURRENT_SESSION_ID.reset(token)
        return resp

app.add_middleware(SessionBinderMiddleware)  # type: ignore

# Accept 헤더/SSE 및 트레일링 슬래시 호환용 ASGI 미들웨어
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

# 인증 미들웨어(선택 적용) — (변경) PRODUCT_API_KEY 제거로 인해 로직은 무력화되지만 원문 구조는 유지합니다.
class MCPApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """
    (deprecated) /mcp 요청에 대해 서버 전용 API 키를 '선택적으로' 요구하는 미들웨어.
    현재는 사용하지 않습니다.
    """
    def __init__(self, app: ASGIApp, api_key: Optional[str]):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next):
        # 원문 구조 보존: REQUIRE_MCP_AUTH가 False이므로 그대로 통과
        return await call_next(request)

# 원문 라인 보존(무해함): 현재 PRODUCT_API_KEY=None, REQUIRE_MCP_AUTH=False라서 실질적으로 영향 없음
app.add_middleware(MCPApiKeyAuthMiddleware, api_key=PRODUCT_API_KEY)

# ──────────────────────────────────────────────────────────────────────────────
# 10) 실행(로컬/Render)
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
