import { spawnSync } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const artifactDir = path.dirname(fileURLToPath(import.meta.url));
const testDir = await mkdtemp(path.join(artifactDir, ".test-build-"));
const testBundle = path.join(testDir, "all.test.mjs");
const testEntry = path.join(artifactDir, "all.test.ts");

try {
  await build({
    entryPoints: [testEntry],
    outfile: testBundle,
    bundle: true,
    platform: "node",
    format: "esm",
    packages: "external",
    alias: {
      "@workspace/api-zod": fileURLToPath(
        new URL("../../../lib/api-zod/src/index.ts", import.meta.url),
      ),
      zod: fileURLToPath(
        new URL("../../../lib/api-zod/node_modules/zod/index.js", import.meta.url),
      ),
    },
    sourcemap: "inline",
  });
  const result = spawnSync(process.execPath, ["--test", testBundle], {
    stdio: "inherit",
    env: process.env,
  });
  if (result.error) throw result.error;
  process.exitCode = result.status ?? 1;
} finally {
  await rm(testDir, { recursive: true, force: true });
}
