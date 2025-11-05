// server.js
// Minimal MCP-over-HTTP server with SSE (2024-11-05) + JSON-RPC handling.
// Works on localhost and Render.com
// Node: >=18

const express = require("express");
const morgan = require("morgan");
const cors = require("cors");

const app = express();

// ---------- Basic middlewares ----------
app.use(morgan("tiny"));
app.use(express.json({ limit: "1mb" }));

// CORS (wide open for convenience; tighten in production)
app.use(
  cors({
    origin: true,
    credentials: false,
    exposedHeaders: ["mcp-session-id"],
  })
);

// ---------- Helpers ----------
const PROTOCOL_VERSION = "2024-11-05"; // Matches spec page
// Ref: https://modelcontextprotocol.io/specification/2024-11-05/basic/lifecycle

// Build full URL helper (keeps ?key=... etc.)
function fullUrl(req, path) {
  const scheme = req.headers["x-forwarded-proto"] || "http";
  const host = req.headers["x-forwarded-host"] || req.headers.host;
  // If caller passed ?key=... on GET /mcp, preserve it for POST endpoint too.
  const qs = req.originalUrl.includes("?")
    ? req.originalUrl.substring(req.originalUrl.indexOf("?"))
    : "";
  return `${scheme}://${host}${path}${qs}`;
}

// Small JSON-RPC helper
function makeResult(id, result) {
  return { jsonrpc: "2.0", id, result };
}
function makeError(id, code, message, data) {
  return { jsonrpc: "2.0", id, error: { code, message, data } };
}

// ---------- Health ----------
app.get("/health", (_req, res) => {
  res
    .status(200)
    .set("Access-Control-Expose-Headers", "mcp-session-id")
    .json({ status: "ok" });
});

// ---------- SSE endpoint (GET /mcp) ----------
app.get("/mcp", (req, res) => {
  // SSE headers
  res.status(200);
  res.set({
    "Content-Type": "text/event-stream; charset=utf-8",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Expose-Headers": "mcp-session-id",
  });

  // Immediately send the 'endpoint' event with the POST URL (spec requirement)
  // Ref: https://modelcontextprotocol.io/specification/2024-11-05/basic/transports
  const postUri = fullUrl(req, "/mcp"); // same path, keep ?key=... if present

  const payload = JSON.stringify({ uri: postUri });
  res.write(`event: endpoint\n`);
  res.write(`data: ${payload}\n\n`);

  // Keep the stream open. Some clients expect at least one heartbeat later.
  const keepAlive = setInterval(() => {
    res.write(`event: ping\n`);
    res.write(`data: {}\n\n`);
  }, 25_000);

  // Clean up on close
  req.on("close", () => {
    clearInterval(keepAlive);
  });
});

// ---------- CORS preflight (OPTIONS /mcp) ----------
app.options("/mcp", (req, res) => {
  res.set({
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers":
      "content-type, mcp-session-id, x-api-key, authorization",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Expose-Headers": "mcp-session-id",
  });
  res.status(200).send("POST");
});

// ---------- JSON-RPC endpoint (POST /mcp) ----------
app.post("/mcp", (req, res) => {
  res.set({
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Expose-Headers": "mcp-session-id",
    "Content-Type": "application/json; charset=utf-8",
  });

  const body = req.body;

  // Basic validation
  if (!body || typeof body !== "object" || body.jsonrpc !== "2.0") {
    return res
      .status(400)
      .json(
        makeError(
          null,
          -32600,
          "Invalid Request: expected JSON-RPC 2.0 object"
        )
      );
  }

  const { id, method, params } = body;

  // Handle known methods
  if (method === "initialize") {
    // Minimal initialize result per spec
    // https://modelcontextprotocol.io/specification/2024-11-05/basic/lifecycle
    const result = {
      protocolVersion: PROTOCOL_VERSION,
      serverInfo: {
        name: "fmp-mcp-max",
        version: "0.1.0",
      },
      capabilities: {
        // We support tools/resources/prompts listing via JSON-RPC methods below
        tools: {},
        resources: {},
        prompts: {},
      },
    };
    return res.status(200).json(makeResult(id, result));
  }

  if (method === "tools/list") {
    // You can put actual tools here later. Empty list is fine for connector creation.
    const result = { tools: [] };
    return res.status(200).json(makeResult(id, result));
  }

  if (method === "resources/list") {
    const result = { resources: [] };
    return res.status(200).json(makeResult(id, result));
  }

  if (method === "prompts/list") {
    const result = { prompts: [] };
    return res.status(200).json(makeResult(id, result));
  }

  // (Optional) A tiny ping utility so you can test roundtrips easily.
  if (method === "util/ping") {
    const now = new Date().toISOString();
    const result = { ok: true, now, echo: params ?? null };
    return res.status(200).json(makeResult(id, result));
  }

  // Fallback: method not found
  return res.status(200).json(makeError(id, -32601, "Method not found"));
});

// ---------- Start ----------
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`[MCP] Server started on :${PORT}`);
});
