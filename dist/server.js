import "dotenv/config";
import express from "express";
import { randomUUID } from "node:crypto";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { registerAllTools } from "./registerTools.js";
import { registerResources } from "./resources.js";
import { registerAnyGetTool } from "./anyGet.js";
import { FmpClient } from "./fmp.js";
import { requireApiKey, maybeProtectHealth } from "./auth.js";
function requireEnv(name) {
    const v = process.env[name];
    if (!v)
        throw new Error(`Missing ${name}`);
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
// (선택) 브라우저 클라이언트용 CORS 헤더
app.use((_req, res, next) => {
    res.setHeader("Access-Control-Expose-Headers", "mcp-session-id");
    res.setHeader("Access-Control-Allow-Headers", "content-type, mcp-session-id, x-api-key, authorization");
    next();
});
// 헬스 체크 (환경변수로 보호 가능)
app.get("/health", maybeProtectHealth(), (_req, res) => {
    res.status(200).send("ok");
});
// === 세션별 transport 재사용 ===
const transports = new Map();
app.post("/mcp", requireApiKey(), async (req, res) => {
    // 요청 헤더에서 세션ID 추출(Express는 소문자 키)
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
        // 생성 직후 sessionId가 할당되는 구현 대비: 즉시 저장 시도
        const sid0 = transport.sessionId;
        if (sid0) {
            transports.set(sid0, transport);
            // console.log("[MCP] session pre-registered:", sid0);
        }
    }
    try {
        // 실제 처리
        await transport.handleRequest(req, res, req.body);
        // 처리 후에도 sessionId 저장(초기화 응답 직후를 대비)
        const sid1 = transport.sessionId;
        if (sid1 && !transports.has(sid1)) {
            transports.set(sid1, transport);
            // console.log("[MCP] session registered:", sid1);
        }
        // 혹시 응답 헤더에 기록된 경우도 수용(이중 안전장치)
        const sidHeader = res.getHeader("mcp-session-id");
        const sid2 = typeof sidHeader === "string" ? sidHeader : undefined;
        if (sid2 && !transports.has(sid2)) {
            transports.set(sid2, transport);
            // console.log("[MCP] session registered from header:", sid2);
        }
    }
    catch (e) {
        if (!res.headersSent) {
            res.status(500).json({
                jsonrpc: "2.0",
                error: { code: -32603, message: "Internal server error" },
                id: null,
            });
        }
    }
});
// STDIO 모드(로컬 전용)
if (process.env.STDIO === "1") {
    const transport = new StdioServerTransport();
    server.connect(transport).catch((e) => {
        console.error(e);
        process.exit(1);
    });
}
else {
    const port = Number(process.env.PORT ?? 3333);
    app.listen(port, () => console.log(`FMP MCP (HTTP) on http://localhost:${port}/mcp`));
}
