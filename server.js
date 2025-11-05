// server.js
// FMP(https://financialmodelingprep.com) 모든 엔드포인트를 호출할 수 있는
// 제너릭 MCP-over-HTTP(JSON-RPC) 서버
//
// - /mcp : JSON-RPC 2.0
// - tools:
//     * fmp.request  -> 모든 FMP 엔드포인트 지원 (GET/POST, 쿼리파라미터, 바디)
//     * fmp.get      -> GET 전용 편의 래퍼
//     * fmp.batch    -> 여러 요청을 한 번에
//
// 배포 전 환경변수 설정 권장:
//   FMP_API_KEY        : FMP API 키 (권장, 있으면 자동으로 쿼리에 붙여줌)
//   APP_API_KEY        : (선택) 서버 보호용 키. 없으면 공개 엔드포인트
//   APP_PROTECT_HEALTH : "1"이면 /health도 보호
//
// Render 설정:
//   Build Command  : npm ci
//   Start Command  : node server.js
//   Health Check   : /health

const express = require("express");
const cors = require("cors");
const morgan = require("morgan");
const { randomUUID } = require("uuid");
const http = require("http");

// -------------------- Config --------------------
const PORT = Number(process.env.PORT || 3000);

// 보호용 키(?key= 또는 x-api-key 헤더)
const APP_API_KEY = (process.env.APP_API_KEY || "").trim();
const APP_PROTECT_HEALTH = (process.env.APP_PROTECT_HEALTH || "0").trim() === "1";

// FMP API
const FMP_API_KEY = (process.env.FMP_API_KEY || "").trim();
const FMP_BASE = "https://financialmodelingprep.com/api"; // /v1, /v3, /v4 등 모두 지원

// 타임아웃(밀리초)
const REQUEST_TIMEOUT_MS = Number(process.env.REQUEST_TIMEOUT_MS || 25000);

// -------------------- App --------------------
const app = express();
app.set("trust proxy", true);
app.use(express.json({ limit: "2mb" }));
app.use(
  cors({
    origin: "*",
    exposedHeaders: ["mcp-session-id"]
  })
);
app.use(morgan("tiny"));

// -------------------- Helpers --------------------
function getApiKeyFromReq(req) {
  const hdrKey = req.get("x-api-key");
  if (hdrKey) return hdrKey.trim();

  const auth = req.get("authorization");
  if (auth && /^bearer\s+/i.test(auth)) {
    return auth.replace(/^bearer\s+/i, "").trim();
  }

  if (req.query && typeof req.query.key === "string") {
    return req.query.key.trim();
  }
  return "";
}

function requireApiKey(req, res, next) {
  if (!APP_API_KEY) return next(); // 잠금 안 함
  const provided = getApiKeyFromReq(req);
  if (!provided || provided !== APP_API_KEY) {
    return res
      .status(401)
      .json({ error: "unauthorized", hint: "provide x-api-key header or ?key=..." });
  }
  next();
}

const sessions = new Map(); // sessionId -> { initialized: boolean, createdAt: number }
function getOrCreateSession(req, res) {
  let sid = req.get("mcp-session-id");
  if (!sid) sid = randomUUID();
  if (!sessions.has(sid)) sessions.set(sid, { initialized: false, createdAt: Date.now() });
  res.set("mcp-session-id", sid);
  return { sid, state: sessions.get(sid) };
}

function rpcResult(id, result) {
  return { jsonrpc: "2.0", id, result };
}
function rpcError(id, code, message, data) {
  const err = { jsonrpc: "2.0", id, error: { code, message } };
  if (data !== undefined) err.error.data = data;
  return err;
}

// -------------------- FMP utils --------------------
function normalizePath(p) {
  // 입력 예:
  //  "v3/quote/AAPL"   -> "/v3/quote/AAPL"
  //  "/v4/something"   -> 그대로
  //  "quote/AAPL"      -> 기본 "/v3/quote/AAPL"
  let path = String(p || "").trim();
  if (!path) throw new Error("path is required");
  if (!path.startsWith("/")) path = "/" + path;
  if (!/^\/v\d+\//.test(path)) path = "/v3" + (path === "/" ? "" : path);
  return path;
}

function toQueryString(obj) {
  const qs = new URLSearchParams();
  if (obj && typeof obj === "object") {
    for (const [k, v] of Object.entries(obj)) {
      if (v === undefined || v === null) continue;
      qs.append(k, String(v));
    }
  }
  return qs.toString();
}

function buildUrl({ path, params }) {
  const vpath = normalizePath(path);
  const qp = { ...(params || {}) };

  // apikey가 명시되지 않았다면 서버의 FMP_API_KEY 자동 추가
  const hasApiKey = Object.keys(qp).some((k) => k.toLowerCase() === "apikey");
  if (!hasApiKey && FMP_API_KEY) qp.apikey = FMP_API_KEY;

  const qs = toQueryString(qp);
  return `${FMP_BASE}${vpath}${qs ? "?" + qs : ""}`;
}

async function fetchWithTimeout(url, opts = {}, timeoutMs = REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...opts, signal: controller.signal });
    return res;
  } finally {
    clearTimeout(id);
  }
}

async function doFmpRequest({ method = "GET", path, params, body, headers, timeoutMs }) {
  const url = buildUrl({ path, params });
  const m = String(method || "GET").toUpperCase();

  const res = await fetchWithTimeout(
    url,
    {
      method: m,
      headers: {
        "Content-Type": "application/json",
        ...(headers || {})
      },
      body: m === "GET" || m === "HEAD" ? undefined : body ? JSON.stringify(body) : undefined
    },
    timeoutMs ? Number(timeoutMs) : REQUEST_TIMEOUT_MS
  );

  const ctype = (res.headers.get("content-type") || "").toLowerCase();
  let data;
  if (ctype.includes("application/json")) {
    data = await res.json();
  } else {
    data = await res.text();
  }

  if (!res.ok) {
    const msg = typeof data === "string" ? data : JSON.stringify(data);
    throw new Error(`FMP HTTP ${res.status}: ${msg}`);
  }

  return data;
}

// -------------------- MCP server meta --------------------
const SERVER_INFO = { name: "fmp-mcp-max", version: "3.0.0" };
const MCP_CAPABILITIES = { tools: {} };

// 유저가 보기 쉬운 기본 도구들
const TOOLS = [
  {
    name: "fmp.request",
    description:
      "Call ANY FMP endpoint (all versions). Example path: 'v3/quote/AAPL' or 'v4/financial-growth/AAPL'. Supports GET/POST.",
    inputSchema: {
      type: "object",
      properties: {
        method: { type: "string", enum: ["GET", "POST"], default: "GET" },
        path: { type: "string", description: "FMP path. Accepts 'v3/...', '/v3/...', 'quote/AAPL' (auto /v3)" },
        params: { type: "object", description: "Query params (apikey auto-added if missing)" },
        body: { type: "object", description: "JSON body for POST if needed" },
        headers: { type: "object", description: "Optional extra headers" },
        timeoutMs: { type: "number", description: "Request timeout ms (default 25000)" }
      },
      required: ["path"]
    }
  },
  {
    name: "fmp.get",
    description: "Convenience GET wrapper. Example: path='quote/AAPL' or 'v4/profile/AAPL', params={}.",
    inputSchema: {
      type: "object",
      properties: {
        path: { type: "string" },
        params: { type: "object" },
        timeoutMs: { type: "number" }
      },
      required: ["path"]
    }
  },
  {
    name: "fmp.batch",
    description:
      "Batch multiple FMP requests at once. Input: { requests: [ {method?, path, params?, body?, headers?, timeoutMs?}, ... ] }",
    inputSchema: {
      type: "object",
      properties: {
        requests: {
          type: "array",
          items: {
            type: "object",
            properties: {
              method: { type: "string", enum: ["GET", "POST"] },
              path: { type: "string" },
              params: { type: "object" },
              body: { type: "object" },
              headers: { type: "object" },
              timeoutMs: { type: "number" }
            },
            required: ["path"]
          }
        }
      },
      required: ["requests"]
    }
  }
];

// -------------------- Routes --------------------

// 건강 체크
app.get(
  "/health",
  APP_PROTECT_HEALTH ? requireApiKey : (req, res, next) => next(),
  (req, res) => {
    res.json({ status: "ok", fmpKey: FMP_API_KEY ? "set" : "missing" });
  }
);

// 사전 점검(OPTIONS)
app.options("/mcp", requireApiKey, (req, res) => {
  res.set("Allow", "POST");
  res.status(200).send("POST");
});

// MCP 본체
app.post("/mcp", requireApiKey, async (req, res) => {
  const { state } = getOrCreateSession(req, res);

  if (!req.is("application/json")) {
    return res
      .status(415)
      .json({ jsonrpc: "2.0", error: { code: -32600, message: "Invalid Request: JSON only" }, id: null });
  }

  const body = req.body;
  const isBatch = Array.isArray(body);
  const messages = isBatch ? body : [body];
  const replies = [];

  for (const msg of messages) {
    const hasId = Object.prototype.hasOwnProperty.call(msg || {}, "id");
    const id = hasId ? msg.id : null;

    if (!msg || msg.jsonrpc !== "2.0" || typeof msg.method !== "string") {
      if (hasId) replies.push(rpcError(id, -32600, "Invalid Request"));
      continue;
    }

    try {
      switch (msg.method) {
        case "initialize": {
          state.initialized = true;
          replies.push(
            rpcResult(id, {
              protocolVersion: "2025-01-01",
              capabilities: MCP_CAPABILITIES,
              serverInfo: SERVER_INFO
            })
          );
          break;
        }

        case "tools/list": {
          if (!state.initialized) {
            replies.push(rpcError(id, -32000, "Server not initialized"));
            break;
          }
          replies.push(rpcResult(id, { tools: TOOLS }));
          break;
        }

        case "tools/call": {
          if (!state.initialized) {
            replies.push(rpcError(id, -32000, "Server not initialized"));
            break;
          }
          const { name, arguments: args } = msg.params || {};
          try {
            let data;

            if (name === "fmp.request") {
              const { method = "GET", path, params, body, headers, timeoutMs } = args || {};
              data = await doFmpRequest({ method, path, params, body, headers, timeoutMs });
            } else if (name === "fmp.get") {
              const { path, params, timeoutMs } = args || {};
              data = await doFmpRequest({ method: "GET", path, params, timeoutMs });
            } else if (name === "fmp.batch") {
              const { requests } = args || {};
              if (!Array.isArray(requests) || requests.length === 0) throw new Error("requests is empty");
              const results = [];
              for (const r of requests) {
                try {
                  const d = await doFmpRequest({
                    method: r.method || "GET",
                    path: r.path,
                    params: r.params,
                    body: r.body,
                    headers: r.headers,
                    timeoutMs: r.timeoutMs
                  });
                  results.push({ ok: true, data: d });
                } catch (e) {
                  results.push({ ok: false, error: String(e && e.message || e) });
                }
              }
              data = results;
            } else {
              replies.push(rpcError(id, -32601, `Tool not found: ${name}`));
              break;
            }

            replies.push(
              rpcResult(id, {
                content: [{ type: "json", json: data }]
              })
            );
          } catch (toolErr) {
            replies.push(
              rpcError(id, -32002, "Tool execution failed", { message: String(toolErr && toolErr.message || toolErr) })
            );
          }
          break;
        }

        // 리소스 기능 미사용
        case "resources/list":
          if (!state.initialized) {
            replies.push(rpcError(id, -32000, "Server not initialized"));
            break;
          }
          replies.push(rpcResult(id, { resources: [] }));
          break;

        case "resources/read":
          if (!state.initialized) {
            replies.push(rpcError(id, -32000, "Server not initialized"));
            break;
          }
          replies.push(rpcError(id, -32601, "No resources available"));
          break;

        default:
          if (hasId) replies.push(rpcError(id, -32601, `Method not found: ${msg.method}`));
      }
    } catch (e) {
      if (hasId) replies.push(rpcError(id, -32603, "Internal error", { message: String(e && e.message || e) }));
    }
  }

  if (replies.length === 0) return res.status(204).end();
  if (isBatch) return res.json(replies);
  return res.json(replies[0]);
});

// 루트
app.get("/", (req, res) => {
  res.type("text/plain").send("MCP FMP server running. Use POST /mcp");
});

// -------------------- Start --------------------
const server = http.createServer(app);
server.keepAliveTimeout = 70_000;
server.headersTimeout = 75_000;
server.requestTimeout = 60_000;

server.listen(PORT, () => {
  console.log(`[MCP] Server listening on port ${PORT}`);
});
