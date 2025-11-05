import "dotenv/config";
import express, { Request, Response, NextFunction } from "express";
import { randomUUID } from "node:crypto";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { registerAllTools } from "./registerTools.js";
import { registerResources } from "./resources.js";
import { registerAnyGetTool } from "./anyGet.js";
import { FmpClient } from "./fmp.js";
import { requireApiKey, maybeProtectHealth } from "./auth.js";

function requireEnv(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing ${name}`);
  return v;
}

const server = new McpServer({ name: "fmp-mcp-max", version: "0.1.1" });
const fmp = new FmpClient({ apiKey: requireEnv("FMP_API_KEY") });

// 도구/리소스 등록
registerAllTools(server, fmp);
registerResources(server, fmp);
registerAnyGetTool(server, fmp);

const app = express();
app.use(express.json());

// (선택) 브라우저 클라이언트용 CORS 헤더 설정
app.use((_req: Request, res: Response, next: NextFunction) => {
  res.setHeader("Access-Control-Expose-Headers", "mcp-session-id");
  res.setHeader(
    "Access-Control-Allow-Headers",
    "content-type, mcp-session-id, x-api-key, authorization"
  );
  next();
});

// 헬스 체크 (환경변수로 보호 가능)
app.get("/health", maybeProtectHealth(), (_req: Request, res: Response) => {
  res.status(200).send("ok");
});

// === 세션별 transport 재사용 ===
const transports = new Map<string, StreamableHTTPServerTransport>();

app.post("/mcp", requireApiKey(), async (req: Request, res: Response) => {
  // 요청 헤더에서 세션ID 추출(Express는 헤더 키를 소문자로 보관)
  const hdr = req.headers["mcp-session-id"];
  const incomingSessionId = typeof hdr === "string" ? hdr : undefined;

  // 기존 세션이 있으면 transport 재사용
  let transport = incomingSessionId ? transports.get(incomingSessionId) : undefined;

  // 기존 세션이 없고 initialize가 아니면 거절
  if (!transport && req.body?.method !== "initialize") {
    res.status(400).json({
      jsonrpc: "2.0",
      error: { code: -32000, message: "Bad Request: Server not initialized" },
      id: null,
    });
    return;
  }

  // initialize 요청이면 새 transport 생성 + 서버 연결
  if (!transport) {
    transport = new StreamableHTTPServerTransport({
      enableJsonResponse: true,
      sessionIdGenerator: () => randomUUID(),
    });
    await server.connect(transport);
  }

  try {
    // 실제 처리
    await transport.handleRequest(req, res, req.body);

    // initialize 응답 시 응답 헤더로 내려간 session id를 테이블에 저장
    const sidHeader = res.getHeader("mcp-session-id");
    const newSessionId = typeof sidHeader === "string" ? sidHeader : undefined;
    if (newSessionId && !transports.has(newSessionId)) {
      transports.set(newSessionId, transport);
      // 필요하면 로깅:
      // console.log("[MCP] session created:", newSessionId);
    }
  } catch (e) {
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: "2.0",
        error: { code: -32603, message: "Internal server error" },
        id: null,
      });
    }
  }
});

// STDIO 모드 지원(로컬 전용)
if (process.env.STDIO === "1") {
  const transport = new StdioServerTransport();
  server.connect(transport).catch((e) => {
    console.error(e);
    process.exit(1);
  });
} else {
  const port = Number(process.env.PORT ?? 3333);
  app.listen(port, () =>
    console.log(`FMP MCP (HTTP) on http://localhost:${port}/mcp`)
  );
}
