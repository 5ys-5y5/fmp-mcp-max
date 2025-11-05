import { z } from "zod";

export type HttpParams = Record<string, string | number | boolean | undefined>;

export const symbolSchema = z.string().min(1).describe("Ticker symbol, e.g. AAPL");
export const forexPairSchema = z.string().min(6).describe("Forex pair, e.g. EURUSD");
export const cryptoSymbolSchema = z.string().min(1).describe("Crypto symbol, e.g. BTCUSD");
export const indexSymbolSchema = z.string().min(1).describe("Index symbol, e.g. ^GSPC or ^NDX");
export const periodSchema = z.enum(["annual", "quarter"]).default("annual");
export const limitSchema = z.number().int().positive().max(200).default(10);
export const dateSchema = z.string().regex(/^\d{4}-\d{2}-\d{2}$/).describe("YYYY-MM-DD");

export type ToolDef = {
  name: string;
  title: string;
  description: string;
  path: string; // FMP path like "/stable/quote"
  params: Record<string, z.ZodTypeAny>;
  toQuery?: (args: any) => HttpParams; // optional param mapping
  ttlSeconds?: number; // cache TTL
};
