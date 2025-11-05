import "dotenv/config";
import express from "express";
import { randomUUID } from "node:crypto"; // ⬅ 추가
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { registerAllTools } from "./registerTools.js";
import { registerResources } from "./resources.js";
import { registerAnyGetTool } from "./anyGet.js";
import { FmpClient } from "./fmp.js";
import { requireApiKey, maybeProtectHealth } from "./auth.js";

function requireEnv(name: string) {
  const v = process.env[name];
  if (!v) throw new Error(`Missing ${name}`);
  return v;
}

const server = new McpServer({ name: "fmp-mcp-max", version: "0.1.1" });
const fmp = new FmpClient({ apiKey: requireEnv("FMP_API_KEY") });

registerAllTools(server, fmp);
registerResources(server, fmp);
registerAnyGetTool(server, fmp);

// Health probe
const app = express();
app.use(express.json());

// ✅ 헬스 체크 (옵션 보호)
app.get("/health", maybeProtectHealth(), (_req, res) => res.status(200).send("ok"));

// ✅ MCP HTTP 엔드포인트 (키 필요)
app.post("/mcp", requireApiKey(), async (req, res) => {
  const transport = new StreamableHTTPServerTransport({
    enableJsonResponse: true,
    sessionIdGenerator: () => randomUUID(), // ⬅ 필수 옵션
  });
  res.on("close", () => transport.close());
  await server.connect(transport);
  await transport.handleRequest(req, res, req.body);
});

if (process.env.STDIO === "1") {
  const transport = new StdioServerTransport();
  server.connect(transport).catch((e) => { console.error(e); process.exit(1); });
} else {
  const port = Number(process.env.PORT ?? 3333);
  app.listen(port, () => console.log(`FMP MCP (HTTP) on http://localhost:${port}/mcp`));
}
