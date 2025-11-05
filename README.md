# FMP MCP Server (Max Version)

이 저장소는 Financial Modeling Prep(FMP) API를 넓게 감싼 **MCP 서버**입니다.
HTTP/STDIO 트랜스포트, 캐시/레이트리밋, 동적 리소스까지 포함되어 **바로 실행**할 수 있습니다.

---

## 빠른 시작
1) Node.js 20+ 설치 → `node -v` 확인  
2) `.env.example`를 복사해 `.env`로 만들고 `FMP_API_KEY=` 값을 채우기  
3) 설치: `npm i`  
4) 실행(HTTP): `npm run dev` → `http://localhost:3333/health` 가 `ok`면 정상  
5) 스모크 테스트: `npm run smoke` (AAPL 검색/시세 확인)

---

## 범용 프록시 도구 (fmp_any_get)
- 도구 이름: `fmp_any_get`
- 입력 예:
```json
{ "path": "/stable/quote", "params": { "symbol": "AAPL" }, "ttl": 30 }
```
- `/stable`, `/api/v3`, `/api/v4` GET 엔드포인트를 호출할 수 있습니다.
