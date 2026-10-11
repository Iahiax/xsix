type CapitalMode = "live" | "demo";
type ConnectionState = "connected" | "not_configured" | "unavailable" | "unauthorized";

type CapitalPosition = {
  id: string;
  epic: string;
  name: string;
  direction: "buy" | "sell";
  size: number | null;
  entryPrice: number | null;
  currentPrice: number | null;
  profitLoss: number | null;
  currency: string | null;
  openedAt: string | null;
  marketStatus: string | null;
};

type CapitalAccountSnapshot = {
  state: ConnectionState;
  environment: CapitalMode | null;
  source: "Capital.com";
  checkedAt: string;
  detail: string;
  accountIdSuffix: string | null;
  currency: string | null;
  balance: number | null;
  available: number | null;
  deposit: number | null;
  profitLoss: number | null;
  positions: CapitalPosition[];
};

type CapitalMarket = {
  epic: string;
  name: string;
  instrumentType: string | null;
  marketStatus: string | null;
  bid: number | null;
  offer: number | null;
  change: number | null;
  changePct: number | null;
  currency: string | null;
  updatedAt: string | null;
};

type CapitalMarketsSnapshot = {
  state: ConnectionState;
  environment: CapitalMode | null;
  source: "Capital.com";
  checkedAt: string;
  detail: string;
  markets: CapitalMarket[];
};

type SessionTokens = {
  cst: string;
  securityToken: string;
  expiresAt: number;
};

type CapitalClientOptions = {
  env?: Record<string, string | undefined>;
  fetcher?: typeof fetch;
  now?: () => number;
};

class CapitalRequestError extends Error {
  constructor(
    readonly state: "unavailable" | "unauthorized",
    readonly safeDetail: string,
  ) {
    super(safeDetail);
  }
}

const origins: Record<CapitalMode, string> = {
  live: "https://api-capital.backend-capital.com",
  demo: "https://demo-api-capital.backend-capital.com",
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function asNumber(value: unknown): number | null {
  if (typeof value !== "number" && typeof value !== "string") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function suffix(value: string | null): string | null {
  return value ? value.slice(-4) : null;
}

function describeFailure(status: number): CapitalRequestError {
  if (status === 401 || status === 403) {
    return new CapitalRequestError(
      "unauthorized",
      "رفض Capital.com بيانات الدخول أو صلاحية القراءة. راجع المفاتيح وصلاحيات الحساب.",
    );
  }
  if (status === 429) {
    return new CapitalRequestError(
      "unavailable",
      "بلغ اتصال Capital.com حد الطلبات؛ ستُعاد المحاولة بعد فترة قصيرة.",
    );
  }
  return new CapitalRequestError(
    "unavailable",
    `تعذر جلب البيانات من Capital.com (HTTP ${status}). لم تُعرض بيانات بديلة.`,
  );
}

/**
 * Read-only Capital.com client. Its only POST request authenticates a session;
 * account, position, and market data are fetched with GET requests only.
 * Session tokens stay in process memory and are never returned or logged.
 */
export function createCapitalReadOnlyClient(options: CapitalClientOptions = {}) {
  const env = options.env ?? process.env;
  const fetcher = options.fetcher ?? fetch;
  const now = options.now ?? Date.now;
  let cachedSession: SessionTokens | null = null;
  let sessionRequest: Promise<SessionTokens> | null = null;
  let cachedAccount: { expiresAt: number; value: CapitalAccountSnapshot } | null = null;
  const marketCache = new Map<string, { expiresAt: number; value: CapitalMarketsSnapshot }>();

  function configuration():
    | { mode: CapitalMode; origin: string; apiKey: string; identifier: string; password: string }
    | null {
    const modeValue = env.CAPITAL_API_MODE?.trim().toLowerCase();
    if (modeValue !== "live" && modeValue !== "demo") return null;
    const apiKey = env.CAPITAL_API_KEY?.trim();
    const identifier = env.CAPITAL_IDENTIFIER?.trim();
    const password = env.CAPITAL_PASSWORD;
    if (!apiKey || !identifier || !password) return null;
    return { mode: modeValue, origin: origins[modeValue], apiKey, identifier, password };
  }

  function emptyAccount(
    state: ConnectionState,
    detail: string,
    environment: CapitalMode | null = configuration()?.mode ?? null,
  ): CapitalAccountSnapshot {
    return {
      state,
      environment,
      source: "Capital.com",
      checkedAt: new Date(now()).toISOString(),
      detail,
      accountIdSuffix: null,
      currency: null,
      balance: null,
      available: null,
      deposit: null,
      profitLoss: null,
      positions: [],
    };
  }

  function emptyMarkets(
    state: ConnectionState,
    detail: string,
    environment: CapitalMode | null = configuration()?.mode ?? null,
  ): CapitalMarketsSnapshot {
    return {
      state,
      environment,
      source: "Capital.com",
      checkedAt: new Date(now()).toISOString(),
      detail,
      markets: [],
    };
  }

  async function authenticate(force = false): Promise<SessionTokens> {
    const config = configuration();
    if (!config) {
      throw new CapitalRequestError(
        "unavailable",
        "الاتصال غير مهيأ. اضبط CAPITAL_API_MODE وبيانات Capital.com في الأسرار.",
      );
    }
    if (!force && cachedSession && cachedSession.expiresAt > now()) return cachedSession;
    if (sessionRequest) return sessionRequest;

    sessionRequest = (async () => {
      let response: Response;
      try {
        response = await fetcher(`${config.origin}/api/v1/session`, {
          method: "POST",
          headers: {
            "content-type": "application/json",
            "X-CAP-API-KEY": config.apiKey,
          },
          body: JSON.stringify({
            identifier: config.identifier,
            password: config.password,
            encryptedPassword: false,
          }),
          signal: AbortSignal.timeout(8_000),
          redirect: "manual",
        });
      } catch {
        throw new CapitalRequestError(
          "unavailable",
          "تعذر الوصول إلى خدمة Capital.com. لم تُعرض بيانات بديلة.",
        );
      }
      if (!response.ok) throw describeFailure(response.status);
      const cst = response.headers.get("CST");
      const securityToken = response.headers.get("X-SECURITY-TOKEN");
      if (!cst || !securityToken) {
        throw new CapitalRequestError(
          "unavailable",
          "استجاب Capital.com دون رموز جلسة صالحة؛ لم يُعتبر الاتصال ناجحاً.",
        );
      }
      const tokens = { cst, securityToken, expiresAt: now() + 8 * 60_000 };
      cachedSession = tokens;
      return tokens;
    })();

    try {
      return await sessionRequest;
    } finally {
      sessionRequest = null;
    }
  }

  async function getJson(path: string, retry = true): Promise<unknown> {
    const config = configuration();
    if (!config) {
      throw new CapitalRequestError(
        "unavailable",
        "الاتصال غير مهيأ. اضبط CAPITAL_API_MODE وبيانات Capital.com في الأسرار.",
      );
    }
    const session = await authenticate();
    let response: Response;
    try {
      response = await fetcher(`${config.origin}/api/v1${path}`, {
        method: "GET",
        headers: {
          "X-CAP-API-KEY": config.apiKey,
          CST: session.cst,
          "X-SECURITY-TOKEN": session.securityToken,
        },
        signal: AbortSignal.timeout(8_000),
        redirect: "manual",
      });
    } catch {
      throw new CapitalRequestError(
        "unavailable",
        "انقطع اتصال القراءة بـCapital.com. لم تُعرض بيانات بديلة.",
      );
    }
    if (response.status === 401 && retry) {
      cachedSession = null;
      await authenticate(true);
      return getJson(path, false);
    }
    if (!response.ok) throw describeFailure(response.status);
    try {
      return await response.json();
    } catch {
      throw new CapitalRequestError(
        "unavailable",
        "أعاد Capital.com استجابة غير قابلة للقراءة؛ لم تُعرض بيانات بديلة.",
      );
    }
  }

  function normalizePosition(raw: unknown): CapitalPosition | null {
    const row = asRecord(raw);
    const position = asRecord(row.position);
    const market = asRecord(row.market);
    const rawId = asText(position.dealId) ?? asText(row.dealId);
    const epic = asText(market.epic);
    const rawDirection = asText(position.direction)?.toLowerCase();
    if (!epic || (rawDirection !== "buy" && rawDirection !== "sell")) return null;
    return {
      id: suffix(rawId) ? `••${suffix(rawId)}` : `position-${epic}`,
      epic,
      name: asText(market.instrumentName) ?? epic,
      direction: rawDirection,
      size: asNumber(position.size),
      entryPrice: asNumber(position.level),
      currentPrice:
        rawDirection === "buy"
          ? asNumber(market.bid)
          : asNumber(market.offer),
      profitLoss: asNumber(position.profit ?? position.profitAndLoss),
      currency: asText(position.currency) ?? asText(market.currency),
      openedAt:
        asText(position.createdDateUTC) ??
        asText(position.createdDate) ??
        null,
      marketStatus: asText(market.marketStatus),
    };
  }

  function normalizeMarket(raw: unknown): CapitalMarket | null {
    const row = asRecord(raw);
    const epic = asText(row.epic);
    if (!epic) return null;
    return {
      epic,
      name: asText(row.instrumentName) ?? epic,
      instrumentType: asText(row.instrumentType),
      marketStatus: asText(row.marketStatus),
      bid: asNumber(row.bid),
      offer: asNumber(row.offer),
      change: asNumber(row.netChange),
      changePct: asNumber(row.percentageChange),
      currency: asText(row.currency),
      updatedAt:
        asText(row.updateTimeUTC) ??
        asText(row.updateTime) ??
        asText(row.lastUpdateTime) ??
        null,
    };
  }

  async function getAccountSnapshot(force = false): Promise<CapitalAccountSnapshot> {
    const config = configuration();
    if (!config) {
      return emptyAccount(
        "not_configured",
        "لم تُضبط بيانات Capital.com بعد. أضف CAPITAL_API_MODE وبيانات الدخول في الأسرار.",
        null,
      );
    }
    if (!force && cachedAccount && cachedAccount.expiresAt > now()) return cachedAccount.value;

    try {
      const [accountsPayload, positionsPayload] = await Promise.all([
        getJson("/accounts"),
        getJson("/positions"),
      ]);
      const accountRoot = asRecord(accountsPayload);
      const positionRoot = asRecord(positionsPayload);
      const accounts = asArray(accountRoot.accounts).map(asRecord);
      const currentAccountId =
        asText(accountRoot.currentAccountId) ??
        asText(asRecord(accountRoot.account).accountId);
      const selectedAccount =
        accounts.find((account) => asText(account.accountId) === currentAccountId) ??
        accounts.find((account) => account.preferred === true) ??
        accounts[0];
      if (!selectedAccount) {
        throw new CapitalRequestError(
          "unavailable",
          "نجح تسجيل الدخول لكن Capital.com لم يُرجع حساباً قابلاً للقراءة.",
        );
      }
      const info = asRecord(selectedAccount.accountInfo);
      const positions = asArray(positionRoot.positions)
        .map(normalizePosition)
        .filter((position): position is CapitalPosition => position !== null);
      const snapshot: CapitalAccountSnapshot = {
        state: "connected",
        environment: config.mode,
        source: "Capital.com",
        checkedAt: new Date(now()).toISOString(),
        detail: "تم التحقق من الجلسة وقراءة الحساب والمراكز المفتوحة عبر واجهات GET فقط.",
        accountIdSuffix: suffix(asText(selectedAccount.accountId)),
        currency: asText(selectedAccount.currencyIsoCode),
        balance: asNumber(info.balance),
        available: asNumber(info.available),
        deposit: asNumber(info.deposit),
        profitLoss: asNumber(info.profitLoss),
        positions,
      };
      cachedAccount = { expiresAt: now() + 15_000, value: snapshot };
      return snapshot;
    } catch (error) {
      cachedAccount = null;
      if (error instanceof CapitalRequestError) {
        return emptyAccount(error.state, error.safeDetail, config.mode);
      }
      return emptyAccount(
        "unavailable",
        "تعذر التحقق من حساب Capital.com. لم تُعرض بيانات بديلة.",
        config.mode,
      );
    }
  }

  async function searchMarkets(searchTerm: string): Promise<CapitalMarketsSnapshot> {
    const config = configuration();
    const query = searchTerm.trim().slice(0, 80);
    if (!config) {
      return emptyMarkets(
        "not_configured",
        "أضف إعدادات Capital.com في الأسرار لعرض الأسواق الحقيقية.",
        null,
      );
    }
    if (!query) {
      return emptyMarkets("connected", "اكتب رمزاً أو اسماً للبحث في أسواق Capital.com.", config.mode);
    }
    const cacheKey = query.toLowerCase();
    const cached = marketCache.get(cacheKey);
    if (cached && cached.expiresAt > now()) return cached.value;
    try {
      const params = new URLSearchParams({ searchTerm: query });
      const payload = asRecord(await getJson(`/markets?${params.toString()}`));
      const markets = asArray(payload.markets)
        .map(normalizeMarket)
        .filter((market): market is CapitalMarket => market !== null);
      const snapshot: CapitalMarketsSnapshot = {
        state: "connected",
        environment: config.mode,
        source: "Capital.com",
        checkedAt: new Date(now()).toISOString(),
        detail: markets.length
          ? `أعاد Capital.com ${markets.length} نتيجة حقيقية لهذا البحث.`
          : "لم يُرجع Capital.com أدوات مطابقة؛ لا توجد أسعار بديلة.",
        markets,
      };
      marketCache.set(cacheKey, { expiresAt: now() + 10_000, value: snapshot });
      return snapshot;
    } catch (error) {
      if (error instanceof CapitalRequestError) {
        return emptyMarkets(error.state, error.safeDetail, config.mode);
      }
      return emptyMarkets(
        "unavailable",
        "تعذر البحث في أسواق Capital.com. لم تُعرض بيانات بديلة.",
        config.mode,
      );
    }
  }

  return { getAccountSnapshot, searchMarkets };
}

export const capitalReadOnlyClient = createCapitalReadOnlyClient();
