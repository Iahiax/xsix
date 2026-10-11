import { randomUUID } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";
import { extname, relative, resolve } from "node:path";
import { gzipSync } from "node:zlib";
import { ReplitConnectors } from "@replit/connectors-sdk";

type DriveFile = {
  id: string;
  name: string;
  mimeType?: string;
  webViewLink?: string;
  createdTime?: string;
};

type DriveList = { files?: DriveFile[]; nextPageToken?: string };

const FOLDER_MIME = "application/vnd.google-apps.folder";
const PROJECT_FOLDER = "Unified Trading Intelligence";
const VERSIONS_FOLDER = "Project Versions";
const ROOT_FOLDER = "مرصاد";
const SOURCE_ROOTS = [
  "artifacts/trading-intelligence",
  "artifacts/api-server",
  "lib/api-spec",
  "lib/api-client-react",
  "lib/api-zod",
  "huggingface-space",
];
const ROOT_FILES = [
  ".gitignore",
  ".npmrc",
  ".replit",
  ".replitignore",
  "package.json",
  "pnpm-lock.yaml",
  "pnpm-workspace.yaml",
  "replit.md",
  "tsconfig.base.json",
  "tsconfig.json",
];
const SAFE_EXTENSIONS = new Set([
  ".ts", ".tsx", ".js", ".mjs", ".py", ".txt", ".css", ".yaml", ".yml", ".json", ".md", ".html", ".sh", ".conf",
]);
const MAX_SNAPSHOT_BYTES = 3 * 1024 * 1024;

let backupQueue: Promise<unknown> = Promise.resolve();

function escapeDriveQuery(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll("'", "\\'");
}

async function driveJson<T>(
  connectors: ReplitConnectors,
  path: string,
  options?: { method?: string; body?: string; headers?: Record<string, string> },
): Promise<T> {
  const response = await connectors.proxy("google-drive", path, options);
  if (!response.ok) {
    throw new Error(`Google Drive request failed (${response.status}) at ${path.split("?")[0]}`);
  }
  return (await response.json()) as T;
}

async function listFolders(
  connectors: ReplitConnectors,
  parentId: string | null,
  exactName?: string,
): Promise<DriveFile[]> {
  const predicates = ["trashed = false", `mimeType = '${FOLDER_MIME}'`];
  if (parentId) predicates.push(`'${escapeDriveQuery(parentId)}' in parents`);
  if (exactName) predicates.push(`name = '${escapeDriveQuery(exactName)}'`);
  const query = new URLSearchParams({
    q: predicates.join(" and "),
    pageSize: "100",
    orderBy: "createdTime desc",
    fields: "files(id,name,mimeType,webViewLink,createdTime)",
  });
  const response = await driveJson<DriveList>(
    connectors,
    `/drive/v3/files?${query.toString()}`,
    { method: "GET" },
  );
  return response.files ?? [];
}

async function createFolder(
  connectors: ReplitConnectors,
  name: string,
  parentId: string | null,
): Promise<DriveFile> {
  const fields = new URLSearchParams({
    fields: "id,name,mimeType,webViewLink,createdTime",
  });
  return driveJson<DriveFile>(
    connectors,
    `/drive/v3/files?${fields.toString()}`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name,
        mimeType: FOLDER_MIME,
        ...(parentId ? { parents: [parentId] } : {}),
      }),
    },
  );
}

async function ensureFolder(
  connectors: ReplitConnectors,
  name: string,
  parentId: string | null,
): Promise<DriveFile> {
  const existing = await listFolders(connectors, parentId, name);
  return existing[0] ?? createFolder(connectors, name, parentId);
}

async function listFilesInFolder(
  connectors: ReplitConnectors,
  parentId: string,
): Promise<DriveFile[]> {
  const query = new URLSearchParams({
    q: `trashed = false and '${escapeDriveQuery(parentId)}' in parents`,
    pageSize: "100",
    orderBy: "createdTime desc",
    fields: "files(id,name,mimeType,webViewLink,createdTime)",
  });
  const response = await driveJson<DriveList>(
    connectors,
    `/drive/v3/files?${query.toString()}`,
    { method: "GET" },
  );
  return response.files ?? [];
}

async function getVersionsFolder(connectors: ReplitConnectors): Promise<DriveFile> {
  const root = await ensureFolder(connectors, ROOT_FOLDER, null);
  const project = await ensureFolder(connectors, PROJECT_FOLDER, root.id);
  return ensureFolder(connectors, VERSIONS_FOLDER, project.id);
}

async function collectSourceFiles(rootPath: string): Promise<Record<string, string>> {
  const files: Record<string, string> = {};
  let totalBytes = 0;

  async function walk(path: string): Promise<void> {
    const entries = await readdir(path, { withFileTypes: true });
    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      if (entry.name === "node_modules" || entry.name === "dist" || entry.name.startsWith(".")) {
        continue;
      }
      const absolutePath = resolve(path, entry.name);
      if (entry.isDirectory()) {
        await walk(absolutePath);
        continue;
      }
      if (
        !entry.isFile() ||
        (!SAFE_EXTENSIONS.has(extname(entry.name).toLowerCase()) && entry.name !== "Dockerfile")
      ) continue;
      const body = await readFile(absolutePath);
      totalBytes += body.byteLength;
      if (totalBytes > MAX_SNAPSHOT_BYTES) {
        throw new Error("Source snapshot exceeds the 3 MiB safety limit.");
      }
      const relativePath = relative(rootPath, absolutePath).split("\\").join("/");
      files[relativePath] = body.toString("utf8");
    }
  }

  for (const sourceRoot of SOURCE_ROOTS) {
    const absoluteRoot = resolve(rootPath, sourceRoot);
    try {
      await walk(absoluteRoot);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") {
        throw new Error(`Required source directory is unavailable: ${sourceRoot}`);
      }
      throw error;
    }
  }
  for (const filePath of ROOT_FILES) {
    const absolutePath = resolve(rootPath, filePath);
    const body = await readFile(absolutePath);
    totalBytes += body.byteLength;
    if (totalBytes > MAX_SNAPSHOT_BYTES) {
      throw new Error("Source snapshot exceeds the 3 MiB safety limit.");
    }
    files[filePath] = body.toString("utf8");
  }
  return files;
}

async function nextVersion(connectors: ReplitConnectors, parentId: string): Promise<string> {
  const entries = await listFolders(connectors, parentId);
  const latest = entries.reduce((maximum, entry) => {
    const match = /^v(\d+)-/.exec(entry.name);
    return match ? Math.max(maximum, Number(match[1])) : maximum;
  }, 0);
  return `v${String(latest + 1).padStart(3, "0")}`;
}

async function uploadSnapshot(
  connectors: ReplitConnectors,
  parentId: string,
  fileName: string,
  body: string,
): Promise<DriveFile> {
  const boundary = `replit-${randomUUID()}`;
  const metadata = {
    name: fileName,
    mimeType: "application/json",
    parents: [parentId],
  };
  const multipartBody = [
    `--${boundary}`,
    "Content-Type: application/json; charset=UTF-8",
    "",
    JSON.stringify(metadata),
    `--${boundary}`,
    "Content-Type: application/json; charset=UTF-8",
    "",
    body,
    `--${boundary}--`,
    "",
  ].join("\r\n");
  const fields = new URLSearchParams({
    uploadType: "multipart",
    fields: "id,name,mimeType,webViewLink,createdTime",
  });
  return driveJson<DriveFile>(
    connectors,
    `/upload/drive/v3/files?${fields.toString()}`,
    {
      method: "POST",
      headers: { "content-type": `multipart/related; boundary=${boundary}` },
      body: multipartBody,
    },
  );
}

function compressedBundle(value: unknown): string {
  return gzipSync(Buffer.from(JSON.stringify(value), "utf8")).toString("base64");
}

function bundleParts(name: string, content: string) {
  const chunkSize = 20_000;
  const count = Math.max(1, Math.ceil(content.length / chunkSize));
  return Array.from({ length: count }, (_, index) => ({
    name: `${name}-${String(index + 1).padStart(3, "0")}.json`,
    body: JSON.stringify({
      encoding: "gzip+base64",
      part: index + 1,
      parts: count,
      content: content.slice(index * chunkSize, (index + 1) * chunkSize),
    }),
  }));
}

async function removeNewFolder(connectors: ReplitConnectors, folderId: string): Promise<void> {
  await connectors
    .proxy("google-drive", `/drive/v3/files/${encodeURIComponent(folderId)}`, {
      method: "DELETE",
    })
    .catch(() => undefined);
}

export async function listDriveSnapshots() {
  const connectors = new ReplitConnectors();
  const versionsFolder = await getVersionsFolder(connectors);
  const folders = await listFolders(connectors, versionsFolder.id);
  return folders
    .filter((folder) => /^v\d+-/.test(folder.name))
    .map((folder) => ({
      id: folder.id,
      name: folder.name,
      version: folder.name.split("-")[0] ?? folder.name,
      webViewLink:
        folder.webViewLink ??
        `https://drive.google.com/drive/folders/${encodeURIComponent(folder.id)}`,
      createdAt: folder.createdTime ?? new Date().toISOString(),
    }));
}

export async function createDriveSnapshot(state: {
  settings: unknown;
  positions: unknown[];
  activities: unknown[];
  backtests: unknown[];
  training: unknown;
}) {
  const operation = async () => {
    const connectors = new ReplitConnectors();
    const versionsFolder = await getVersionsFolder(connectors);
    const version = await nextVersion(connectors, versionsFolder.id);
    const createdAt = new Date();
    const dateTag = createdAt.toISOString().replace(/[:.]/g, "-");
    const workspaceRoot = resolve(process.env.WORKSPACE_ROOT ?? resolve(process.cwd(), "../.."));
    const sourceFiles = await collectSourceFiles(workspaceRoot);
    const manifest = {
      version,
      createdAt: createdAt.toISOString(),
      dataPolicy: "No environment variables, secrets, chat messages, or attached assets are included.",
      sourceFileCount: Object.keys(sourceFiles).length,
      sourceFilePaths: Object.keys(sourceFiles),
      bundles: {
        source: "source-*.json",
        operationalState: "state-*.json",
        encoding: "gzip+base64; concatenate each bundle's parts in order, base64-decode, then gunzip",
      },
    };
    const uploads = [
      {
        name: "manifest.json",
        body: JSON.stringify({
          ...manifest,
          operationalState: "Stored in the state-*.json bundle.",
        }),
      },
      ...bundleParts("source", compressedBundle({ files: sourceFiles })),
      ...bundleParts("state", compressedBundle(state)),
    ];
    const versionFolder = await createFolder(
      connectors,
      `${version}-${dateTag}`,
      versionsFolder.id,
    );
    try {
      for (let index = 0; index < uploads.length; index += 4) {
        const batch = uploads.slice(index, index + 4);
        await Promise.all(
          batch.map((file) =>
            uploadSnapshot(connectors, versionFolder.id, file.name, file.body),
          ),
        );
      }
    } catch (error) {
      await removeNewFolder(connectors, versionFolder.id);
      throw error;
    }
    return {
      id: versionFolder.id,
      name: versionFolder.name,
      version,
      webViewLink:
        versionFolder.webViewLink ??
        `https://drive.google.com/drive/folders/${encodeURIComponent(versionFolder.id)}`,
      createdAt: createdAt.toISOString(),
    };
  };

  const result = backupQueue.then(operation, operation);
  backupQueue = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}
