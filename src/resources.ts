import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { FmpClient } from "./fmp.js";

export function registerResources(server: McpServer, fmp: FmpClient) {
  // 문자열 템플릿 오버로드 사용(타입 단순)
  server.registerResource(
    "fmp-quote",
    "fmp://quote/{symbol}",
    { title: "FMP Quote Resource", description: "Dynamic quote as text" },
    (async (uri: URL, variables: any) => {
      const sym = Array.isArray(variables?.symbol)
        ? String(variables.symbol[0])
        : String(variables?.symbol ?? "");

      const data = await fmp.get("/stable/quote", { symbol: sym }, 5);
      const row = Array.isArray(data) ? data[0] : data;

      const text = [
        `Symbol: ${row?.symbol ?? sym}`,
        `Price: ${row?.price ?? row?.c ?? "?"}`,
        `Change: ${row?.change ?? row?.d ?? "?"} (${row?.changesPercentage ?? row?.dp ?? "?"}%)`,
        `Updated: ${new Date().toISOString()}`,
      ].join("\n");

      return { contents: [{ uri: uri.toString(), text }] } as any; // 타입 단순화
    }) as any
  );
}
