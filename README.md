# FMP MCP (HTTP)

단일 액션 **`fmp.request`** 로 Financial Modeling Prep의 **모든 엔드포인트**를 호출할 수 있는 MCP 서버.

## 환경변수

- `FMP_API_KEY` (권장): FMP의 apikey. 서버가 자동으로 쿼리에 `apikey=`를 붙여줍니다.
- `APP_API_KEY` (선택): 서버 보호용 키. 설정 시 반드시 `?key=...` 또는 `x-api-key: ...` 로 전달해야 함.
- `PORT` (선택): 기본 10000

## 로컬 실행

```bash
npm ci
npm run dev
# 새 터미널에서
curl -i http://127.0.0.1:10000/health
