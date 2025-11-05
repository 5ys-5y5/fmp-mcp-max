import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { FmpClient } from "./fmp.js";

/** Generic GET proxy for /stable, /api/v3, /api/v4 */
export function registerAnyGetTool(server: McpServer, fmp: FmpClient) {
  server.registerTool(
    "fmp_any_get",
    {
      title: "FMP Any GET",
      description: "Call FMP GET endpoints under /stable, /api/v3, or /api/v4 with arbitrary query params.",
      inputSchema: z.object({
        path: z.string().regex(/^\/(stable|api\/v3|api\/v4)\//, "경로는 /stable, /api/v3, /api/v4 중 하나로 시작해야 합니다."),
        params: z.record(z.string(), z.string()).default({}),
        ttl: z.number().int().min(0).max(3600).default(30)
      })
    },
    async ({ path, params, ttl }) => {
      const data = await fmp.get(path, params, ttl);
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: data };
    }
  );
}
