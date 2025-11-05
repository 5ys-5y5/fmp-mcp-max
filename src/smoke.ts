import "dotenv/config";
import { FmpClient } from "./fmp.js";

async function main() {
  const apiKey = process.env.FMP_API_KEY;
  if (!apiKey) {
    console.error("❌ FMP_API_KEY가 없습니다. .env 파일을 확인하세요.");
    process.exit(1);
  }
  const fmp = new FmpClient({ apiKey });

  try {
    console.log("🔎 심볼 검색: query=AAPL");
    const search = await fmp.get("/stable/search-symbol", { query: "AAPL" }, 5);
    console.log("검색 결과 예시 1개:", Array.isArray(search) ? search[0] : search);

    console.log("💹 현재가 확인: symbol=AAPL");
    const quote = await fmp.get("/stable/quote", { symbol: "AAPL" }, 5);
    const row = Array.isArray(quote) ? quote[0] : quote;
    console.log(`AAPL 가격: ${row?.price ?? row?.c ?? "?"}`);

    console.log("✅ FMP API 통신 성공!");
    process.exit(0);
  } catch (e:any) {
    console.error("❌ FMP API 통신 실패:", e?.message || e);
    process.exit(2);
  }
}

main();
