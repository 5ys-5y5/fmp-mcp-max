/**
 * FMP MCP (HTTP) — enumerate all FMP endpoints as Actions
 *
 * ✔ /health : liveness
 * ✔ /mcp    : tool discovery (lists ALL actions)
 * ✔ /mcp/:toolName : tool invocation (proxy to FMP REST)
 *
 * Security:
 *   - APP_API_KEY: optional server gate (pass via ?key= or x-api-key header)
 *   - FMP_API_KEY: your FMP apikey (auto-injected to every request)
 */

const express = require('express');
const cors = require('cors');
const cheerio = require('cheerio');
const fetch = globalThis.fetch ? globalThis.fetch.bind(globalThis) : undefined;

const PORT = process.env.PORT || 10000;
const APP_API_KEY = process.env.APP_API_KEY || null; // optional gate
const FMP_API_KEY = process.env.FMP_API_KEY || "";   // strongly recommended

const FMP_HOST = 'https://financialmodelingprep.com';
const FMP_DOCS = 'https://site.financialmodelingprep.com/developer/docs';

const app = express();
app.use(cors());
app.use(express.json({ limit: '1mb' }));

// --- helpers ---------------------------------------------------------------
function gate(req, res, next) {
  if (!APP_API_KEY) return next();
  const key = req.query.key || req.headers['x-api-key'];
  if (key && String(key) === String(APP_API_KEY)) return next();
  return res.status(401).json({ error: 'unauthorized: missing/invalid key' });
}

/** normalize tool name from path, e.g. /api/v3/quote → fmp_api_v3_quote */
function toolNameFromPath(path) {
  return 'fmp' + path.replace(/[^a-zA-Z0-9]+/g, '_');
}

/** Build a single tool descriptor (MCP over HTTP compatible) */
function buildToolDescriptor(path) {
  return {
    name: toolNameFromPath(path),
    description: `GET ${path} — Proxies to FMP. Pass query params in \"query\" object.`,
    input_schema: {
      type: 'object',
      properties: {
        // optional symbol shortcut (will be appended to path if it ends with /:symbol)
        symbol: { type: 'string' },
        query: { type: 'object', additionalProperties: true }
      },
      additionalProperties: false
    },
    metadata: { method: 'GET', path }
  };
}

/**
 * Minimal but robust list of seed endpoints (used if docs scrape fails)
 * These already cover the majority of common tasks.
 */
const SEED_ENDPOINTS = [
  '/api/v3/quote',
  '/api/v3/quote-short',
  '/api/v3/profile',
  '/api/v3/search',
  '/api/v3/stock/list',
  '/api/v3/financials/income-statement',
  '/api/v3/financials/balance-sheet-statement',
  '/api/v3/financials/cash-flow-statement',
  '/api/v3/income-statement',
  '/api/v3/balance-sheet-statement',
  '/api/v3/cash-flow-statement',
  '/api/v3/ratios',
  '/api/v3/enterprise-values',
  '/api/v3/historical-price-full',
  '/api/v3/historical-chart/1min',
  '/api/v3/historical-chart/5min',
  '/api/v3/historical-chart/15min',
  '/api/v3/historical-chart/30min',
  '/api/v3/historical-chart/1hour',
  '/api/v3/historical-chart/4hour',
  '/api/v3/stock_news',
  '/api/v3/etf/list',
  '/api/v3/etf/sector-weightings',
  '/api/v3/etf/holdings',
  '/api/v3/forex',
  '/api/v3/crypto',
  '/api/v3/treasury',
  '/api/v3/discounted-cash-flow',
  '/api/v3/key-metrics',
  '/api/v3/analyst-estimates'
];

/** Discover endpoints by scraping FMP docs (best-effort). */
async function discoverEndpoints() {
  try {
    const html = await fetch(FMP_DOCS, { timeout: 15000 }).then(r => r.text());
    const $ = cheerio.load(html);
    const set = new Set(SEED_ENDPOINTS);

    $('code, pre').each((_, el) => {
      const txt = $(el).text();
      (txt.match(/\/api\/v\d+\/[a-zA-Z0-9_\/-]+/g) || []).forEach((m) => {
        // Exclude Swagger examples with domains; keep path only
        const path = m.replace(/https?:\/\/[a-zA-Z0-9.-]+/, '');
        // sanity check: looks like a path
        if (path.startsWith('/api/')) set.add(path);
      });
    });

    // Return sorted list for stable tool order
    return Array.from(set).sort();
  } catch (e) {
    console.warn('[discoverEndpoints] failed, falling back to seeds:', e.message);
    return SEED_ENDPOINTS;
  }
}

/** Compose URL for FMP call */
function buildFmpUrl(path, query = {}) {
  const url = new URL(path, FMP_HOST);
  const entries = Object.entries(query || {});
  for (const [k, v] of entries) {
    if (v === undefined || v === null) continue;
    url.searchParams.set(k, String(v));
  }
  if (FMP_API_KEY) url.searchParams.set('apikey', FMP_API_KEY);
  return url.toString();
}

/** Execute a GET call to FMP */
async function callFmp(path, query) {
  const url = buildFmpUrl(path, query);
  const r = await fetch(url, { headers: { 'accept': 'application/json' } });
  const text = await r.text();

  // Try JSON first, then fallback to text
  try {
    return { ok: r.ok, status: r.status, data: JSON.parse(text) };
  } catch (_) {
    return { ok: r.ok, status: r.status, data: text };
  }
}

// --- MCP HTTP contract -----------------------------------------------------
let TOOLS = {};

app.get('/health', (_req, res) => {
  res.json({ ok: true, name: 'fmp-mcp', version: '2.0.0' });
});

// List tools (what ChatGPT shows under \"액션\")
app.get('/mcp', gate, (_req, res) => {
  res.json({
    name: 'FMP_MCP',
    version: '2.0.0',
    tools: Object.values(TOOLS).map(t => ({
      name: t.name,
      description: t.description,
      input_schema: t.input_schema
    }))
  });
});

// Invoke tool — POST /mcp/:toolName
app.post('/mcp/:name', gate, async (req, res) => {
  const name = req.params.name;
  const tool = TOOLS[name];
  if (!tool) return res.status(404).json({ error: `unknown tool: ${name}` });

  try {
    const args = req.body?.arguments || req.body || {};
    const query = args.query || {};

    // Allow smart shorthand: if tool has a :symbol form, append args.symbol
    let path = tool.metadata.path;
    if (args.symbol && /\/:symbol$/.test(path)) {
      path = path.replace(/:symbol$/, encodeURIComponent(args.symbol));
    }

    const out = await callFmp(path, query);

    // MCP over HTTP: return toolResult-like payload
    res.json({
      content: [
        {
          type: 'json',
          json: out
        }
      ]
    });
  } catch (e) {
    res.status(500).json({ error: e.message || String(e) });
  }
});

// Boot: discover and build tool table
async function boot() {
  const paths = await discoverEndpoints();
  TOOLS = {};
  // Create an action per endpoint
  for (const p of paths) {
    TOOLS[toolNameFromPath(p)] = buildToolDescriptor(p);
  }

  // Generic super-tool (always present)
  TOOLS['fmp_request'] = {
    name: 'fmp_request',
    description:
      'Generic FMP request. Provide path like "/api/v3/quote" and optional query object (e.g., { symbol: "AAPL" }).',
    input_schema: {
      type: 'object',
      properties: {
        path: { type: 'string' },
        query: { type: 'object', additionalProperties: true }
      },
      required: ['path'],
      additionalProperties: false
    },
    metadata: { method: 'GET', path: '/__dynamic__' }
  };

  // Bind generic executor at the same route shape
  app.post('/mcp/fmp_request', gate, async (req, res) => {
    try {
      const args = req.body?.arguments || req.body || {};
      if (!args.path) return res.status(400).json({ error: 'missing path' });
      const out = await callFmp(args.path, args.query || {});
      res.json({ content: [{ type: 'json', json: out }] });
    } catch (e) {
      res.status(500).json({ error: e.message || String(e) });
    }
  });

  app.listen(PORT, () => {
    console.log(`[FMP MCP] listening on :${PORT}`);
  });
}

boot().catch((e) => {
  console.error('Failed to boot MCP server:', e);
  process.exit(1);
});