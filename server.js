// server.js
// FMP MCP HTTP 서버 (JSON-RPC 2.0, GPT MCP 호환)
// 모든 FMP 엔드포인트를 단일 액션(fmp.request)으로 프록시 호출합니다.

const express = require("express");
const cors = require("cors");
const { randomUUID: _rand } = require("crypto");

// ---- 설정 ----
const PORT = Number(process.env.PORT || 10000);
const APP_API_KEY = process.env.APP_API_KEY || ""; // 서버 보호용(선택)
const FMP_API_KEY = process.env.FMP_API_KEY || ""; // FMP 키(강력 권장)
const FMP_BASE = process.env.FMP_BASE || "https://financialmodelingprep.com"; // 기본 도메인

// ---- 유틸 ----
function makeUUID() {
  try {
    if (typeof _rand === "function") return _rand();
    // 일부 런타임에서 전역 crypto.randomUUID가 있을 수도 있음
    if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
      return globalThis.crypto.randomUUID();
    }
  } catch {}
  // 폴백(충돌 방지)
  return `sid-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function ok(res, result, id = null) {
  res.json({ jsonrpc: "2.0", result, id });
}

function err(res, code, message, id = null) {
  res.status(code === -32601 ? 404 : 400).json({
    jsonrpc: "2.0",
    error: { code, message },
    id,
  });
}

// path 정규화: "v3/quote/AAPL", "/api/v3/quote/AAPL" 모두 허용
function buildFmpUrl(path, params = {}) {
  let p = String(path || "").trim();
  if (!p) throw new Error("path is required");

  // 앞의 / 제거
  if (p.startsWith("/")) p = p.slice(1);

  // /api/ 접두사 보정
  if (!p.startsWith("api/") && (p.startsWith("v") || p.startsWith("version"))) {
    p = `api/${p}`;
  }

  // 최종 URL
  const url = new URL(`${FMP_BASE}/${p}`);

  // 쿼리 병합 (apikey 자동 주입)
  const q = new URLSearchParams(params || {});
  const hasKey =
    q.has("apikey") || q.has("apiKey") || q.has("key") || q.has("token");
  if (!hasKey && FMP_API_KEY) q.set("apikey", FMP_API_KEY);

  for (const [k, v] of q.entries()) url.searchParams.set(k, v);
  return url.toString();
}

// ---- 서버 ----
const app = express();
app.use(cors({ origin: "*", exposedHeaders: ["mcp-session-id"] }));
app.use(express.json({ limit: "1mb" }));

// 간단한 로거 (필요 시 주석 처리)
app.use((req, _res, next) => {
  console.log(`${req.method} ${req.url}`);
  next();
});

// 보호용 API 키(선택). APP_API_KEY가 설정된 경우에만 검사.
function requireApiKey(req, res, next) {
  if (!APP_API_KEY) return next(); // 보호 OFF
  const key =
    req.get("x-api-key") ||
    req.query.key ||
    (req.body && req.body.key) ||
    "";
  if (key && String(key) === String(APP_API_KEY)) return next();
  return res.status(401).json({ error: "Unauthorized (invalid key)" });
}

// 세션 헤더 보장
function getOrCreateSession(req, res) {
  let sid = req.get("mcp-session-id");
  if (!sid) sid = makeUUID();
  res.set("mcp-session-id", sid);
  return sid;
}

// 헬스체크
app.get("/", (_req, res) =>
  res.status(200).send("FMP MCP (HTTP) is running. POST /mcp")
);
app.head("/", (_req, res) => res.status(200).end());
app.get("/health", (_req, res) => res.json({ status: "ok" }));

// CORS 프리플라이트
app.options("/mcp", (_req, res) => {
  res.set("Allow", "POST");
  res.status(200).send("POST");
});

// MCP 엔드포인트
app.all("/mcp", requireApiKey, async (req, res) => {
  const sid = getOrCreateSession(req, res);

  if (req.method !== "POST") {
    // GPT가 GET으로 서버 특성 확인하는 경우 200으로 가볍게 응답
    return res
      .status(200)
      .send(`MCP ready (session=${sid}). Use POST with JSON-RPC 2.0.`);
  }

  const body = req.body || {};
  const { id = null, method, params = {} } = body;

  try {
    switch (method) {
      case "initialize": {
        return ok(res, {
          protocolVersion: "2024-11-01",
          serverInfo: {
            name: "fmp-mcp-max",
            version: "1.0.0",
          },
          capabilities: {
            tools: { listChanged: true },
          },
        }, id);
      }

      case "ping": {
        return ok(res, { now: new Date().toISOString(), session: sid }, id);
      }

      case "tools/list": {
        // 단일 범용 액션: 모든 FMP 엔드포인트를 지원
        return ok(
          res,
          {
            tools: [
              {
                name: "fmp.request",
                description:
                  "Call ANY Financial Modeling Prep endpoint. Example: {\"method\":\"GET\",\"path\":\"v3/quote/AAPL\"}",
                input_schema: {
                  type: "object",
                  properties: {
                    method: {
                      type: "string",
                      enum: ["GET", "POST", "PUT", "PATCH", "DELETE"],
                      default: "GET",
                    },
                    path: { type: "string", description: "e.g. v3/quote/AAPL or api/v3/quote/AAPL" },
                    params: {
                      type: "object",
                      description:
                        "Query/body params. apikey is auto-injected from server unless you override it.",
                      additionalProperties: true,
                    },
                    headers: {
                      type: "object",
                      description: "Optional extra headers to FMP.",
                      additionalProperties: true,
                    },
                    body: {
                      type: ["object", "string", "null"],
                      description:
                        "Raw body for non-GET calls. If object is given, it will be JSON-encoded.",
                      default: null,
                    },
                  },
                  required: ["path"],
                },
              },
            ],
          },
          id
        );
      }

      case "tools/call": {
        const { name, arguments: args = {} } = params;
        if (name !== "fmp.request") {
          return err(res, -32601, `Unknown tool: ${name}`, id);
        }

        const method = String(args.method || "GET").toUpperCase();
        const path = String(args.path || "");
        const q = args.params || {};
        const extraHeaders = args.headers || {};
        const rawBody = args.body ?? null;

        if (!path) return err(res, -32602, "path is required", id);

        const url = buildFmpUrl(path, q);
        const headers = {
          Accept: "application/json",
          ...extraHeaders,
        };

        let fetchBody = undefined;
        if (method !== "GET" && method !== "HEAD") {
          if (rawBody && typeof rawBody === "object") {
            headers["Content-Type"] = "application/json";
            fetchBody = JSON.stringify(rawBody);
          } else if (typeof rawBody === "string") {
            fetchBody = rawBody; // 사용자가 직접 Content-Type 지정 가능
          }
        }

        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 55_000); // 55s 타임아웃
        let status = 0;
        let text = "";
        try {
          const r = await fetch(url, {
            method,
            headers,
            body: fetchBody,
            signal: controller.signal,
          });
          status = r.status;
          text = await r.text();
          clearTimeout(timeout);
        } catch (e) {
          clearTimeout(timeout);
          return err(
            res,
            -32000,
            `FMP request failed: ${e && e.message ? e.message : String(e)}`,
            id
          );
        }

        // JSON 시도 → 실패하면 원문 반환
        let data;
        try {
          data = JSON.parse(text);
        } catch {
          data = text;
        }

        return ok(
          res,
          {
            request: { url, method, sentHeaders: headers },
            response: { status, data },
          },
          id
        );
      }

      default:
        return err(res, -32601, `Unknown method: ${method}`, id);
    }
  } catch (e) {
    return err(
      res,
      -32000,
      `Server error: ${e && e.message ? e.message : String(e)}`,
      id
    );
  }
});

// 서버 시작
const server = app.listen(PORT, "0.0.0.0", () => {
  console.log(`FMP MCP (HTTP) on http://0.0.0.0:${PORT}/mcp`);
});

// 커넥션 안정성(타임아웃 튜닝)
server.keepAliveTimeout = 65_000;
server.headersTimeout = 66_000;
