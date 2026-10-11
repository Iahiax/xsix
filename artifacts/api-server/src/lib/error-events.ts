import type { RequestHandler } from "express";

const WINDOW_MS = 24 * 60 * 60 * 1_000;
const MAX_EVENTS = 100;
const MAX_VISIBLE_EVENTS = 20;

export type ApiErrorEvent = {
  id: string;
  occurredAt: Date;
  statusCode: number;
  method: string;
  path: string;
  requestId: string | null;
};

const events: ApiErrorEvent[] = [];
let eventSequence = 0;

function prune(now: number): void {
  while (events.length && now - events[0]!.occurredAt.getTime() > WINDOW_MS) {
    events.shift();
  }
}

function safeRequestPath(path: string): string {
  return path
    .split("?")[0]!
    .replace(/\/[0-9a-f]{8}-[0-9a-f-]{27,}/gi, "/:id")
    .replace(/\/\d+(?=\/|$)/g, "/:id")
    .replace(/\/[^/]{32,}/g, "/:segment")
    .slice(0, 180);
}

export function recordApiError(input: {
  statusCode: number;
  method: string;
  path: string;
  requestId?: string | number | null;
}): void {
  const now = Date.now();
  prune(now);
  events.push({
    id: `api-error-${++eventSequence}`,
    occurredAt: new Date(now),
    statusCode: Math.max(500, Math.min(599, Math.trunc(input.statusCode))),
    method: input.method.toUpperCase().slice(0, 10),
    path: safeRequestPath(input.path),
    requestId: input.requestId == null ? null : String(input.requestId).slice(0, 80),
  });
  while (events.length > MAX_EVENTS) events.shift();
}

export const captureApiErrors: RequestHandler = (req, res, next) => {
  res.once("finish", () => {
    if (res.statusCode < 500) return;
    const routePath = typeof req.route?.path === "string" ? req.route.path : req.path;
    const routePrefix = req.baseUrl || "";
    recordApiError({
      statusCode: res.statusCode,
      method: req.method,
      path: `${routePrefix}${routePath}`,
      requestId:
        typeof req.id === "string" || typeof req.id === "number" ? req.id : null,
    });
  });
  next();
};

export function getSystemDiagnostics() {
  const now = Date.now();
  prune(now);
  const recentErrors = events
    .slice(-MAX_VISIBLE_EVENTS)
    .reverse()
    .map((event) => ({ ...event }));
  return {
    state: events.length ? "attention" : "healthy",
    windowMinutes: WINDOW_MS / 60_000,
    errorCount: events.length,
    lastErrorAt: recentErrors[0]?.occurredAt ?? null,
    recentErrors,
    checkedAt: new Date(now),
    retentionNote:
      "أخطاء HTTP من فئة 5xx فقط؛ ذاكرة العملية الحالية، حتى 24 ساعة وبحد أقصى 100 حدث. لا تُحفظ الأجسام أو الأسرار.",
  };
}
