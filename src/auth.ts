// src/auth.ts
import type { Request, Response, NextFunction } from "express";

function getAllowedKeys(): string[] {
  const raw = process.env.APP_API_KEYS || process.env.APP_API_KEY || "";
  return raw.split(",").map(s => s.trim()).filter(Boolean);
}

function extractProvidedKey(req: Request): string | null {
  // 1) 권장: 헤더
  const hdr = req.header("x-api-key");
  if (hdr) return hdr;
  // 2) 대안: Authorization: Bearer <key>
  const auth = req.header("authorization");
  if (auth?.toLowerCase().startsWith("bearer ")) {
    return auth.slice(7).trim();
  }
  // 3) 대안: 쿼리스트링 ?key=<...>
  const q = req.query["key"];
  if (typeof q === "string") return q;
  return null;
}

export function requireApiKey() {
  const allowed = new Set(getAllowedKeys());

  // allowed 가 비어있으면 "잠금 비활성화" (기존과 호환)
  // 꼭 잠그고 싶으면 APP_API_KEYS를 반드시 채우세요.
  const lockEnabled = allowed.size > 0;

  return (req: Request, res: Response, next: NextFunction) => {
    if (!lockEnabled) return next(); // 잠금 미사용

    const provided = extractProvidedKey(req);
    if (!provided || !allowed.has(provided)) {
      // 통일된 에러 메시지
      return res.status(401).json({ error: "unauthorized", hint: "provide x-api-key header or ?key=..." });
    }
    next();
  };
}

export function maybeProtectHealth() {
  return (req: Request, res: Response, next: NextFunction) => {
    const protect = (process.env.APP_PROTECT_HEALTH || "").trim() === "1";
    if (!protect) return next();
    return requireApiKey()(req, res, next);
  };
}
