import { z } from "zod";
import { ToolDef } from "./types.js";

export const tools: ToolDef[] = [
  { name: "search_symbol", title: "Search Symbol", description: "Search tickers/companies by query", path: "/stable/search-symbol", params: { query: z.string().min(1) }, ttlSeconds: 60 },
  { name: "quote", title: "Get Quote", description: "Real-time quote for a stock symbol", path: "/stable/quote", params: { symbol: z.string().min(1) }, ttlSeconds: 5 },
  { name: "aftermarket_quote", title: "Aftermarket Quote", description: "Bid/Ask and sizes outside regular hours", path: "/stable/aftermarket-quote", params: { symbol: z.string().min(1) }, ttlSeconds: 5 },
  { name: "quote_change", title: "Quote Price Changes", description: "Multi-horizon price change summary", path: "/stable/stock-price-change", params: { symbol: z.string().min(1) }, ttlSeconds: 15 },
  { name: "income_statement", title: "Income Statement", description: "Financial statements (income)", path: "/stable/income-statement", params: { symbol: z.string().min(1), period: z.enum(["annual","quarter"]).default("annual"), limit: z.number().int().min(1).max(120).default(10) }, ttlSeconds: 300 },
  { name: "balance_sheet", title: "Balance Sheet", description: "Financial statements (balance sheet)", path: "/stable/balance-sheet-statement", params: { symbol: z.string().min(1), period: z.enum(["annual","quarter"]).default("annual"), limit: z.number().int().min(1).max(120).default(10) }, ttlSeconds: 300 },
  { name: "cash_flow", title: "Cash Flow", description: "Financial statements (cash flow)", path: "/stable/cash-flow-statement", params: { symbol: z.string().min(1), period: z.enum(["annual","quarter"]).default("annual"), limit: z.number().int().min(1).max(120).default(10) }, ttlSeconds: 300 },
  { name: "financial_ratios", title: "Financial Ratios", description: "Common financial ratios", path: "/stable/ratios", params: { symbol: z.string().min(1), period: z.enum(["annual","quarter"]).default("annual"), limit: z.number().int().min(1).max(60).default(10) }, ttlSeconds: 300 },
  { name: "company_profile", title: "Company Profile", description: "Profile & key info for a symbol", path: "/stable/profile", params: { symbol: z.string().min(1) }, ttlSeconds: 60 },
  { name: "news", title: "Market/Company News", description: "News feed for symbol or general market", path: "/stable/stock_news", params: { tickers: z.string().optional(), limit: z.number().int().min(1).max(200).default(50) }, ttlSeconds: 30 },
  { name: "indices_quote", title: "Index Quote", description: "Quote for market index (e.g. ^GSPC)", path: "/stable/quote", params: { symbol: z.string().min(1) }, ttlSeconds: 5 },
  { name: "forex_quote", title: "Forex Quotes", description: "Latest forex rate for a pair (EURUSD)", path: "/stable/forex", params: { symbol: z.string().min(6) }, ttlSeconds: 5 },
  { name: "crypto_quote", title: "Crypto Quote", description: "Cryptocurrency quote (BTCUSD)", path: "/stable/crypto", params: { symbol: z.string().min(3) }, ttlSeconds: 5 },
  { name: "commodities_list", title: "Commodities List", description: "Available commodities directory", path: "/stable/commodities/list", params: {}, ttlSeconds: 600 },
  { name: "commodities_prices", title: "Commodity Prices", description: "Current prices for a commodity", path: "/stable/commodities", params: { symbol: z.string().min(1) }, ttlSeconds: 30 },
  { name: "historical_price", title: "Historical Price (daily)", description: "EOD historical prices (date range)", path: "/stable/historical-price-full", params: { symbol: z.string().min(1), from: z.string().optional(), to: z.string().optional(), serietype: z.enum(["line","candle"]).default("line") }, ttlSeconds: 120 },
  { name: "ema", title: "Technical EMA", description: "Exponential Moving Average", path: "/stable/ema", params: { symbol: z.string().min(1), time_period: z.number().int().min(2).max(365).default(20) }, ttlSeconds: 60 },
  { name: "search_directory", title: "Search Directory (CIK/ISIN)", description: "Symbol directory & lookup", path: "/stable/search", params: { query: z.string().min(1), limit: z.number().int().min(1).max(500).default(50) }, ttlSeconds: 300 }
];
