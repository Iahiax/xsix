export type Candle = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type Shield = {
  blocked: boolean;
  reasons: string[];
};

function hashSeed(input: string): number {
  let hash = 2166136261;
  for (const character of input) {
    hash ^= character.charCodeAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function randomGenerator(seed: number): () => number {
  let state = seed || 1;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

export function generateSyntheticBars(
  symbol: string,
  count = 512,
  initialPrice = 1,
  spanMs = count * 60_000,
): Candle[] {
  const random = randomGenerator(hashSeed(symbol));
  const bars: Candle[] = [];
  let close = initialPrice;
  const volatility = symbol.includes("BTC") ? 0.009 : 0.0018;
  const now = Date.now();
  const intervalMs = spanMs / Math.max(1, count - 1);

  for (let index = count - 1; index >= 0; index -= 1) {
    const open = close;
    const drift = Math.sin((count - index) / 33) * volatility * 0.2;
    const shock = (random() - 0.5) * volatility * 2;
    close = Math.max(0.00001, open * (1 + drift + shock));
    const wick = random() * volatility * open * 0.75;
    bars.push({
      time: now - index * intervalMs,
      open,
      high: Math.max(open, close) + wick,
      low: Math.max(0.00001, Math.min(open, close) - wick * random()),
      close,
      volume: 100 + random() * 900,
    });
  }
  return bars;
}

export function ema(values: number[], period: number): number[] {
  if (period <= 0) throw new Error("EMA period must be positive");
  const output: number[] = [];
  const alpha = 2 / (period + 1);
  let previous = values[0] ?? 0;
  for (const value of values) {
    previous = alpha * value + (1 - alpha) * previous;
    output.push(previous);
  }
  return output;
}

export function rsi(values: number[], period = 14): number[] {
  if (values.length < 2) return values.map(() => 50);
  const changes = values.map((value, index) =>
    index === 0 ? 0 : value - (values[index - 1] ?? value),
  );
  const gains = changes.map((change) => Math.max(0, change));
  const losses = changes.map((change) => Math.max(0, -change));
  const averageGain = ema(gains, period);
  const averageLoss = ema(losses, period);
  return values.map((_, index) => {
    const loss = averageLoss[index] ?? 0;
    const gain = averageGain[index] ?? 0;
    if (loss === 0) return gain === 0 ? 50 : 100;
    return 100 - 100 / (1 + gain / loss);
  });
}

export function atr(candles: Candle[], period = 14): number[] {
  const ranges = candles.map((bar, index) => {
    const previousClose = candles[index - 1]?.close ?? bar.close;
    return Math.max(
      bar.high - bar.low,
      Math.abs(bar.high - previousClose),
      Math.abs(bar.low - previousClose),
    );
  });
  return ema(ranges, period);
}

export function bollinger(
  values: number[],
  period = 20,
  deviation = 2,
): { middle: number; upper: number; lower: number } {
  const sample = values.slice(-period);
  const middle = sample.reduce((sum, value) => sum + value, 0) / Math.max(1, sample.length);
  const variance =
    sample.reduce((sum, value) => sum + (value - middle) ** 2, 0) /
    Math.max(1, sample.length);
  const width = Math.sqrt(variance) * deviation;
  return { middle, upper: middle + width, lower: middle - width };
}

export function rollingHurst(values: number[], maxLag = 20): number {
  if (values.length < maxLag + 4) return 0.5;
  const logLags: number[] = [];
  const logVolatility: number[] = [];
  for (let lag = 2; lag <= maxLag; lag += 1) {
    const differences: number[] = [];
    for (let index = lag; index < values.length; index += 1) {
      differences.push((values[index] ?? 0) - (values[index - lag] ?? 0));
    }
    const mean = differences.reduce((sum, value) => sum + value, 0) / differences.length;
    const variance =
      differences.reduce((sum, value) => sum + (value - mean) ** 2, 0) /
      Math.max(1, differences.length - 1);
    if (variance > 0) {
      logLags.push(Math.log(lag));
      logVolatility.push(Math.log(Math.sqrt(variance)));
    }
  }
  const xMean = logLags.reduce((sum, value) => sum + value, 0) / logLags.length;
  const yMean =
    logVolatility.reduce((sum, value) => sum + value, 0) / logVolatility.length;
  const numerator = logLags.reduce(
    (sum, value, index) =>
      sum + (value - xMean) * ((logVolatility[index] ?? 0) - yMean),
    0,
  );
  const denominator = logLags.reduce((sum, value) => sum + (value - xMean) ** 2, 0);
  return Math.max(0, Math.min(1, denominator ? numerator / denominator : 0.5));
}

export function kalmanVelocity(values: number[]): number {
  if (values.length < 2) return 0;
  let estimate = values[0] ?? 0;
  let covariance = 1;
  let prior = estimate;
  for (const value of values.slice(1)) {
    covariance += 0.001;
    const gain = covariance / (covariance + 0.01);
    prior = estimate;
    estimate += gain * (value - estimate);
    covariance *= 1 - gain;
  }
  return estimate - prior;
}

export function garchForecast(
  returns: number[],
  alpha = 0.08,
  beta = 0.88,
): number {
  if (returns.length === 0) return 0;
  const varianceTarget =
    returns.reduce((sum, value) => sum + value * value, 0) / returns.length;
  let variance = varianceTarget;
  for (const value of returns) {
    variance = Math.max(
      0,
      varianceTarget * (1 - alpha - beta) + alpha * value * value + beta * variance,
    );
  }
  return Math.sqrt(variance);
}

export function fractionalDifference(
  values: number[],
  order = 0.4,
  threshold = 1e-4,
): number[] {
  const weights = [1];
  for (let index = 1; index < values.length; index += 1) {
    const weight = -(weights[index - 1] ?? 0) * ((order - index + 1) / index);
    if (Math.abs(weight) < threshold) break;
    weights.push(weight);
  }
  return values.map((_, index) => {
    let total = 0;
    for (let weightIndex = 0; weightIndex < weights.length && weightIndex <= index; weightIndex += 1) {
      total += (weights[weightIndex] ?? 0) * (values[index - weightIndex] ?? 0);
    }
    return total;
  });
}

export function volumeDeltaZScore(candles: Candle[], window = 30): number {
  const deltas = candles.map((bar) => (bar.close >= bar.open ? bar.volume : -bar.volume));
  const sample = deltas.slice(-window);
  if (sample.length < 2) return 0;
  const mean = sample.reduce((sum, value) => sum + value, 0) / sample.length;
  const variance =
    sample.reduce((sum, value) => sum + (value - mean) ** 2, 0) /
    (sample.length - 1);
  return variance > 0 ? ((sample.at(-1) ?? 0) - mean) / Math.sqrt(variance) : 0;
}

export function assessMarketShields(now = new Date()): Shield {
  const day = now.getUTCDay();
  const minutes = now.getUTCHours() * 60 + now.getUTCMinutes();
  const reasons: string[] = [];

  if ((day === 5 && minutes >= 20 * 60) || day === 6 || (day === 0 && minutes < 21 * 60)) {
    reasons.push("حظر التداول خارج ساعات السوق الأسبوعية");
  }
  if (minutes >= 15 * 60 + 55 && minutes < 16 * 60 + 5) {
    reasons.push("نافذة تثبيت لندن 16:00 UTC");
  }
  if (minutes >= 21 * 60 + 30 && minutes < 22 * 60 + 15) {
    reasons.push("نافذة رسوم التبييت");
  }
  return { blocked: reasons.length > 0, reasons };
}

export function instrumentAnalytics(candles: Candle[]) {
  const closes = candles.map((bar) => bar.close);
  const returns = closes.slice(1).map((close, index) => close / (closes[index] ?? close) - 1);
  const last = closes.at(-1) ?? 0;
  const prior = closes.at(-2) ?? last;
  const fastEma = ema(closes, 20).at(-1) ?? last;
  const slowEma = ema(closes, 50).at(-1) ?? last;
  const rsiValue = rsi(closes, 14).at(-1) ?? 50;
  const atrValue = atr(candles, 14).at(-1) ?? 0;
  const bands = bollinger(closes);
  const hurst = rollingHurst(closes.slice(-128));
  const garch = garchForecast(returns.slice(-128));
  const kalman = kalmanVelocity(closes.slice(-32));
  const volumeDelta = volumeDeltaZScore(candles);
  const fractional = fractionalDifference(closes.slice(-64)).at(-1) ?? 0;
  const regime =
    hurst >= 0.53 ? "ترند" : hurst <= 0.47 ? "ارتداد" : "عشوائي/محايد";
  const signal =
    fastEma > slowEma && rsiValue < 72
      ? "buy"
      : fastEma < slowEma && rsiValue > 28
        ? "sell"
        : "neutral";

  return {
    fastEma,
    slowEma,
    rsi: rsiValue,
    atr: atrValue,
    bollinger: bands,
    hurst,
    garchVolatility: garch,
    kalmanVelocity: kalman,
    volumeDeltaZScore: volumeDelta,
    fractionalDifference: fractional,
    regime,
    signal,
    changePct: prior ? ((last - prior) / prior) * 100 : 0,
  };
}

export function buildIllustrativeBacktest(
  symbol: string,
  strategy: string,
  startingBalance: number,
  windowDays: number,
) {
  const barCount = Math.min(900, Math.max(240, windowDays * 2));
  const bars = generateSyntheticBars(
    symbol,
    barCount,
    100,
    windowDays * 24 * 60 * 60 * 1000,
  );
  const closes = bars.map((bar) => bar.close);
  const fast = ema(closes, strategy === "mean-reversion" ? 8 : 12);
  const slow = ema(closes, strategy === "mean-reversion" ? 24 : 36);
  const rsiSeries = rsi(closes);
  const balanceCurve: { date: string; equity: number }[] = [];
  let equity = startingBalance;
  let peak = equity;
  let maxDrawdown = 0;
  let positive = 0;
  let negative = 0;
  let wins = 0;
  let losses = 0;
  let openSide = 0;
  let entry = 0;
  const step = Math.max(1, Math.floor(bars.length / 36));

  for (let index = 50; index < bars.length; index += 1) {
    const price = closes[index] ?? 0;
    const priorPrice = closes[index - 1] ?? price;
    const isMeanReversion = strategy === "mean-reversion";
    const direction =
      isMeanReversion
        ? (rsiSeries[index] ?? 50) < 32
          ? 1
          : (rsiSeries[index] ?? 50) > 68
            ? -1
            : 0
        : (fast[index] ?? 0) > (slow[index] ?? 0)
          ? 1
          : (fast[index] ?? 0) < (slow[index] ?? 0)
            ? -1
            : 0;

    if (openSide !== 0) {
      const markReturn = ((price - entry) / Math.max(entry, 0.00001)) * openSide;
      const finished = Math.abs(markReturn) >= 0.004 || index % 19 === 0;
      if (finished) {
        const outcome = equity * Math.max(-0.008, Math.min(0.012, markReturn * 0.12));
        equity += outcome;
        if (outcome >= 0) {
          positive += outcome;
          wins += 1;
        } else {
          negative += Math.abs(outcome);
          losses += 1;
        }
        openSide = 0;
      }
    }
    if (openSide === 0 && direction !== 0 && index % 3 === 0) {
      openSide = direction;
      entry = price;
    }

    peak = Math.max(peak, equity);
    maxDrawdown = Math.max(maxDrawdown, peak ? ((peak - equity) / peak) * 100 : 0);
    if ((index - 50) % step === 0) {
      balanceCurve.push({
        date: new Date(bars[index]?.time ?? Date.now()).toISOString().slice(0, 10),
        equity: Math.round(equity * 100) / 100,
      });
    }
    if (!Number.isFinite(priorPrice)) break;
  }

  const count = wins + losses;
  return {
    returnPct: ((equity - startingBalance) / startingBalance) * 100,
    winRate: count ? (wins / count) * 100 : 0,
    maxDrawdown,
    profitFactor: negative ? positive / negative : positive ? 99 : 0,
    totalTrades: count,
    equityCurve: balanceCurve,
  };
}
