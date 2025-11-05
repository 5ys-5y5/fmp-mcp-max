import { setTimeout as sleep } from "node:timers/promises";
import { URL } from "node:url";
import { HttpParams } from "./types.js";

// Simple token-bucket limiter
class TokenBucket {
  private capacity: number;
  private tokens: number;
  private refillInterval: number;
  private lastRefill: number;
  constructor(rps: number) {
    this.capacity = Math.max(1, rps);
    this.tokens = this.capacity;
    this.refillInterval = 1000; // 1s
    this.lastRefill = Date.now();
  }
  async take() {
    while (true) {
      const now = Date.now();
      const elapsed = now - this.lastRefill;
      if (elapsed >= this.refillInterval) {
        const add = Math.floor(elapsed / this.refillInterval) * this.capacity;
        this.tokens = Math.min(this.capacity, this.tokens + add);
        this.lastRefill = now;
      }
      if (this.tokens > 0) {
        this.tokens -= 1;
        return;
      }
      await sleep(50);
    }
  }
}

// Tiny in-memory cache with TTL and de-dupe
export class Cache<T> {
  private store = new Map<string, { exp: number; value: T }>();
  get(key: string) {
    const hit = this.store.get(key);
    if (!hit) return undefined;
    if (hit.exp < Date.now()) { this.store.delete(key); return undefined; }
    return hit.value;
  }
  set(key: string, value: T, ttlMs: number) {
    this.store.set(key, { exp: Date.now() + ttlMs, value });
  }
}

export type FmpClientOpts = {
  apiKey: string;
  baseUrl?: string;
  rps?: number;
  timeoutMs?: number;
  proxyUrl?: string;
};

export class FmpClient {
  private base: string;
  private key: string;
  private limiter: TokenBucket;
  private timeoutMs: number;
  private cache = new Cache<any>();

  constructor(opts: FmpClientOpts) {
    this.base = (opts.baseUrl ?? process.env.FMP_BASE_URL ?? "https://financialmodelingprep.com").replace(/\/$/, "");
    this.key = opts.apiKey;
    this.limiter = new TokenBucket(Number(process.env.FMP_RPS ?? opts.rps ?? 4));
    this.timeoutMs = Number(process.env.FMP_TIMEOUT_MS ?? opts.timeoutMs ?? 15000);
  }

  private makeUrl(path: string, params: HttpParams = {}) {
    const url = new URL(path, this.base);
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined) url.searchParams.set(k, String(v));
    });
    url.searchParams.set("apikey", this.key);
    return url;
  }

  async get(path: string, params: HttpParams = {}, ttlSeconds = 10) {
    const url = this.makeUrl(path, params);
    const key = url.toString();
    const cached = this.cache.get(key);
    if (cached) return cached;

    await this.limiter.take();

    const controller = new AbortController();
    const t = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const res = await fetch(url, { signal: controller.signal, headers: { Accept: "application/json" } });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`FMP ${res.status} ${res.statusText}: ${text}`);
      }
      const data = await res.json();
      this.cache.set(key, data, ttlSeconds * 1000);
      return data;
    } finally {
      clearTimeout(t);
    }
  }
}
