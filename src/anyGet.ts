import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import type { FmpClient } from "./fmp.js";

/** Generic GET proxy for /stable, /api/v3, /api/v4 */
export function registerAnyGetTool(server: McpServer, fmp: FmpClient) {
  const schema = z.object({
    path: z
      .string()
      .regex(/^\/(stable|api\/v3|api\/v4)\//, "경로는 /stable, /api/v3, /api/v4 중 하나로 시작해야 합니다."),
    params: z.record(z.string(), z.string()).default({}),
    ttl: z.number().int().min(0).max(3600).default(30),
  });

  server.registerTool(
    "fmp_any_get",
    {
      title: "FMP Any GET",
      description: "Call FMP GET endpoints under /stable, /api/v3, or /api/v4 with arbitrary query params.",
      inputSchema: schema as any, // SDK 타입 불일치 회피
    },
    (async (args: any) => {
      const path = String(args.path);
      const params = (args.params ?? {}) as Record<string, string>;
      const ttl = Number(args.ttl ?? 30);

      const data = await fmp.get(path, params, ttl);
      return {
        content: [{ type: "text", text: JSON.stringify(data, null, 2) }],
        structuredContent: data,
      } as any; // MCP ToolResult 타입 캐스팅
    }) as any
  );
}
