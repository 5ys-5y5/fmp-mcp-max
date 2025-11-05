import { McpServer, ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
import { FmpClient } from "./fmp.js";

export function registerResources(server: McpServer, fmp: FmpClient) {
  server.registerResource(
    "fmp-quote",
    new ResourceTemplate("fmp://quote/{symbol}", { list: undefined }),
    { title: "FMP Quote Resource", description: "Dynamic quote as text" },
    async (uri, { symbol }: { symbol: string | string[] }) => {
      const sym = Array.isArray(symbol) ? symbol[0] : symbol; // ⬅ 문자열 보장
      const data = await fmp.get("/stable/quote", { symbol: sym }, 5);
      const row = Array.isArray(data) ? data[0] : data;
      const lines = [
        `Symbol: ${row?.symbol ?? sym}`,
        `Price: ${row?.price ?? row?.c ?? "?"}`,
        `Change: ${row?.change ?? row?.d ?? "?"} (${row?.changesPercentage ?? row?.dp ?? "?"}%)`,
        `Updated: ${new Date().toISOString()}`,
      ];
      return { contents: [{ uri: uri.href, text: lines.join("\n") }] };
    }
  );
}
