import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createServer, request as httpRequest, type Server } from "node:http";
import express from "express";
import router from "../src/routes/trading";

const app = express();
const warnings: unknown[] = [];
app.use((req, _res, next) => {
  (req as typeof req & { log: { warn: (...args: unknown[]) => void } }).log = {
    warn: (...args) => warnings.push(args),
  };
  next();
});
app.use("/api", router);

let server: Server;
let serverUrl: string;
before(async () => {
  server = createServer(app);
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  serverUrl = `http://127.0.0.1:${address.port}`;
});
after(async () => {
  await new Promise<void>((resolve, reject) =>
    server.close((error) => error ? reject(error) : resolve()),
  );
});

test("economic and company endpoints show not-configured states without provider calls", async () => {
  const previousFredKey = process.env.FRED_API_KEY;
  const previousFmpKey = process.env.FMP_API_KEY;
  const originalFetch = globalThis.fetch;
  delete process.env.FRED_API_KEY;
  delete process.env.FMP_API_KEY;
  globalThis.fetch = (async () => {
    throw new Error("A provider must not be called without credentials.");
  }) as typeof fetch;

  try {
    const economicResponse = await get("/api/trading/economic-data");
    const economic = await economicResponse.json() as {
      state: string;
      configured: boolean;
      indicators: Array<{ value: number | null; freshness: string; source: string }>;
    };
    assert.equal(economicResponse.status, 200);
    assert.equal(economic.state, "not_configured");
    assert.equal(economic.configured, false);
    assert.equal(economic.indicators.length, 4);
    assert.ok(economic.indicators.every((row) =>
      row.value === null && row.freshness === "unavailable" && row.source === "FRED",
    ));

    const fundamentalsResponse = await get("/api/trading/fundamentals");
    const fundamentals = await fundamentalsResponse.json() as {
      state: string;
      configured: boolean;
      fundamentals: unknown[];
    };
    assert.equal(fundamentalsResponse.status, 200);
    assert.equal(fundamentals.state, "not_configured");
    assert.equal(fundamentals.configured, false);
    assert.deepEqual(fundamentals.fundamentals, []);
  } finally {
    globalThis.fetch = originalFetch;
    restoreEnv("FRED_API_KEY", previousFredKey);
    restoreEnv("FMP_API_KEY", previousFmpKey);
  }
});

test("provider observations and fundamentals keep provenance and sanitized rate-limit errors", async () => {
  const previousFredKey = process.env.FRED_API_KEY;
  const previousFmpKey = process.env.FMP_API_KEY;
  const originalFetch = globalThis.fetch;
  process.env.FRED_API_KEY = "fake-fred-test-key";
  process.env.FMP_API_KEY = "fake-fmp-test-key";
  const providerRequests: string[] = [];
  globalThis.fetch = (async (input) => {
    const url = new URL(String(input));
    providerRequests.push(url.pathname);
    if (url.hostname === "api.stlouisfed.org") {
      return Response.json({
        observations: [{ date: new Date().toISOString().slice(0, 10), value: "3.2" }],
      });
    }
    if (url.pathname.endsWith("/stable/profile")) {
      return Response.json([{
        symbol: url.searchParams.get("symbol"),
        companyName: "Example Company",
        sector: "Technology",
        industry: "Software",
        currency: "USD",
        marketCap: 1_000_000,
      }]);
    }
    if (url.searchParams.get("symbol") === "RATE") {
      return new Response(null, { status: 429 });
    }
    return Response.json([{
      symbol: url.searchParams.get("symbol"),
      date: new Date().toISOString().slice(0, 10),
      marketCap: 1_000_000,
      peRatio: 20,
      pbRatio: 4,
      priceToSalesRatio: 6,
      returnOnEquity: 0.24,
    }]);
  }) as typeof fetch;

  try {
    const economicResponse = await get("/api/trading/economic-data");
    const economic = await economicResponse.json() as {
      state: string;
      provider: string;
      indicators: Array<{ value: number | null; source: string; observationDate: string | null; retrievedAt: string }>;
    };
    assert.equal(economic.state, "connected");
    assert.equal(economic.provider, "FRED");
    assert.equal(economic.indicators[0]?.value, 3.2);
    assert.equal(economic.indicators[0]?.source, "FRED");
    assert.ok(economic.indicators[0]?.observationDate);
    assert.ok(economic.indicators[0]?.retrievedAt);

    const fundamentalsResponse = await get("/api/trading/fundamentals?symbols=AAPL");
    const fundamentals = await fundamentalsResponse.json() as {
      state: string;
      fundamentals: Array<{ companyName: string | null; peRatio: number | null; source: string; asOf: string | null; retrievedAt: string }>;
    };
    assert.equal(fundamentals.state, "connected");
    assert.equal(fundamentals.fundamentals[0]?.companyName, "Example Company");
    assert.equal(fundamentals.fundamentals[0]?.peRatio, 20);
    assert.equal(fundamentals.fundamentals[0]?.source, "FMP");
    assert.ok(fundamentals.fundamentals[0]?.asOf);
    assert.ok(fundamentals.fundamentals[0]?.retrievedAt);

    const rateLimitResponse = await get("/api/trading/fundamentals?symbols=RATE");
    const rateLimit = await rateLimitResponse.json() as {
      state: string;
      errors: string[];
    };
    assert.equal(rateLimit.state, "partial");
    assert.ok(rateLimit.errors.some((message) => message.includes("حد الطلبات")));
    assert.doesNotMatch(JSON.stringify(rateLimit), /fake-fmp-test-key/);
    assert.doesNotMatch(JSON.stringify(warnings), /fake-(?:fred|fmp)-test-key/);
    assert.equal(providerRequests.filter((path) => path.endsWith("/fred/series/observations")).length, 4);
  } finally {
    globalThis.fetch = originalFetch;
    restoreEnv("FRED_API_KEY", previousFredKey);
    restoreEnv("FMP_API_KEY", previousFmpKey);
  }
});

test("fundamentals reject too many or malformed symbols before provider access", async () => {
  const previousFmpKey = process.env.FMP_API_KEY;
  const originalFetch = globalThis.fetch;
  process.env.FMP_API_KEY = "fake-fmp-test-key";
  globalThis.fetch = (async () => {
    throw new Error("Invalid requests must not reach the provider.");
  }) as typeof fetch;

  try {
    const tooMany = await get("/api/trading/fundamentals?symbols=AAPL,MSFT,NVDA,TSLA,AMZN");
    const malformed = await get("/api/trading/fundamentals?symbols=AAPL,");
    assert.equal(tooMany.status, 400);
    assert.equal(malformed.status, 400);
  } finally {
    globalThis.fetch = originalFetch;
    restoreEnv("FMP_API_KEY", previousFmpKey);
  }
});

function get(path: string): Promise<Response> {
  return new Promise((resolve, reject) => {
    httpRequest(`${serverUrl}${path}`, (incoming) => {
      const chunks: Buffer[] = [];
      incoming.on("data", (chunk: Buffer) => chunks.push(chunk));
      incoming.on("end", () => resolve(new Response(Buffer.concat(chunks), {
        status: incoming.statusCode ?? 500,
        headers: incoming.headers as HeadersInit,
      })));
    }).on("error", reject).end();
  });
}

function restoreEnv(name: string, value: string | undefined): void {
  if (value === undefined) delete process.env[name];
  else process.env[name] = value;
}
