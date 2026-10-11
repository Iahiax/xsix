import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createServer, type Server } from "node:http";
import express from "express";
import { captureApiErrors } from "../src/lib/error-events";
import healthRouter from "../src/routes/health";

const app = express();
app.use(captureApiErrors);
app.get("/probe/:id", (_req, res) => {
  res.status(503).json({ error: "sensitive upstream details must not be retained" });
});
app.use("/api", healthRouter);

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
    server.close((error) => (error ? reject(error) : resolve())),
  );
});

test("5xx diagnostics keep only bounded, sanitized request metadata", async () => {
  const failed = await fetch(`${serverUrl}/probe/account-742?token=never-store-this`);
  assert.equal(failed.status, 503);

  const response = await fetch(`${serverUrl}/api/system/diagnostics`);
  assert.equal(response.status, 200);
  const body = (await response.json()) as {
    state: string;
    errorCount: number;
    recentErrors: Array<{
      statusCode: number;
      method: string;
      path: string;
      requestId: string | null;
    }>;
  };
  assert.equal(body.state, "attention");
  assert.equal(body.errorCount, 1);
  assert.equal(body.recentErrors[0]?.statusCode, 503);
  assert.equal(body.recentErrors[0]?.method, "GET");
  assert.equal(body.recentErrors[0]?.path, "/probe/:id");
  assert.equal(body.recentErrors[0]?.requestId, null);
  assert.doesNotMatch(JSON.stringify(body), /never-store-this|sensitive upstream details|account-742/);
});
