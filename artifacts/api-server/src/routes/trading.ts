import { randomUUID } from "node:crypto";
import { Router, type IRouter } from "express";
import {
  CreateTradingBackupResponse,
  CreateBacktestBody,
  GetBacktestsResponse,
  GetConnectorStatusResponse,
  GetCompanyFundamentalsQueryParams,
  GetCompanyFundamentalsResponse,
  GetEconomicDataResponse,
  GetLiveMarketQueryParams,
  GetLiveMarketResponse,
  GetLiveReadinessResponse,
  GetTradingBackupsResponse,
  GetTradingActivitiesResponse,
  GetTradingDashboardResponse,
  GetTradingInstrumentsQueryParams,
  GetTradingInstrumentsResponse,
  GetTradingPositionsResponse,
  GetTradingSettingsResponse,
  GetTrainingStatusResponse,
  SendAssistantMessageBody,
  SendAssistantMessageResponse,
  StartRetrainingBody,
  UpdateTradingSettingsBody,
  UpdateTradingSettingsResponse,
} from "@workspace/api-zod";
import { createDriveSnapshot, listDriveSnapshots } from "../lib/drive-snapshots";
import { capitalReadOnlyClient } from "../lib/capital-client";

const router: IRouter = Router();

const liveQuoteCache = new Map<
  string,
  { expiresAt: number; quote: ReturnType<typeof GetLiveMarketResponse.parse>["quotes"][number] }
>();
type EconomicIndicator = ReturnType<typeof GetEconomicDataResponse.parse>["indicators"][number];
type CompanyFundamental =
  ReturnType<typeof GetCompanyFundamentalsResponse.parse>["fundamentals"][number];
const economicIndicatorCache = new Map<
  string,
  { expiresAt: number; indicator: EconomicIndicator }
>();
const companyFundamentalCache = new Map<
  string,
  { expiresAt: number; fundamental: CompanyFundamental | null; error: string | null }
>();

const fredSeries = [
  { seriesId: "CPIAUCSL", label: "مؤشر أسعار المستهلكين", unit: "مؤشر، غير معدل موسمياً", freshnessDays: 75 },
  { seriesId: "UNRATE", label: "معدل البطالة", unit: "%", freshnessDays: 60 },
  { seriesId: "FEDFUNDS", label: "سعر الفائدة الفيدرالي الفعلي", unit: "%", freshnessDays: 45 },
  { seriesId: "GDP", label: "الناتج المحلي الإجمالي", unit: "مليار دولار، معدل سنوياً", freshnessDays: 150 },
] as const;

const fundamentalSymbols = ["AAPL", "NVDA", "TSLA", "MSFT"] as const;

function nullableNumber(value: unknown): number | null {
  if (typeof value !== "number" && (typeof value !== "string" || value.trim() === "")) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function nullableString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function dateOnly(value: unknown): Date | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const date = new Date(`${value}T00:00:00.000Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function recordFromProvider(payload: unknown): Record<string, unknown> | null {
  const candidate = Array.isArray(payload) ? payload[0] : payload;
  return candidate && typeof candidate === "object" && !Array.isArray(candidate)
    ? candidate as Record<string, unknown>
    : null;
}

async function requestProviderJson(
  url: URL,
): Promise<{ ok: boolean; status: number | null; payload: unknown }> {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(7_000) });
    if (!response.ok) return { ok: false, status: response.status, payload: null };
    return { ok: true, status: response.status, payload: await response.json() };
  } catch {
    return { ok: false, status: null, payload: null };
  }
}

function providerFreshness(
  asOf: Date | null,
  checkedAt: Date,
  freshnessDays: number,
): "fresh" | "delayed" | "stale" | "unknown" {
  if (!asOf) return "unknown";
  const ageDays = Math.max(0, checkedAt.getTime() - asOf.getTime()) / 86_400_000;
  if (ageDays <= freshnessDays) return "fresh";
  return ageDays <= freshnessDays * 2 ? "delayed" : "stale";
}

type Settings = ReturnType<typeof GetTradingSettingsResponse.parse>;
type Activity = ReturnType<typeof GetTradingActivitiesResponse.parse>[number];
type Backtest = ReturnType<typeof GetBacktestsResponse.parse>[number];
type TrainingStatus = ReturnType<typeof GetTrainingStatusResponse.parse>;

let settings: Settings = {
  mode: "live_locked",
  startingBalance: 0,
  maxRiskPerTradePct: 0.5,
  dailyCircuitBreakerPct: 3,
  maxDrawdownPct: 6,
  maxConcurrentPositions: 4,
  maxOpenSymbols: 2,
  cooldownAfterLosses: 2,
  useMarketShields: true,
  useMacroNewsFilter: false,
  allowAutoRetraining: false,
  liveTradingEnabled: false,
};

const activities: Activity[] = [];

const backtests: Backtest[] = [];
type LocalModelMessage = {
  role: "system" | "user" | "assistant" | "tool";
  content: string | null;
  name?: string;
  tool_call_id?: string;
  tool_calls?: Array<{
    id: string;
    type: "function";
    function: { name: string; arguments: string };
  }>;
};
const chatHistory = new Map<string, Array<{ role: "user" | "assistant"; content: string }>>();

let training: TrainingStatus = {
  status: "blocked",
  stage: "لا توجد أوزان مدرّبة معتمدة أو نتائج تقييم حقيقية بعد",
  progress: 0,
  currentVersion: "لا توجد نسخة معتمدة",
  candidateVersion: null,
  lastStartedAt: null,
  lastCompletedAt: null,
  shadowMinutes: 30,
  challengerMetrics: null,
  championMetrics: null,
  guardrails: [
    "لا توجد أوزان مشروع مدرّبة ومراجعة؛ المحادثة تتوقف بدلاً من استخدام نموذج بديل.",
    "لا تعرض المنصة مقاييس تدريب أو أداء حتى تتوفر نتائج تقييم حقيقية قابلة للمراجعة.",
    "التداول وإرسال أوامر الوسيط غير متاحين في هذا الإصدار.",
  ],
  history: [],
};

function addActivity(title: string, detail: string, severity: Activity["severity"], type = "system") {
  activities.unshift({
    id: randomUUID(),
    type,
    title,
    detail,
    createdAt: new Date(),
    severity,
  });
  if (activities.length > 60) activities.length = 60;
}

router.get("/trading/dashboard", async (_req, res): Promise<void> => {
  const account = await capitalReadOnlyClient.getAccountSnapshot();
  const result = GetTradingDashboardResponse.parse({
    equity: account.balance,
    dailyPnl: account.profitLoss,
    dailyPnlPct: null,
    openPositions: account.positions.length,
    winRate: null,
    maxDrawdown: null,
    dailyLossLimitPct: null,
    trackedSymbols: null,
    modelVersion: training.currentVersion,
    trainingProgress: null,
    tradingMode: "read_only",
    liveTradingEnabled: false,
    dataSource: account.state === "connected"
      ? account.environment === "demo" ? "capital_demo" : "capital_live"
      : "unavailable",
    systemHealth: account.state === "connected" ? "healthy" : "attention",
    riskState: "guarded",
    updatedAt: account.checkedAt,
  });
  res.json(result);
});

router.get("/trading/instruments", (req, res) => {
  const parsed = GetTradingInstrumentsQueryParams.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: "مرشحات الرموز غير صالحة." });
    return;
  }
  res.json(GetTradingInstrumentsResponse.parse([]));
});

router.get("/trading/positions", async (_req, res): Promise<void> => {
  const account = await capitalReadOnlyClient.getAccountSnapshot();
  const rows = account.positions.map((position) => ({
    id: position.id,
    symbol: position.epic,
    side: position.direction,
    entryPrice: position.entryPrice,
    currentPrice: position.currentPrice,
    size: position.size,
    leverage: null,
    pnl: position.profitLoss,
    stopLoss: null,
    takeProfit: null,
    openedAt: position.openedAt,
    status: "open" as const,
    mode: account.environment === "demo" ? "demo" as const : "live" as const,
  }));
  res.json(GetTradingPositionsResponse.parse(rows));
});

router.post("/trading/positions/:positionId/close", (_req, res) => {
  res.status(410).json({ error: "هذا الإصدار للقراءة فقط؛ لا يمكن إغلاق أو تعديل مراكز الوسيط." });
});

router.get("/trading/activities", (_req, res) => {
  res.json(GetTradingActivitiesResponse.parse(activities));
});

router.get("/trading/settings", (_req, res) => {
  res.json(GetTradingSettingsResponse.parse(settings));
});

router.patch("/trading/settings", (req, res) => {
  const parsed = UpdateTradingSettingsBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "إعداد مخاطرة غير صالح.", issues: parsed.error.issues });
    return;
  }
  settings = { ...settings, ...parsed.data, mode: "live_locked", liveTradingEnabled: false };
  addActivity("تم تحديث الضوابط", "حُفظت إعدادات المخاطر محلياً؛ لا تفعّل أي أوامر وسيط.", "success", "settings");
  res.json(UpdateTradingSettingsResponse.parse(settings));
});

router.get("/trading/live-readiness", async (_req, res): Promise<void> => {
  const account = await capitalReadOnlyClient.getAccountSnapshot();
  const blockers = [
    "إرسال أوامر الوسيط معطل عن قصد؛ هذا الإصدار للقراءة فقط.",
    "خطة Hugging Face ZeroGPU المجانية لا توفر خدمة دائمة أو جلسة تداول مستمرة.",
  ];
  if (account.state !== "connected") blockers.push(account.detail);
  res.json(
    GetLiveReadinessResponse.parse({
      ready: false,
      liveTradingEnabled: false,
      mode: "live_locked",
      blockers,
    }),
  );
});

router.post("/trading/simulations", (_req, res) => {
  res.status(410).json({ error: "المحاكاة معطلة في هذا الإصدار؛ بيانات الوسيط للقراءة فقط." });
});

router.get("/trading/training", (_req, res) => {
  res.json(GetTrainingStatusResponse.parse(training));
});

router.post("/trading/training/retrain", (req, res) => {
  const parsed = StartRetrainingBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "إعدادات التدريب غير صالحة.", issues: parsed.error.issues });
    return;
  }
  res.status(501).json({
    error: "التدريب من هذه الواجهة غير متاح. لا يُنشأ مرشح أو مقياس إلا بعد تشغيل تدريب حقيقي وتقييمه.",
  });
});

router.get("/trading/backtests", (_req, res) => {
  res.json(GetBacktestsResponse.parse(backtests));
});

router.post("/trading/backtests", (req, res) => {
  const parsed = CreateBacktestBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "إعدادات الاختبار التاريخي غير صالحة.", issues: parsed.error.issues });
    return;
  }
  res.status(501).json({
    error: "الاختبار التاريخي معطل حتى تُربط سلسلة أسعار تاريخية حقيقية وتُتحقق جودتها.",
  });
});

router.get("/trading/connectors", async (_req, res): Promise<void> => {
  const capitalSnapshot = await capitalReadOnlyClient.getAccountSnapshot();
  const modelUrl = process.env.LOCAL_MODEL_URL?.trim();
  const modelApiToken = process.env.LOCAL_MODEL_API_TOKEN;
  const hfSpaceToken = process.env.LOCAL_MODEL_HF_TOKEN;
  let localModelState: "connected" | "not_configured" | "blocked" = "not_configured";
  let localModelDetail =
    "يلزم ضبط LOCAL_MODEL_URL وLOCAL_MODEL_API_TOKEN وLOCAL_MODEL_HF_TOKEN؛ لن يُستخدم النموذج الأساسي أو بديل سحابي.";

  if (modelUrl && modelApiToken && hfSpaceToken) {
    try {
      const healthUrl = new URL(`${modelUrl.replace(/\/+$/, "")}/health`);
      if (
        healthUrl.protocol !== "https:" ||
        healthUrl.username ||
        healthUrl.password ||
        healthUrl.search ||
        healthUrl.hash
      ) {
        throw new Error("invalid_space_url");
      }

      const response = await fetch(healthUrl, {
        headers: {
          authorization: `Bearer ${hfSpaceToken}`,
          "x-space-api-token": modelApiToken,
        },
        signal: AbortSignal.timeout(5_000),
        redirect: "manual",
      });

      if (response.status === 401 || response.status === 403) {
        localModelState = "blocked";
        localModelDetail =
          "رفض Space الخاص بيانات الوصول أو الصلاحيات؛ تحقق من رمزي HF وSpace API وصلاحية قراءة الـSpace.";
      } else if (!response.ok) {
        localModelState = "blocked";
        localModelDetail = `تعذر الوصول إلى فحص Space (HTTP ${response.status})؛ تحقق من عنوان Space وأن الخدمة تعمل.`;
      } else {
        const health = (await response.json()) as { ready?: unknown };
        if (health.ready === true) {
          localModelState = "connected";
          localModelDetail = `تم التحقق من جاهزية نموذج المشروع في Space الخاص (${process.env.LOCAL_MODEL_ID ?? "غير محدد"}).`;
        } else {
          localModelState = "blocked";
          localModelDetail =
            "Space يستجيب، لكن نسخة نموذج المشروع غير جاهزة أو لم تجتز التقييم المطلوب.";
        }
      }
    } catch (error) {
      localModelState = "blocked";
      if (error instanceof Error && error.message === "invalid_space_url") {
        localModelDetail = "عنوان Space غير صالح؛ يلزم عنوان HTTPS صالح من دون بيانات اعتماد مضمنة.";
      } else if (error instanceof Error && error.name === "TimeoutError") {
        localModelDetail = "انتهت مهلة الاتصال بـSpace الخاص؛ تحقق من عنوان Space وأنه مستيقظ.";
      } else {
        localModelDetail = "تعذر الاتصال بـSpace الخاص أو قراءة استجابته؛ تحقق من العنوان وإتاحته.";
      }
    }
  }

  const capitalState =
    capitalSnapshot.state === "connected"
      ? "connected"
      : capitalSnapshot.state === "not_configured"
        ? "needs_credentials"
        : "blocked";
  const telegramReady = Boolean(
    process.env.TELEGRAM_BOT_TOKEN && process.env.TELEGRAM_CHAT_ID,
  );
  const marketQuotesReady = Boolean(process.env.FINNHUB_API_KEY);
  const macroNewsReady = Boolean(process.env.FRED_API_KEY && process.env.FMP_API_KEY);
  const rows = [
    {
      id: "local-model",
      name: "نموذج مرصاد المدرّب",
      state: localModelState,
      detail: localModelDetail,
      requiredForLive: true,
    },
    {
      id: "capital",
      name: "Capital.com",
      state: capitalState,
      detail: capitalSnapshot.detail,
      requiredForLive: true,
    },
    {
      id: "telegram",
      name: "Telegram",
      state: telegramReady ? "blocked" : "needs_credentials",
      detail: telegramReady
        ? "الإعداد موجود، لكن الاتصال وصلاحية الوجهة لم يُختبرا؛ لم يُرسل أي اختبار."
        : "يتطلب بيانات جديدة في الأسرار؛ لم يُرسل أي اختبار أو إشعار.",
      requiredForLive: true,
    },
    {
      id: "market-quotes",
      name: "أسعار السوق — Finnhub",
      state: marketQuotesReady ? "blocked" : "needs_credentials",
      detail: marketQuotesReady
        ? "المفتاح موجود؛ لا يُعد المصدر متصلاً حتى ينجح طلب سوق فعلي."
        : "يتطلب FINNHUB_API_KEY. لا تعرض واجهة الذكاء أسعاراً بديلة عند غياب المصدر.",
      requiredForLive: false,
    },
    {
      id: "macro-news",
      name: "مصادر الاقتصاد والأخبار",
      state: macroNewsReady ? "blocked" : "needs_credentials",
      detail: macroNewsReady
        ? "المفاتيح موجودة، لكن لم يُنفذ فحص حديث؛ لا تُعرض بيانات الاقتصاد على أنها حية."
        : "يتطلب FRED_API_KEY وFMP_API_KEY؛ لا تُعرض أحداث أو أخبار على أنها حية قبل التحقق.",
      requiredForLive: true,
    },
    {
      id: "google-drive",
      name: "Google Drive",
      state: "not_configured",
      detail: "الموصل متاح في مساحة العمل، لكن واجهة التطبيق لم تختبر أو تستخدم اتصال Drive.",
      requiredForLive: false,
    },
    {
      id: "mcp",
      name: "موصلات MCP",
      state: "not_configured",
      detail: "أدوات MCP المتاحة للوكيل في مساحة العمل ليست اتصالاً داخل التطبيق المنشور؛ لم يُسجل موصل MCP للتطبيق.",
      requiredForLive: false,
    },
  ];
  res.json(GetConnectorStatusResponse.parse(rows));
});

router.get("/trading/live-market", async (req, res): Promise<void> => {
  const parsed = GetLiveMarketQueryParams.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: "قائمة رموز السوق غير صالحة." });
    return;
  }

  const rawSymbols = parsed.data.symbols?.trim();
  const symbols = rawSymbols
    ? [...new Set(rawSymbols.split(",").map((symbol) => symbol.trim().toUpperCase()))]
    : ["AAPL", "NVDA", "TSLA", "SPY"];
  if (
    symbols.length > 8 ||
    symbols.some((symbol) => !/^[A-Z0-9.^-]{1,15}$/.test(symbol))
  ) {
    res.status(400).json({
      error: "يسمح بثمانية رموز كحد أقصى، وبأحرف وأرقام ورموز السوق فقط.",
    });
    return;
  }

  const checkedAt = new Date();
  const apiKey = process.env.FINNHUB_API_KEY;
  if (!apiKey) {
    res.json(
      GetLiveMarketResponse.parse({
        state: "not_configured",
        provider: null,
        configured: false,
        quotes: [],
        errors: ["أضف FINNHUB_API_KEY إلى أسرار Replit لطلب الأسعار من المصدر."],
        checkedAt,
        sourceNote:
          "لا توجد أسعار بديلة أو تركيبية في هذه الصفحة. هذا المصدر لا يمثل أسعار CFDs لدى Capital.com.",
      }),
    );
    return;
  }

  const errors: string[] = [];
  const quotes = await Promise.all(
    symbols.map(async (symbol) => {
      const cached = liveQuoteCache.get(symbol);
      if (cached && cached.expiresAt > Date.now()) return cached.quote;

      try {
        const url = new URL("https://finnhub.io/api/v1/quote");
        url.searchParams.set("symbol", symbol);
        url.searchParams.set("token", apiKey);
        const response = await fetch(url, { signal: AbortSignal.timeout(8_000) });
        if (!response.ok) throw new Error(`provider_http_${response.status}`);
        const payload: unknown = await response.json();
        if (!payload || typeof payload !== "object") throw new Error("invalid_payload");

        const record = payload as Record<string, unknown>;
        const price = Number(record["c"]);
        const providerSeconds = Number(record["t"]);
        if (
          !Number.isFinite(price) ||
          price <= 0 ||
          !Number.isFinite(providerSeconds) ||
          providerSeconds <= 0
        ) {
          throw new Error("quote_unavailable");
        }

        const timestamp = new Date(providerSeconds * 1000);
        const ageMs = Math.max(0, checkedAt.getTime() - timestamp.getTime());
        const freshness =
          ageMs <= 90_000 ? "fresh" : ageMs <= 15 * 60_000 ? "delayed" : "stale";
        const quote: ReturnType<typeof GetLiveMarketResponse.parse>["quotes"][number] = {
          symbol,
          price,
          change: Number.isFinite(Number(record["d"])) ? Number(record["d"]) : null,
          changePct: Number.isFinite(Number(record["dp"])) ? Number(record["dp"]) : null,
          timestamp,
          freshness,
        };
        liveQuoteCache.set(symbol, { quote, expiresAt: Date.now() + 20_000 });
        return quote;
      } catch {
        errors.push(`${symbol}: تعذر الحصول على تسعيرة صالحة من Finnhub.`);
        return null;
      }
    }),
  );
  const validQuotes = quotes.filter((quote) => quote !== null);
  if (errors.length) {
    req.log.warn(
      { provider: "finnhub", failedSymbols: errors.length, requestedSymbols: symbols.length },
      "Live market quote request was partially or fully unavailable",
    );
  }
  res.json(
    GetLiveMarketResponse.parse({
      state: validQuotes.length ? "connected" : "unavailable",
      provider: "Finnhub",
      configured: true,
      quotes: validQuotes,
      errors,
      checkedAt,
      sourceNote:
        "وقت السعر من مزود البيانات؛ قد تختلف الإتاحة والسرعة حسب خطة Finnhub. الأسعار ليست تسعيرة CFD من Capital.com.",
    }),
  );
});

router.get("/trading/economic-data", async (req, res): Promise<void> => {
  const checkedAt = new Date();
  const apiKey = process.env.FRED_API_KEY?.trim();
  if (!apiKey) {
    const indicators = fredSeries.map((series) => ({
      seriesId: series.seriesId,
      label: series.label,
      value: null,
      unit: series.unit,
      observationDate: null,
      source: "FRED" as const,
      retrievedAt: checkedAt,
      freshness: "unavailable" as const,
      error: "يتطلب FRED_API_KEY.",
    }));
    res.json(GetEconomicDataResponse.parse({
      state: "not_configured",
      provider: "FRED",
      configured: false,
      indicators,
      errors: ["مصدر FRED غير مضبوط؛ لم تُعرض قيم بديلة."],
      checkedAt,
      sourceNote: "المصدر: Federal Reserve Bank of St. Louis (FRED).",
    }));
    return;
  }

  let rateLimited = false;
  let requestFailed = false;
  const indicators = await Promise.all(fredSeries.map(async (series) => {
    const cached = economicIndicatorCache.get(series.seriesId);
    if (cached && cached.expiresAt > Date.now()) return cached.indicator;

    const retrievedAt = new Date();
    let indicator: EconomicIndicator;
    try {
      const url = new URL("https://api.stlouisfed.org/fred/series/observations");
      url.searchParams.set("series_id", series.seriesId);
      url.searchParams.set("api_key", apiKey);
      url.searchParams.set("file_type", "json");
      url.searchParams.set("sort_order", "desc");
      url.searchParams.set("limit", "1");
      const response = await fetch(url, { signal: AbortSignal.timeout(7_000) });
      if (!response.ok) {
        if (response.status === 429) rateLimited = true;
        requestFailed = true;
        indicator = {
          seriesId: series.seriesId,
          label: series.label,
          value: null,
          unit: series.unit,
          observationDate: null,
          source: "FRED",
          retrievedAt,
          freshness: "unavailable",
          error: response.status === 429
            ? "بلغ مصدر FRED حد الطلبات؛ أعد المحاولة لاحقاً."
            : "تعذر جلب هذا المؤشر من FRED.",
        };
      } else {
        const payload: unknown = await response.json();
        const observations = payload && typeof payload === "object"
          ? (payload as Record<string, unknown>)["observations"]
          : null;
        const observation = Array.isArray(observations)
          ? recordFromProvider(observations)
          : null;
        const value = nullableNumber(observation?.["value"]);
        const observationDate = dateOnly(observation?.["date"]);
        if (value == null || !observationDate) {
          requestFailed = true;
          indicator = {
            seriesId: series.seriesId,
            label: series.label,
            value: null,
            unit: series.unit,
            observationDate: null,
            source: "FRED",
            retrievedAt,
            freshness: "unavailable",
            error: "لا يتوفر رصد حديث صالح لهذا المؤشر من FRED.",
          };
        } else {
          const ageDays = Math.max(0, checkedAt.getTime() - observationDate.getTime()) / 86_400_000;
          indicator = {
            seriesId: series.seriesId,
            label: series.label,
            value,
            unit: series.unit,
            observationDate,
            source: "FRED",
            retrievedAt,
            freshness: ageDays <= series.freshnessDays
              ? "fresh"
              : ageDays <= series.freshnessDays * 2
                ? "delayed"
                : "stale",
            error: null,
          };
        }
      }
    } catch {
      requestFailed = true;
      indicator = {
        seriesId: series.seriesId,
        label: series.label,
        value: null,
        unit: series.unit,
        observationDate: null,
        source: "FRED",
        retrievedAt,
        freshness: "unavailable",
        error: "تعذر الاتصال بمصدر FRED.",
      };
    }
    economicIndicatorCache.set(series.seriesId, {
      indicator,
      expiresAt: Date.now() + (indicator.error ? 30_000 : 5 * 60_000),
    });
    return indicator;
  }));

  const errors = indicators
    .filter((indicator) => indicator.error)
    .map((indicator) => `${indicator.label}: ${indicator.error}`);
  if (requestFailed) {
    req.log.warn(
      { provider: "fred", rateLimited, failedIndicators: errors.length },
      "Economic indicator request was partially or fully unavailable",
    );
  }
  const availableCount = indicators.filter((indicator) => indicator.value != null).length;
  res.json(GetEconomicDataResponse.parse({
    state: availableCount === 0 ? "unavailable" : errors.length ? "partial" : "connected",
    provider: "FRED",
    configured: true,
    indicators,
    errors,
    checkedAt,
    sourceNote: "المصدر: Federal Reserve Bank of St. Louis (FRED). حداثة كل مؤشر محسوبة من تاريخ الرصد المنشور.",
  }));
});

router.get("/trading/fundamentals", async (req, res): Promise<void> => {
  const parsed = GetCompanyFundamentalsQueryParams.safeParse(req.query);
  if (!parsed.success) {
    res.status(400).json({ error: "قائمة رموز الشركات غير صالحة." });
    return;
  }
  const symbols = parsed.data.symbols?.trim()
    ? [...new Set(parsed.data.symbols.split(",").map((symbol) => symbol.trim().toUpperCase()))]
    : [...fundamentalSymbols];
  if (
    symbols.length > 4 ||
    symbols.some((symbol) => !/^[A-Z][A-Z0-9.-]{0,9}$/.test(symbol))
  ) {
    res.status(400).json({ error: "يسمح بأربعة رموز أسهم كحد أقصى، وبصيغة رمز صالحة فقط." });
    return;
  }

  const checkedAt = new Date();
  const apiKey = process.env.FMP_API_KEY?.trim();
  if (!apiKey) {
    res.json(GetCompanyFundamentalsResponse.parse({
      state: "not_configured",
      provider: "FMP",
      configured: false,
      fundamentals: [],
      errors: ["مصدر FMP غير مضبوط؛ أضف FMP_API_KEY لعرض بيانات الشركات."],
      checkedAt,
      sourceNote: "المصدر: Financial Modeling Prep (FMP). لا تُستخدم قيم بديلة.",
    }));
    return;
  }

  const cachedResults = await Promise.all(symbols.map(async (symbol) => {
    const cached = companyFundamentalCache.get(symbol);
    if (cached && cached.expiresAt > Date.now()) return cached;

    const retrievedAt = new Date();
    const profileUrl = new URL("https://financialmodelingprep.com/stable/profile");
    profileUrl.searchParams.set("symbol", symbol);
    profileUrl.searchParams.set("apikey", apiKey);
    const metricsUrl = new URL("https://financialmodelingprep.com/stable/key-metrics");
    metricsUrl.searchParams.set("symbol", symbol);
    metricsUrl.searchParams.set("limit", "1");
    metricsUrl.searchParams.set("apikey", apiKey);

    const [profileResult, metricsResult] = await Promise.all([
      requestProviderJson(profileUrl),
      requestProviderJson(metricsUrl),
    ]);
    const profileStatus = profileResult.status;
    const metricsStatus = metricsResult.status;
    const profile = profileResult.ok ? recordFromProvider(profileResult.payload) : null;
    const metrics = metricsResult.ok ? recordFromProvider(metricsResult.payload) : null;

    const profileFailed = profileStatus === null || profileStatus >= 400 || profile === null;
    const metricsFailed = metricsStatus === null || metricsStatus >= 400 || metrics === null;
    const rateLimited = profileStatus === 429 || metricsStatus === 429;
    const profileOrMetrics = profile ?? metrics;
    let error: string | null = null;
    if (profileFailed || metricsFailed) {
      error = rateLimited
        ? "بلغ مصدر FMP حد الطلبات؛ أعد المحاولة لاحقاً."
        : `تعذر جلب بعض بيانات ${symbol} من FMP.`;
    }
    const asOf = dateOnly(metrics?.["date"]);
    const hasAnyData = profileOrMetrics !== null;
    const fundamental: CompanyFundamental | null = hasAnyData ? {
      symbol,
      companyName: nullableString(profile?.["companyName"] ?? profile?.["name"]),
      sector: nullableString(profile?.["sector"]),
      industry: nullableString(profile?.["industry"]),
      currency: nullableString(profile?.["currency"]),
      marketCap: nullableNumber(metrics?.["marketCap"] ?? profile?.["marketCap"]),
      peRatio: nullableNumber(metrics?.["peRatio"]),
      pbRatio: nullableNumber(metrics?.["pbRatio"]),
      priceToSalesRatio: nullableNumber(metrics?.["priceToSalesRatio"]),
      returnOnEquity: nullableNumber(metrics?.["returnOnEquity"]),
      asOf,
      source: "FMP",
      retrievedAt,
      freshness: providerFreshness(asOf, checkedAt, 150),
    } : null;
    const result = { fundamental, error };
    companyFundamentalCache.set(symbol, {
      ...result,
      expiresAt: Date.now() + (error ? 45_000 : 15 * 60_000),
    });
    return result;
  }));

  const fundamentals = cachedResults.flatMap((result) => result.fundamental ? [result.fundamental] : []);
  const errors = cachedResults.flatMap((result) => result.error ? [result.error] : []);
  if (errors.length) {
    req.log.warn(
      {
        provider: "fmp",
        failedSymbols: errors.length,
        rateLimited: errors.some((message) => message.includes("حد الطلبات")),
      },
      "Company fundamentals request was partially or fully unavailable",
    );
  }
  res.json(GetCompanyFundamentalsResponse.parse({
    state: fundamentals.length === 0
      ? "unavailable"
      : errors.length
        ? "partial"
        : "connected",
    provider: "FMP",
    configured: true,
    fundamentals,
    errors,
    checkedAt,
    sourceNote: "المصدر: Financial Modeling Prep (FMP). تاريخ الأساسيات يعكس تاريخ التقرير المنشور، لا وقت جلبه.",
  }));
});

router.get("/trading/backups", async (req, res) => {
  if (!process.env.REPLIT_DEV_DOMAIN && !process.env.REPL_ID) {
    res.status(503).json({ error: "يتطلب حفظ النسخ موصل Google Drive داخل بيئة Replit." });
    return;
  }
  try {
    const snapshots = await listDriveSnapshots();
    res.json(GetTradingBackupsResponse.parse(snapshots));
  } catch (error) {
    req.log.error({ err: error }, "Google Drive backup listing failed");
    res.status(503).json({ error: "تعذر الاتصال بمجلد النسخ في Google Drive." });
  }
});

router.post("/trading/backups", async (req, res) => {
  if (!process.env.REPLIT_DEV_DOMAIN && !process.env.REPL_ID) {
    res.status(503).json({ error: "يتطلب حفظ النسخ موصل Google Drive داخل بيئة Replit." });
    return;
  }
  try {
    const account = await capitalReadOnlyClient.getAccountSnapshot();
    const snapshot = await createDriveSnapshot({
      settings,
      positions: account.positions,
      activities,
      backtests,
      training,
    });
    addActivity(
      `تم حفظ نسخة ${snapshot.version} في Google Drive`,
      "تتضمن نسخة المصدر المسموح وبيانات الحالة التشغيلية، ولا تتضمن الأسرار أو المحادثات أو الملفات المرفقة.",
      "success",
      "backup",
    );
    res.status(201).json(CreateTradingBackupResponse.parse(snapshot));
  } catch (error) {
    req.log.error({ err: error }, "Google Drive backup creation failed");
    res.status(503).json({ error: "تعذر إنشاء نسخة Google Drive؛ لم تتغير بيانات النظام." });
  }
});

router.post("/assistant/chat", async (req, res) => {
  const parsed = SendAssistantMessageBody.safeParse(req.body);
  if (!parsed.success) {
    res.status(400).json({ error: "رسالة المحادثة غير صالحة.", issues: parsed.error.issues });
    return;
  }
  const baseUrl = process.env.LOCAL_MODEL_URL?.replace(/\/+$/, "");
  const modelApiToken = process.env.LOCAL_MODEL_API_TOKEN;
  const hfSpaceToken = process.env.LOCAL_MODEL_HF_TOKEN;
  if (!baseUrl || !modelApiToken || !hfSpaceToken) {
    res.json(
      SendAssistantMessageResponse.parse({
        reply: "نسخة مرصاد المدرّبة غير متصلة بعد. لم أستخدم النموذج الأساسي للرد أو أرسل رسالتك إلى خدمة محادثة خارجية.",
        source: "local_model_unavailable",
        suggestions: [
          "أنشئ نسخة مرشحة في Hugging Face Space الخاص ثم قيّمها قبل تفعيلها.",
          "اضبط عنوان Space ومعرف النسخة المدرّبة ورموز الوصول عبر الأسرار.",
          "تأكد من تفعيل الأدوات على وضع المحاكاة قبل ربط حساب تداول.",
        ],
      }),
    );
    return;
  }

  const conversationId = parsed.data.conversationId;
  const history = chatHistory.get(conversationId) ?? [];
  const account = await capitalReadOnlyClient.getAccountSnapshot();
  const dashboard = GetTradingDashboardResponse.parse({
    equity: account.balance,
    dailyPnl: account.profitLoss,
    dailyPnlPct: null,
    openPositions: account.positions.length,
    winRate: null,
    maxDrawdown: null,
    dailyLossLimitPct: null,
    trackedSymbols: null,
    modelVersion: training.currentVersion,
    trainingProgress: null,
    tradingMode: "read_only",
    liveTradingEnabled: false,
    dataSource: account.state === "connected"
      ? account.environment === "demo" ? "capital_demo" : "capital_live"
      : "unavailable",
    systemHealth: account.state === "connected" ? "healthy" : "attention",
    riskState: "guarded",
    updatedAt: account.checkedAt,
  });
  const systemMessage: LocalModelMessage = {
    role: "system",
    content: [
      "أنت العقل الحواري المحلي الوحيد لمنصة مرصاد/Unified Trading Intelligence.",
      "استخدم أدوات المنصة للحقائق الحالية. أدواتك للقراءة والتحليل فقط؛ لا توجد أداة تفتح صفقات أو تغيّر المخاطر.",
      "تحدث بالعربية الواضحة، اذكر مصدر البيانات ووقت التحقق، وصرّح عندما تكون البيانات غير متاحة. لا تخترع أسعاراً أو أرباحاً.",
      "التداول الحقيقي مقفل. لا تدّع أنك دربت النموذج أو أرسلت أمرًا أو قرأت خبرًا ما لم تؤكد أداة ذلك.",
      "لا توصي برافعة قصوى أو مخاطرة مفرطة. قدم شرحًا تعليميًا لا توصية استثمارية شخصية.",
      `سياق المستخدم: ${parsed.data.context ?? "general"}.`,
      `حالة لوحة النظام الحالية: ${JSON.stringify({
        dataSource: dashboard.dataSource,
        tradingMode: dashboard.tradingMode,
        liveTradingEnabled: dashboard.liveTradingEnabled,
        equity: dashboard.equity,
        dailyPnl: dashboard.dailyPnl,
        dailyPnlPct: dashboard.dailyPnlPct,
        openPositions: dashboard.openPositions,
        dailyLossLimitPct: dashboard.dailyLossLimitPct,
        modelVersion: dashboard.modelVersion,
         activePositions: account.positions,
         capitalConnection: {
           state: account.state,
           environment: account.environment,
           source: account.source,
           checkedAt: account.checkedAt,
           detail: account.detail,
         },
        riskSettings: settings,
        training: {
          status: training.status,
          currentVersion: training.currentVersion,
          candidateVersion: training.candidateVersion,
          stage: training.stage,
        },
      })}`,
    ].join("\n"),
  };
  const messages: LocalModelMessage[] = [
    systemMessage,
    ...history.map((message): LocalModelMessage => ({ ...message })),
    { role: "user", content: parsed.data.message },
  ];
  const tools = [
    {
      type: "function" as const,
      function: {
        name: "get_risk_status",
        description: "Read the connected Capital.com account state and live lock status without exposing full account identifiers.",
        parameters: { type: "object", properties: {}, additionalProperties: false },
      },
    },
    {
      type: "function" as const,
      function: {
        name: "search_capital_markets",
        description: "Search live market instruments from Capital.com. Returns unavailable state rather than synthetic quote data.",
        parameters: {
          type: "object",
          properties: {
            query: { type: "string" },
          },
          additionalProperties: false,
        },
      },
    },
    {
      type: "function" as const,
      function: {
        name: "get_recent_activities",
        description: "Read recent system activity and safety events.",
        parameters: { type: "object", properties: {}, additionalProperties: false },
      },
    },
  ];
  const runTool = async (name: string, args: Record<string, unknown>): Promise<unknown> => {
    if (name === "get_risk_status") {
      return {
        dataSource: dashboard.dataSource,
        accountState: account.state,
        environment: account.environment,
        source: account.source,
        checkedAt: account.checkedAt,
        detail: account.detail,
        tradingMode: "read_only",
        liveTradingEnabled: false,
        equity: dashboard.equity,
        dailyPnl: dashboard.dailyPnl,
        currency: account.currency,
        available: account.available,
        openPositions: account.positions,
        liveReadinessBlockers: [
          "هذا التطبيق مضبوط على القراءة فقط ولا يرسل أوامر الوسيط.",
          "لا توجد إحصاءات أداء أو تدريب معتمدة في هذه النسخة.",
        ],
      };
    }
    if (name === "search_capital_markets") {
      const query = typeof args.query === "string" ? args.query.toLowerCase().trim() : "";
      return capitalReadOnlyClient.searchMarkets(query);
    }
    if (name === "get_recent_activities") return activities.slice(0, 12);
    return { error: "أداة غير مسموح بها." };
  };

  try {
    let finalReply = "";
    for (let round = 0; round < 4; round += 1) {
      const modelResponse = await fetch(`${baseUrl}/v1/chat/completions`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${hfSpaceToken}`,
          "x-space-api-token": modelApiToken,
        },
        signal: AbortSignal.timeout(180_000),
        body: JSON.stringify({
          model: process.env.LOCAL_MODEL_ID ?? "unified-trading-model",
          max_tokens: 1200,
          temperature: 0.2,
          tools,
          tool_choice: "auto",
          messages,
        }),
      });
      if (!modelResponse.ok) {
        res.status(503).json(
          SendAssistantMessageResponse.parse({
            reply: "نسخة مرصاد المدرّبة غير متاحة حالياً. لم أستخدم النموذج الأساسي للرد أو أرسل رسالتك إلى خدمة محادثة خارجية.",
            source: "local_model_unavailable",
            suggestions: [
              "تحقق من رمزي الوصول إلى Space الخاص وصلاحية قراءة النموذج.",
              "تأكد من تحميل نسخة المشروع واجتيازها بوابة التقييم.",
            ],
          }),
        );
        return;
      }
      const payload = (await modelResponse.json()) as {
        choices?: Array<{
          message?: {
            content?: string | null;
            tool_calls?: LocalModelMessage["tool_calls"];
          };
        }>;
      };
      const modelMessage = payload.choices?.[0]?.message;
      if (!modelMessage) {
        res.status(502).json({ error: "لم تُرجع خدمة النموذج المحلي رسالة صالحة." });
        return;
      }
      if (modelMessage.tool_calls?.length) {
        messages.push({
          role: "assistant",
          content: modelMessage.content ?? null,
          tool_calls: modelMessage.tool_calls,
        });
        for (const call of modelMessage.tool_calls) {
          let toolResult: unknown;
          try {
            const args = JSON.parse(call.function.arguments || "{}") as Record<string, unknown>;
            toolResult = await runTool(call.function.name, args);
          } catch {
            toolResult = { error: "وسائط الأداة غير صالحة." };
          }
          messages.push({
            role: "tool",
            name: call.function.name,
            tool_call_id: call.id,
            content: JSON.stringify(toolResult),
          });
        }
        continue;
      }
      finalReply = modelMessage.content?.trim() ?? "";
      break;
    }
    if (!finalReply) {
      res.status(502).json({ error: "لم يُرجع النموذج المحلي إجابة نصية بعد استخدام الأدوات." });
      return;
    }
    const updatedHistory: Array<{ role: "user" | "assistant"; content: string }> = [
      ...history,
      { role: "user", content: parsed.data.message },
      { role: "assistant", content: finalReply },
    ];
    chatHistory.set(conversationId, updatedHistory.slice(-16));
    res.json(
      SendAssistantMessageResponse.parse({
        reply: finalReply,
        source: "local_model",
        suggestions: [],
      }),
    );
  } catch (error) {
    req.log.error({ err: error }, "Local model request failed");
    res.status(503).json({ error: "تعذر الوصول إلى خدمة النموذج المحلي." });
  }
});

export default router;
