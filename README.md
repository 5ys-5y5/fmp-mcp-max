# fmp-mcp-max (ALL FMP endpoints via MCP)

이 서버는 GPT의 MCP 커넥터에서 **FMP의 모든 REST 엔드포인트**를 호출할 수 있는
제너릭 도구 `fmp.request`를 제공합니다. (GET/POST, 모든 버전 v1/v3/v4 …)

## 0) 준비
- Node 22~24
- (권장) `FMP_API_KEY` 환경변수 설정

## 1) 로컬 실행
```powershell
cd C:\dev\fmp-mcp-max
npm install
$env:FMP_API_KEY="여러분의_FMP_API_KEY"
npm run dev
