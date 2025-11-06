
# FMP Universal MCP Server — README

이 리포지토리는 **Financial Modeling Prep(FMP) API**를 MCP(Model Context Protocol) 서버로 감싸서
LLM/에이전트가 자연어 지시로 다양한 금융 데이터를 조회할 수 있도록 해 줍니다.

`server.py`는 다음을 제공합니다:

- **범용 호출 툴**: `fmp_call` — FMP의 거의 모든 엔드포인트를 1개의 툴로 호출
- **카탈로그 기반 동적 툴**: 대표적인 Stable 엔드포인트들이 **각각 독립 MCP 툴**로 나타나, 액션 목록에서 바로 확인/실행
- **요금제 힌트 표기**: 각 카탈로그 툴에는 `Plan hint`가 설명에 들어가 있어 어떤 플랜에서 접근 가능한지 가늠 가능
- **접근성 점검 도구**: `list_fmp_endpoints(run_check=True)` / `test_endpoint_access(...)`로 **현재 API 키로 실제 호출 가능 여부**를 점검
- **ASGI + Uvicorn 배포**: `/mcp` 경로로 스트리머블 HTTP MCP, `/health` 헬스체크 제공 → Render.com 등 PaaS에 손쉽게 배포

> ⚠️ 주의: FMP의 실제 제공 범위/쿼터/가격은 시기에 따라 변동될 수 있습니다. `Plan hint`는 문서 기준의 **참고 정보**이며,
> **반드시 `list_fmp_endpoints(run_check=True)`** 로 _현재 API 키_에서의 접근 가능 여부를 확인하세요.

---

## 폴더 구조

```
.
├─ server.py          # MCP 서버(ASGI), 카탈로그/툴 정의
├─ requirements.txt   # 의존성
├─ render.yaml        # (선택) Render.com 배포 블루프린트
├─ .env.example       # 환경변수 템플릿
└─ .gitignore
```

---

## 요구사항

- Python 3.10+ (권장 3.11+)
- FMP API Key (`FMP_API_KEY`)
- 의존성: `mcp[cli]`, `httpx`, `python-dotenv`, `starlette`, `uvicorn`

설치:

```bash
pip install -r requirements.txt
```

환경변수 설정(택1):

- `.env` 파일 (권장)
  ```env
  FMP_API_KEY=YOUR_FMP_API_KEY
  ```
- 또는 PowerShell(임시):  
  ```powershell
  $env:FMP_API_KEY = "YOUR_FMP_API_KEY"
  ```

---

## 실행 방법

### 1) 로컬(HTTP 서버)

```bash
python server.py
# 헬스체크
curl http://localhost:8000/health  # "OK"
# MCP 엔드포인트: http://localhost:8000/mcp
```

### 2) MCP Inspector로 테스트

옵션 A) `uv` 사용
```powershell
uv run mcp dev server.py
# 브라우저에서 표시되는 Inspector UI 접속
```

옵션 B) 서버/인스펙터 분리
```powershell
# 터미널1: 서버 실행
python server.py

# 터미널2: 인스펙터 실행
npx -y @modelcontextprotocol/inspector
# 좌측 Server connection → Transport: HTTP, URL: http://localhost:8000/mcp → Connect
```

> Windows에서 `uv` 가 인식되지 않으면 `C:\Users\<you>\.local\bin`을 사용자 PATH에 추가하거나
> 세션 별칭 `Set-Alias uv "$env:USERPROFILE\.local\bin\uv.exe"`를 사용하세요.

---

## 제공 툴(요약)

### A. 범용 호출기

**`fmp_call(endpoint, service='stable'|'v3'|'v4'|'api'|'raw', params={}, symbol?, paginate?, page_param='page', start_page=0, max_pages=1, method='GET')`**

- 임의의 엔드포인트를 직접 호출합니다.
- 예시
  - `fmp_call("quote", params={"symbol":"AAPL"})`
  - `fmp_call("income-statement", params={"symbol":"TSLA","period":"annual","limit":2})`
  - `fmp_call("key-metrics", params={"symbol":"AAPL","limit":5})`

### B. 카탈로그 기반 동적 툴(액션 목록에 보임)

- `fmp_search_name` — 회사 이름으로 티커 검색 *(Plan hint: Basic(EOD))*
- `fmp_search` — 심볼/이름/ISIN/CIK/CUSIP 검색 *(Basic(EOD))*
- `fmp_available_industries` — 사용 가능한 산업 목록 *(Basic(EOD))*
- `fmp_quote` — 실시간 주가 *(Starter+)*
- `fmp_historical_price_eod_full` — EOD 히스토리(전체) *(Basic(EOD))*
- `fmp_income_statement` — 손익계산서 *(Starter+)*
- `fmp_balance_sheet_statement` — 대차대조표 *(Starter+)*
- `fmp_cash_flow_statement` — 현금흐름표 *(Starter+)*
- `fmp_key_metrics` — 핵심 지표 *(Starter+)*
- `fmp_ratios` — 재무 비율 *(Starter+)*
- `fmp_profile_symbol` — 회사 프로필(심볼) *(Starter+)*
- `fmp_profile_bulk` — 프로필 벌크 *(Starter+)*
- `fmp_earnings_calendar` — 어닝 달력 *(Starter+)*
- `fmp_dividends_calendar` — 배당 달력 *(Starter+)*
- `fmp_ipo_calendar` — IPO 달력 *(Starter+)*
- `fmp_stock_news` — 주식 뉴스 *(Starter+)*
- `fmp_all_index_quotes` — 전체 지수 시세 *(Starter+)*
- `fmp_full_index_quotes` — 지수 시세(상세) *(Starter+)*

> **참고**: 실제 사용 가능 여부는 플랜/키마다 다릅니다. 아래 점검 도구로 확인하세요.

### C. 점검 도구

- `list_fmp_endpoints(run_check: bool = False)`  
  - `run_check=True`로 호출 시, 각 엔드포인트를 **샘플 파라미터**로 실제 호출해 `{ ok: true/false, error }`를 반환합니다.
  - 액션 목록/요금제 힌트를 **한눈에 정리**하는 용도로 사용하세요.
- `test_endpoint_access(service: str, endpoint: str, params: dict = {})`  
  - 임의 엔드포인트에 대해 **즉시 호출 가능 여부**를 확인하고, 샘플 응답 일부를 돌려줍니다.

### D. 즐겨 쓰는 단축 툴

- `search_name(query: str, limit: int = 10, exchange: str | None = None)`
- `get_quote(symbol: str)`
- `get_income_statement(symbol: str, period: str = "annual", limit: int = 1)`

---

## 사용 예(Inspector에서)

1) **애플 실시간 주가**
   - Tool: `fmp_quote`
   - Params: `{"params":{"symbol":"AAPL"}}`

2) **테슬라 손익계산서 2개(연간)**
   - Tool: `fmp_income_statement`
   - Params: `{"params":{"symbol":"TSLA","period":"annual","limit":2}}`

3) **내 키로 접근 가능한 기능 목록**
   - Tool: `list_fmp_endpoints`
   - Params: `{"run_check": true}`

4) **아무 엔드포인트 호출(범용)**
   - Tool: `fmp_call`
   - Params: `{"endpoint":"key-metrics","service":"stable","params":{"symbol":"AAPL","limit":5}}`

---

## Render.com 배포(요약)

**옵션 1) render.yaml (Blueprint)**  
리포지토리를 Render에 연결하면 자동 감지됨.

**옵션 2) Web Service 수동 설정**
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn server:app --host 0.0.0.0 --port $PORT`
- 환경변수: `FMP_API_KEY=<발급키>`
- 헬스체크: `GET /health` (expect: `OK`)
- MCP 엔드포인트: `https://<서비스도메인>.onrender.com/mcp`

---

## 트러블슛

- **401/403**: API 키 누락/오류 → `.env` 또는 환경변수 확인
- **429/5xx**: 레이트 리미트/일시 오류 → 자동 재시도(지수 백오프) 내장, 호출 간격 늘려 재시도
- **Windows에서 `uv`를 못 찾음**:  
  `C:\Users\<you>\.local\bin`에 `uv.exe`가 있으면 사용자 PATH에 해당 폴더를 추가하고 **새 터미널**을 여세요.
  임시로는 `& "$env:USERPROFILE\.local\bin\uv.exe" --version`로 직접 실행 가능

---

## 라이선스 / 책임

- 이 프로젝트는 예시 코드로 제공됩니다. 실제 운영/과금에 맞는 호출 빈도/데이터 범위는
  사용자의 책임 하에 설정하세요. FMP 계정/과금은 각 사용자가 직접 관리해야 합니다.
