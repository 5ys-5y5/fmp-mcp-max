// server.js
// Minimal MCP-like HTTP endpoint with health, strict methods, CORS, and streaming JSON chunks.

import express from "express";
import cors from "cors";
import crypto from "node:crypto";

const BUILD_TAG = "mcp-max-2025-11-05-01";

const app = express();

// Trust proxy (Render 앞단 프록시용)
app.set("trust proxy", true);

// 보안/기본 설정
app.disable("x-powered-by");

// JSON 파서 (POST 본문 파싱이 필요하면 사용. 스트리밍은 res.write 로 처리)
app.use(express.json({ limit: "256kb" }));

// CORS (필요 시 도메인 제한)
app.use(
  cors({
    origin: true,
    credentials: false,
    exposedHeaders: ["mcp-session-id"],
    allowedHeaders: ["content-type", "mcp-session-id", "x-api-key", "authorization"],
    methods: ["POST", "OPTIONS"],
  })
);

// --- 유틸: API Key 확인 ---
function getAllowedKeys() {
  const raw = process.env.APP_API_KEYS || process.env.APP_API_KEY || "";
  return raw
    .split(",")
    .map(s => s.trim())
    .filter(Boolean);
}

function extractProvidedKey(req) {
  const q = req.query?.key;
  if (typeof q === "string" && q) return q;

  const header = req.get("x-api-key");
  if (header) return header;

  const auth = req.get("authorization");
  if (auth && auth.toLowerCase().startsWith("bearer ")) {
    return auth.slice(7).trim();
  }
  return "";
}

function checkAuth(req, res) {
  const allowed = getAllowedKeys();
  if (allowed.length === 0) return true; // 키 미설정 시 개방(개발 편의)
  const provided = extractProvidedKey(req);
  if (!provided) return false;
  return allowed.includes(provided);
}

// --- 헬스체크 ---
app.get("/health", (_req, res) => {
  res.set("Access-Control-Expose-Headers", "mcp-session-id");
  res.status(200).json({ status: "ok", build: BUILD_TAG });
});

// --- /mcp 메서드 제한: GET 은 405 ---
app.get("/mcp", (_req, res) => {
  res.set("Allow", "POST, OPTIONS");
  res.status(405).send("Method Not Allowed");
});

// --- /mcp CORS 프리플라이트 ---
app.options("/mcp", (_req, res) => {
  res.set("Allow", "POST, OPTIONS");
  // cors 미들웨어가 Access-Control-* 헤더 채움
  res.status(204).end();
});

// --- /mcp POST: 스트리밍 응답 ---
app.post("/mcp", async (req, res) => {
  if (!checkAuth(req, res)) {
    return res.status(401).json({ error: "Unauthorized" });
  }

  // 스트리밍 헤더
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Transfer-Encoding", "chunked");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Access-Control-Expose-Headers", "mcp-session-id");

  // 세션 아이디 헤더
  const sessionId = crypto.randomUUID();
  res.setHeader("mcp-session-id", sessionId);

  // 첫 청크: 서버 정보 (클라이언트가 빈 {} 보내도 200 보장)
  const hello = {
    jsonrpc: "2.0",
    id: null,
    result: {
      server: "fmp-mcp-max",
      build: BUILD_TAG,
      sessionId,
      message: "connected",
    },
  };
  res.write(JSON.stringify(hello) + "\n");

  // 주기적 ping (테스트 편의를 위해 2회 전송 후 종료)
  let count = 0;
  const timer = setInterval(() => {
    count += 1;
    const frame = {
      jsonrpc: "2.0",
      method: "mcp/ping",
      params: { t: Date.now(), count },
    };
    try {
      res.write(JSON.stringify(frame) + "\n");
    } catch {
      clearInterval(timer);
    }
    if (count >= 2) {
      clearInterval(timer);
      // 마지막 청크
      const bye = {
        jsonrpc: "2.0",
        method: "mcp/bye",
        params: { reason: "demo-complete" },
      };
      res.write(JSON.stringify(bye) + "\n");
      res.end();
    }
  }, 1000);
});

// --- 서버 기동 ---
const PORT = Number(process.env.PORT || 3000);
const HOST = "0.0.0.0";
app.listen(PORT, HOST, () => {
  console.log(`[MCP] Server listening on http://${HOST}:${PORT} (build=${BUILD_TAG})`);
});
