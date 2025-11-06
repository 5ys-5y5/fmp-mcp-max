# FMP Universal MCP (User-key Only)

> **핵심 요약**
>
> - **환경변수/서버 키는 전혀 사용하지 않습니다.**
> - **`?apiKey=<YOUR_FMP_KEY>` 또는 헤더 `X-FMP-Api-Key` 로 전달된 키만** 사용하여 FMP에 요청합니다.
> - `PRODUCT_API_KEY` 기반 서버 인증은 **제거**되었습니다.
> - MCP/Connector 시나리오에서 **`Mcp-Session-Id`** 로 세션 단위 키 저장/재사용이 가능합니다.

---

## 1) 구성 개요

- 서버 프레임워크: **Starlette** (MCP `FastMCP.streamable_http_app()` 사용)
- 외부 연동: **Financial Modeling Prep (FMP)** — `https://financialmodelingprep.com`
- HTTP 클라이언트: `httpx`
- 파일: `server.py` (본 저장소의 단일 진입점)

### 키 처리 정책

- 서버/환경변수 `FMP_API_KEY` **미사용** (폴백/강제 검증 제거)
- `PRODUCT_API_KEY`, `REQUIRE_MCP_AUTH`, `ALLOW_QUERY_API_KEY` **실질 폐기**
- 모든 FMP 호출은 **사용자 제공 키**만 사용
  - URL 쿼리: `?apiKey=<YOUR_FMP_KEY>`
  - 헤더: `X-FMP-Api-Key: <YOUR_FMP_KEY>`
  - 세션: `Mcp-Session-Id`(또는 `mcp_session_id` 쿼리)로 **세션 저장 후 재사용**

> 초기 요청에서 `?apiKey=...`만 전달되면 해당 키가 **DEFAULT_FMP_KEY_FROM_URL** 로 임시 저장되어
> 이후 세션 식별자가 없는 요청에도 일시적으로 활용될 수 있습니다.

---

## 2) 설치

```bash
# python 3.10+ 권장
pip install uvicorn httpx python-dotenv starlette mcp
```

> 일부 환경에서는 `pip install mcp` 패키지가 제공되지 않을 수 있습니다. 그런 경우
> MCP 클라이언트/서버 툴킷을 별도로 설치하거나 제공된 `server.py`의 MCP 관련 라인을
> 임시로 주석 처리하여 일반 HTTP 엔드포인트만 사용할 수 있습니다.

---

## 3) 실행

```bash
uvicorn server:app --reload
# 기본 주소: http://127.0.0.1:8000
```

Render 등 PaaS에서는 `PORT` 환경변수가 자동 주입될 수 있으며, 본 코드는
`PORT`가 없으면 **8000** 포트로 구동됩니다.

---

## 4) HTTP 엔드포인트

> 아래 엔드포인트들은 **로컬 테스트**용으로 추가되어 있습니다. (MCP 툴 호출을 감싸는 얇은 래퍼)

### 4.1 회사 프로필
```
GET /fmp/profile/{symbol}
```

예시:
```bash
curl "http://127.0.0.1:8000/fmp/profile/AAPL?apiKey=YOUR_FMP_KEY"
# 또는
curl -H "X-FMP-Api-Key: YOUR_FMP_KEY" "http://127.0.0.1:8000/fmp/profile/AAPL"
```

### 4.2 실시간 시세
```
GET /fmp/quote/{symbol}
```

예시:
```bash
curl "http://127.0.0.1:8000/fmp/quote/AAPL?apiKey=YOUR_FMP_KEY"
# 또는
curl -H "X-FMP-Api-Key: YOUR_FMP_KEY" "http://127.0.0.1:8000/fmp/quote/AAPL"
```

### 4.3 임의 경로 프록시 (주의)
```
GET /fmp/call?path=/api/v3/profile/AAPL&apiKey=YOUR_FMP_KEY
```

> **보안 주의**: 운영환경에서는 `/fmp/call`의 허용 경로 화이트리스트/레이트리밋을 꼭 구성하세요.

### 4.4 헬스체크
```
GET /health
```
- 키가 없는 경우: 외부 연동 테스트는 건너뛰고 단순 응답
- 키가 있는 경우: 가벼운 FMP 엔드포인트를 실제로 호출하여 연결성 확인

### 4.5 루트/웰노운
- `GET /` : 인덱스 정보
- `GET /.well-known/openid-configuration` : OAuth/OIDC 미지원 안내(의도적 404)
- `GET /.well-known/oauth-authorization-server` : OAuth/OIDC 미지원 안내(의도적 404)

---

## 5) MCP 도구(툴)

Starlette 애플리케이션은 `FastMCP.streamable_http_app()`로 구성되어 **/mcp** SSE 엔드포인트를 제공합니다.
다음 MCP 툴들이 공개되어 있습니다.

- **핵심**: `fmp_call(endpoint, service, params, ...)`
  - 모든 FMP 호출을 포괄하는 범용 호출기
  - 사용자 키가 없으면 아래와 같은 `_error` 구조로 응답
- **카탈로그 기반 동적 툴**: `fmp_search_name`, `fmp_quote`, `fmp_income_statement` 등 다수
- **유틸**:
  - `ping()` : 세션/키 보유 여부 확인
  - `set_fmp_api_key(api_key)` / `clear_fmp_api_key()` : 세션에 키 등록/해제
  - `list_fmp_endpoints(run_check=True)` : 카탈로그 + 접근성 체크
  - `test_endpoint_access(service, endpoint, params)` : 특정 엔드포인트 샘플 호출

### `_error` 응답 포맷 (예)

```json
{
  "_error": {
    "code": "MISSING_API_KEY",
    "needs_user_confirmation": false,
    "suggest_web_search": true,
    "message": "MCP URL에 ?apiKey=... 로 FMP 키를 전달해야 합니다...",
    "explain_to_user": "MCP 서버 등록 시 URL 끝에 ?apiKey=<YOUR_FMP_KEY>를 포함해 주세요."
  }
}
```

업스트림 에러(401/402/403/429/5xx 등)는 `_error.code/status/plan_hint/suggested_action` 등으로
분류되어 반환됩니다.

---

## 6) 세션과 키 저장 규칙

- 요청에 **`Mcp-Session-Id`** 헤더(또는 쿼리 `mcp_session_id`)가 있으면 해당 값을 세션 ID로 사용합니다.
- `X-FMP-Api-Key` 헤더나 `?apiKey` 파라미터가 포함되면 **해당 세션에 키가 저장**됩니다.
- 이후 같은 세션 ID로 요청하면 **키를 생략**할 수 있습니다.

예시 (PowerShell):
```powershell
# 1) 최초 요청: 세션 + apiKey
curl -H "Mcp-Session-Id: local-test-session" "http://127.0.0.1:8000/fmp/profile/AAPL?apiKey=YOUR_FMP_KEY"

# 2) 이후 요청: 같은 세션, 키 생략
curl -H "Mcp-Session-Id: local-test-session" "http://127.0.0.1:8000/fmp/quote/AAPL"
```

---

## 7) 자주 하는 질문(FAQ) & 트러블슈팅

### Q1) `404 Not Found`가 떠요.
- **원인1**: 서버가 구버전 코드입니다. `server.py`에 다음 라우트 3개가 **반드시 포함**되어야 합니다.
  - `app.add_route("/fmp/profile/{symbol}", ...)`
  - `app.add_route("/fmp/quote/{symbol}", ...)`
  - `app.add_route("/fmp/call", ...)`
- **원인2**: 오탈자/경로 오류. 예: `/fmp/quote/AAPL` 처럼 **심볼**을 path param으로 전달해야 합니다.

### Q2) `_error: MISSING_API_KEY`가 떠요.
- URL에 `?apiKey=...` 또는 헤더 `X-FMP-Api-Key: ...`를 포함했는지 확인하세요.
- MCP 사용 중이면 `set_fmp_api_key()`로 세션에 등록할 수 있습니다.

### Q3) 401/402/403/429/5xx 등 업스트림 에러가 떠요.
- 응답의 `_error` 필드를 확인하세요. `plan_hint`, `suggested_action`에 대응 방법이 안내됩니다.

### Q4) Render 배포 시 설정은?
- **FMP_API_KEY/PRODUCT_API_KEY**는 필요하지 않습니다(사용하지 않음).
- 필요 시 `CORS_ALLOW_ORIGINS`만 환경변수로 지정하세요.
- 포트는 `PORT` 환경변수를 따르며, 없는 경우 8000을 사용합니다.

---

## 8) 보안 주의사항

- 공개 배포 시 `/fmp/call`은 **화이트리스트/레이트리밋**을 반드시 적용하세요.
- API Key는 로그에 남기지 마세요(리버스 프록시/모니터링 도구 포함).
- **HTTPS**(TLS) 환경에서만 사용하세요.

---

## 9) 라이선스

내부 사용 또는 프로젝트 정책에 따릅니다.
