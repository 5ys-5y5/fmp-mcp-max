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
      // ⬇⬇⬇ 여기 as any 추가
      inputSchema: z.object({
        path: z.string().regex(/^\/(stable|api\/v3|api\/v4)\//, "경로는 /stable, /api/v3, /api/v4 중 하나로 시작해야 합니다."),
        params: z.record(z.string(), z.string()).default({}),
        ttl: z.number().int().min(0).max(3600).default(30),
      }) as any,
    },
    // (선택) 인자에 타입 표기
    async ({ path, params, ttl }: { path: string; params: Record<string, string>; ttl: number }) => {
      const data = await fmp.get(path, params, ttl);
      return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: data };
    }
  );
}
