// server.js — Minimal-but-complete MCP over HTTP for ALL FMP endpoints
// - JSON-RPC 2.0: initialize, tools/list, tools/call
// - Tool: fmp.request (method, path, query, body)
// - Forwards ANY /api/* path to https://financialmodelingprep.com (v1/v3/v4...)
// - Appends ?apikey=<FMP_API_KEY>
// - CORS/health/GET-405 handling

const http = require("http");
const crypto = require("crypto");
const express = require("express");
const cors = require("cors");

// ====== Config ======
const HOST = process.env.HOST || "0.0.0.0";
const PORT = Number(process.env.PORT || 10000);
const CONNECTOR_KEY = process.env.CONNECTOR_KEY || ""; // ?key=... 에서 검사
const FMP_BASE = process.env.FMP_BASE || "https://financialmodelingprep.com";
const FMP_API_KEY = process.env.FMP_API_KEY || "demo"; // 반드시 본인 키로 설정 추천

// ====== App base ======
const app = express();
app.disable("x-powered-by");
app.set("trust proxy", true);
app.use(cors({
  origin: "*",
  exposedHeaders: ["mcp-session-id"]
}));
app.use(express.json({ limit: "1mb" }));

// 간단한 로그
app.use((req, res, next) => {
  const t0 = Date.now();
  res.on("finish", () => {
    console.log(`${req.method} ${req.originalUrl} ${res.statusCode} ${Date.now()-t0}ms`);
  });
  next();
});

// ====== Helpers ======
const randomId = () => (crypto.randomUUID ? crypto.randomUUID() : (Date.now()+"-"+Math.random().toString(36).slice(2)));
const jsonOk = (res, body) => res.status(200).type("application/json; charset=utf-8").send(JSON.stringify(body));
const jsonErr = (res, code, message, id=null) =>
  res.status(200).type("application/json; charset=utf-8").send(JSON.stringify({
    jsonrpc: "2.0",
    error: { code, message },
    id
  }));

function requireKey(req, res, next) {
  if (!CONNECTOR_KEY) return next(); // 키를 안쓸 수도 있게(테스트용)
  if (req.query.key === CONNECTOR_KEY) return next();
  return res.status(401).json({ error: "Unauthorized: bad or missing ?key" });
}

function ensurePost(req, res, next) {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).send("POST only");
  }
  next();
}

// 헤더로 세션ID 주고받기(선택적)
function withSession(req, res, next) {
  let sid = req.get("mcp-session-id");
  if (!sid) sid = randomId();
  res.setHeader("mcp-session-id", sid);
  req.mcpSessionId = sid;
  next();
}

// ====== Health & root ======
app.get("/health", (req, res) => {
  res.json({ status: "ok", time: new Date().toISOString() });
});
app.get("/", (req, res) => res.status(200).send("FMP MCP is running. POST /mcp"));
app.head("/", (req, res) => res.status(200).end());

// ====== MCP endpoint ======
app.all("/mcp", requireKey, withSession, ensurePost, async (req, res) => {
  // JSON-RPC 2.0 dispatcher
  const rpc = req.body;
  const id = rpc && ("id" in rpc) ? rpc.id : null;

  if (!rpc || rpc.jsonrpc !== "2.0" || !rpc.method) {
    return jsonErr(res, -32000, "Bad Request: invalid JSON-RPC 2.0 payload", id);
  }

  try {
    switch (rpc.method) {
      case "initialize": {
        // MCP initialize result (shape 중요)
        return jsonOk(res, {
          jsonrpc: "2.0",
          id,
          result: {
            protocolVersion: "2023-10-01",
            serverInfo: { name: "fmp-mcp-max", version: process.env.BUILD || "dev" },
            capabilities: {
              tools: { listChanged: true }
            }
          }
        });
      }

      case "tools/list": {
        const tool = {
          name: "fmp.request",
          description: "Call ANY FinancialModelingPrep API (pass HTTP method/path/query/body).",
          inputSchema: {
            type: "object",
            properties: {
              method: {
                type: "string",
                description: "HTTP method: GET, POST, PUT, DELETE, PATCH",
                enum: ["GET","POST","PUT","DELETE","PATCH"]
              },
              path: {
                type: "string",
                description: "FMP API path starting with /api/..., e.g. /api/v3/profile/AAPL"
              },
              query: {
                type: "object",
                description: "Optional query object (will be merged with apikey)",
                additionalProperties: true
              },
              body: {
                description: "Optional JSON body for POST/PUT/PATCH",
                anyOf: [{ type: "object" }, { type: "array" }, { type: "null" }]
              }
            },
            required: ["method","path"]
          }
        };

        return jsonOk(res, {
          jsonrpc: "2.0",
          id,
          result: { tools: [tool] }
        });
      }

      case "tools/call": {
        const params = rpc.params || {};
        const name = params.name;
        const args = params.arguments || {};

        if (name !== "fmp.request") {
          return jsonErr(res, -32601, `Unknown tool: ${name}`, id);
        }

        // Validate args
        const method = String(args.method || "GET").toUpperCase();
        const path = String(args.path || "");
        if (!path.startsWith("/api/")) {
          return jsonErr(res, -32000, "path must start with /api/", id);
        }

        const q = args.query && typeof args.query === "object" ? { ...args.query } : {};
        // ensure apikey
        if (!q.apikey) q.apikey = FMP_API_KEY;

        // Build URL
        const url = new URL(path, FMP_BASE);
        Object.entries(q).forEach(([k, v]) => url.searchParams.set(k, String(v)));

        // Prepare fetch
        const headers = { "accept": "application/json" };
        let body = undefined;
        if (["POST","PUT","PATCH"].includes(method)) {
          headers["content-type"] = "application/json";
          body = (args.body == null) ? undefined : JSON.stringify(args.body);
        }

        // Call FMP
        let resp;
        try {
          resp = await fetch(url, { method, headers, body, redirect: "follow" });
        } catch (e) {
          return jsonErr(res, -32098, `Network error: ${e.message}`, id);
        }

        const text = await resp.text();
        let data = text;
        try { data = JSON.parse(text); } catch (_) { /* keep as text */ }

        // Return MCP tool result
        return jsonOk(res, {
          jsonrpc: "2.0",
          id,
          result: {
            content: [
              {
                type: "json",
                mimeType: "application/json",
                text: JSON.stringify({
                  request: { method, url: url.toString() },
                  status: resp.status,
                  ok: resp.ok,
                  data
                })
              }
            ],
            isError: !resp.ok
          }
        });
      }

      default:
        return jsonErr(res, -32601, `Method not found: ${rpc.method}`, id);
    }
  } catch (e) {
    console.error("Unhandled server error:", e);
    return jsonErr(res, -32603, "Internal error", id);
  }
});

// GET /mcp → 405
app.get("/mcp", requireKey, (req, res) => {
  res.setHeader("Allow", "POST");
  res.status(405).send("POST only");
});

// ====== Start ======
const server = http.createServer(app);
server.listen(PORT, HOST, () => {
  console.log(`FMP MCP (HTTP) on http://${HOST}:${PORT}/mcp`);
});

// graceful shutdown
process.on("SIGINT", () => { server.close(() => process.exit(0)); });
process.on("SIGTERM", () => { server.close(() => process.exit(0)); });
