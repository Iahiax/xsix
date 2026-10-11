import assert from "node:assert/strict";
import { test } from "node:test";
import { createCapitalReadOnlyClient } from "../src/lib/capital-client";

const testEnv = {
  CAPITAL_API_KEY: "test-capital-key",
  CAPITAL_EMAIL: "test@example.invalid",
  CAPITAL_API_PASSWORD: "test-password",
};

test("Capital account reads authenticate once, use GET only for resources, and mask identifiers", async () => {
  const requests: Array<{ url: string; method: string; body?: string }> = [];
  const fetcher: typeof fetch = async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    requests.push({ url, method, body: typeof init?.body === "string" ? init.body : undefined });
    if (url.endsWith("/api/v1/session")) {
      return new Response(null, {
        status: 200,
        headers: { CST: "session-cst", "X-SECURITY-TOKEN": "session-security" },
      });
    }
    if (url.endsWith("/api/v1/accounts")) {
      return Response.json({
        currentAccountId: "account-987654",
        accounts: [{
          accountId: "account-987654",
          preferred: true,
          currencyIsoCode: "USD",
          accountInfo: { balance: 1200.5, available: 900, deposit: 100, profitLoss: 4.5 },
        }],
      });
    }
    if (url.endsWith("/api/v1/positions")) {
      return Response.json({
        positions: [{
          position: {
            dealId: "deal-secret-4321",
            direction: "BUY",
            size: 0.2,
            level: 12.5,
            profit: 2.5,
            currency: "USD",
            createdDateUTC: "2026-10-11T00:00:00Z",
          },
          market: {
            epic: "TEST.EPIC",
            instrumentName: "Test instrument",
            bid: 12.6,
            offer: 12.7,
            marketStatus: "TRADEABLE",
          },
        }],
      });
    }
    throw new Error(`Unexpected request: ${url}`);
  };
  const client = createCapitalReadOnlyClient({ env: testEnv, fetcher });

  const first = await client.getAccountSnapshot();
  const second = await client.getAccountSnapshot();

  assert.equal(first.state, "connected");
  assert.equal(first.environment, "demo");
  assert.equal(first.balance, 1200.5);
  assert.equal(first.positions[0]?.id, "••4321");
  assert.equal(first.accountIdSuffix, "7654");
  assert.equal(second.checkedAt, first.checkedAt);
  assert.equal(requests.length, 3);
  assert.deepEqual(requests.map((request) => request.method).sort(), ["GET", "GET", "POST"]);
  assert.equal(requests[0]?.method, "POST");
  assert.ok(requests[0]?.url.startsWith("https://demo-api-capital.backend-capital.com/"));
  assert.equal(JSON.parse(requests[0]?.body ?? "{}").identifier, "test@example.invalid");
  assert.doesNotMatch(JSON.stringify(first), /test-capital-key|test-password|deal-secret/);
});

test("Capital markets searches return the provider quote and encode the search term", async () => {
  const requests: string[] = [];
  const fetcher: typeof fetch = async (input, init) => {
    const url = String(input);
    requests.push(`${init?.method ?? "GET"} ${url}`);
    if (url.endsWith("/api/v1/session")) {
      return new Response(null, {
        status: 200,
        headers: { CST: "session-cst", "X-SECURITY-TOKEN": "session-security" },
      });
    }
    return Response.json({
      markets: [{
        epic: "TEST.EPIC",
        instrumentName: "Test market",
        instrumentType: "CURRENCIES",
        marketStatus: "TRADEABLE",
        bid: 1.234,
        offer: 1.235,
        netChange: 0.01,
        percentageChange: 0.8,
        currency: "USD",
      }],
    });
  };
  const client = createCapitalReadOnlyClient({ env: testEnv, fetcher });
  const result = await client.searchMarkets("test & market");

  assert.equal(result.state, "connected");
  assert.equal(result.markets[0]?.bid, 1.234);
  assert.ok(requests.some((request) => request.includes("searchTerm=test+%26+market")));
  assert.deepEqual(requests.map((request) => request.split(" ")[0]).sort(), ["GET", "POST"]);
});

test("missing Capital configuration reports not configured without network access", async () => {
  let fetchCount = 0;
  const fetcher: typeof fetch = async () => {
    fetchCount += 1;
    return new Response(null, { status: 500 });
  };
  const client = createCapitalReadOnlyClient({ env: {}, fetcher });
  const account = await client.getAccountSnapshot();
  const markets = await client.searchMarkets("EUR");

  assert.equal(account.state, "not_configured");
  assert.equal(account.balance, null);
  assert.equal(markets.state, "not_configured");
  assert.deepEqual(markets.markets, []);
  assert.equal(fetchCount, 0);
});
