import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { createServer, request as httpRequest, type Server } from "node:http";
import express from "express";
import router from "../src/routes/trading";

const app = express();
app.use(express.json());
app.use((req, _res, next) => {
  (req as typeof req & { log: { error: () => void } }).log = { error() {} };
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
    server.close((error) => (error ? reject(error) : resolve())),
  );
});

test("upstream authorization and readiness failures report unavailable without any model fallback", async () => {
  const originalFetch = globalThis.fetch;
  const originalEnv = {
    url: process.env.LOCAL_MODEL_URL,
    apiToken: process.env.LOCAL_MODEL_API_TOKEN,
    hfToken: process.env.LOCAL_MODEL_HF_TOKEN,
  };
  const requestedUrls: string[] = [];
  process.env.LOCAL_MODEL_URL = "https://private-space.hf.space";
  process.env.LOCAL_MODEL_API_TOKEN = "space-api-test-token";
  process.env.LOCAL_MODEL_HF_TOKEN = "hf-read-test-token";

  try {
    for (const upstreamStatus of [401, 403, 503]) {
      requestedUrls.length = 0;
      globalThis.fetch = (async (input) => {
        requestedUrls.push(String(input));
        return { ok: false, status: upstreamStatus } as Response;
      }) as typeof fetch;

      const response = await postChat();
      assert.equal(response.status, 503);
      const body = await response.json();
      assert.equal(body.source, "local_model_unavailable");
      assert.match(body.reply, /لم أستخدم النموذج الأساسي/);
      assert.equal(requestedUrls.length, 1);
      assert.equal(
        requestedUrls[0],
        "https://private-space.hf.space/v1/chat/completions",
      );
    }
  } finally {
    globalThis.fetch = originalFetch;
    restoreEnv("LOCAL_MODEL_URL", originalEnv.url);
    restoreEnv("LOCAL_MODEL_API_TOKEN", originalEnv.apiToken);
    restoreEnv("LOCAL_MODEL_HF_TOKEN", originalEnv.hfToken);
  }
});

async function postChat(): Promise<Response> {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({
      conversationId: "access-test-conversation",
      message: "ما حالة النموذج؟",
    });
    const outgoing = httpRequest(
      `${serverUrl}/api/assistant/chat`,
      {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "content-length": Buffer.byteLength(body),
        },
      },
      (incoming) => {
        const chunks: Buffer[] = [];
        incoming.on("data", (chunk: Buffer) => chunks.push(chunk));
        incoming.on("end", () => {
          resolve(
            new Response(Buffer.concat(chunks), {
              status: incoming.statusCode ?? 500,
              headers: incoming.headers as HeadersInit,
            }),
          );
        });
      },
    );
    outgoing.on("error", reject);
    outgoing.end(body);
  });
}

function restoreEnv(name: string, value: string | undefined): void {
  if (value === undefined) delete process.env[name];
  else process.env[name] = value;
}
