import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import { FmpClient } from "./fmp.js";
import { tools } from "./endpoints.js";

export function registerAllTools(server: McpServer, fmp: FmpClient) {
  for (const def of tools) {
    // ⬇⬇⬇ as any 추가
    const inputSchema = z.object(def.params as any) as any;

    server.registerTool(
      def.name,
      { title: def.title, description: def.description, inputSchema },
      async (args: Record<string, unknown>) => {
        const searchParams: Record<string, string> = {};
        for (const k of Object.keys(def.params)) {
          const v = (args as any)[k];
          if (v !== undefined) searchParams[k.replace(/_/g, "")] = String(v);
        }
        const data = await fmp.get(def.path, searchParams, def.ttlSeconds ?? 10);
        return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }], structuredContent: data };
      }
    );
  }
}
