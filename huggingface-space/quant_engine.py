"""CPU-friendly, dependency-free quant research primitives.

The module only analyzes validated candle data supplied by a real provider.
It never creates prices, submits broker orders, or promotes a model. The MLP
and Q-learning agent are research candidates and must pass out-of-sample checks
before anyone considers using their signals.
"""

from __future__ import annotations

import math
import random
from datetime import datetime
from typing import Any

MAX_CANDLES = 10_000
FEATURE_COUNT = 7
CLASS_DOWN = 0
CLASS_FLAT = 1
CLASS_UP = 2


class QuantDataError(ValueError):
    """Raised when market data is incomplete, invalid, or out of order."""


def _finite(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise QuantDataError("A candle contains a non-numeric price.") from error
    if not math.isfinite(number):
        raise QuantDataError("A candle contains a non-finite price.")
    return number


def validate_candles(candles: Any, *, min_candles: int = 60) -> list[dict[str, Any]]:
    """Validate and normalize OHLCV records without filling missing values."""
    if not isinstance(candles, list):
        raise QuantDataError("Candles must be a list returned by a market-data provider.")
    if len(candles) > MAX_CANDLES:
        raise QuantDataError(f"At most {MAX_CANDLES} candles may be analyzed per run.")
    if len(candles) < min_candles:
        raise QuantDataError(f"At least {min_candles} real candles are required.")

    normalized: list[dict[str, Any]] = []
    previous_timestamp: str | None = None
    for raw in candles:
        if not isinstance(raw, dict):
            raise QuantDataError("A candle has an invalid shape.")
        timestamp = raw.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp.strip():
            raise QuantDataError("A candle is missing its provider timestamp.")
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as error:
            raise QuantDataError("A candle timestamp is invalid.") from error
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise QuantDataError("Candles must be strictly ordered by timestamp.")
        previous_timestamp = timestamp

        candle = {
            "timestamp": timestamp,
            "open": _finite(raw.get("open")),
            "high": _finite(raw.get("high")),
            "low": _finite(raw.get("low")),
            "close": _finite(raw.get("close")),
            "volume": None if raw.get("volume") is None else _finite(raw.get("volume")),
            "spread": None if raw.get("spread") is None else _finite(raw.get("spread")),
        }
        if min(candle["open"], candle["high"], candle["low"], candle["close"]) <= 0:
            raise QuantDataError("Candle prices must be positive.")
        if candle["high"] < max(candle["open"], candle["close"], candle["low"]):
            raise QuantDataError("Candle high is below another OHLC value.")
        if candle["low"] > min(candle["open"], candle["close"], candle["high"]):
            raise QuantDataError("Candle low is above another OHLC value.")
        if candle["volume"] is not None and candle["volume"] < 0:
            raise QuantDataError("Candle volume cannot be negative.")
        if candle["spread"] is not None and candle["spread"] < 0:
            raise QuantDataError("Observed bid/ask spread cannot be negative.")
        normalized.append(candle)
    return normalized


def _ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    alpha = 2 / (period + 1)
    current = seed
    for index in range(period, len(values)):
        current = alpha * values[index] + (1 - alpha) * current
        result[index] = current
    return result


def technical_indicators(
    candles: Any,
    *,
    rsi_period: int = 14,
    atr_period: int = 14,
    zigzag_threshold: float = 0.025,
) -> list[dict[str, Any]]:
    """Compute RSI, MACD, ATR, SuperTrend, momentum, volatility, and ZigZag."""
    rows = validate_candles(candles)
    closes = [row["close"] for row in rows]
    ema_12 = _ema(closes, 12)
    ema_20 = _ema(closes, 20)
    ema_26 = _ema(closes, 26)
    ema_50 = _ema(closes, 50)
    macd = [
        None if ema_12[index] is None or ema_26[index] is None
        else float(ema_12[index]) - float(ema_26[index])
        for index in range(len(rows))
    ]
    macd_signal: list[float | None] = [None] * len(rows)
    first_macd = next((index for index, value in enumerate(macd) if value is not None), None)
    if first_macd is not None:
        signal_values = _ema([float(value) for value in macd[first_macd:] if value is not None], 9)
        macd_signal[first_macd:] = signal_values

    gains = [0.0] * len(rows)
    losses = [0.0] * len(rows)
    true_ranges = [0.0] * len(rows)
    returns = [0.0] * len(rows)
    for index in range(1, len(rows)):
        delta = closes[index] - closes[index - 1]
        gains[index] = max(delta, 0.0)
        losses[index] = max(-delta, 0.0)
        true_ranges[index] = max(
            rows[index]["high"] - rows[index]["low"],
            abs(rows[index]["high"] - closes[index - 1]),
            abs(rows[index]["low"] - closes[index - 1]),
        )
        returns[index] = closes[index] / closes[index - 1] - 1

    rsi: list[float | None] = [None] * len(rows)
    atr: list[float | None] = [None] * len(rows)
    if len(rows) > max(rsi_period, atr_period):
        average_gain = sum(gains[1 : rsi_period + 1]) / rsi_period
        average_loss = sum(losses[1 : rsi_period + 1]) / rsi_period
        average_range = sum(true_ranges[1 : atr_period + 1]) / atr_period
        for index in range(max(rsi_period, atr_period), len(rows)):
            if index > rsi_period:
                average_gain = ((rsi_period - 1) * average_gain + gains[index]) / rsi_period
                average_loss = ((rsi_period - 1) * average_loss + losses[index]) / rsi_period
            if index > atr_period:
                average_range = ((atr_period - 1) * average_range + true_ranges[index]) / atr_period
            if average_loss == 0:
                rsi[index] = 100.0
            else:
                strength = average_gain / average_loss
                rsi[index] = 100 - 100 / (1 + strength)
            atr[index] = average_range

    supertrend: list[float | None] = [None] * len(rows)
    trend: list[int | None] = [None] * len(rows)
    final_upper: float | None = None
    final_lower: float | None = None
    direction = 1
    for index, row in enumerate(rows):
        current_atr = atr[index]
        if current_atr is None:
            continue
        midpoint = (row["high"] + row["low"]) / 2
        upper = midpoint + 3 * current_atr
        lower = midpoint - 3 * current_atr
        if final_upper is None or final_lower is None:
            final_upper, final_lower = upper, lower
        else:
            final_upper = upper if upper < final_upper or closes[index - 1] > final_upper else final_upper
            final_lower = lower if lower > final_lower or closes[index - 1] < final_lower else final_lower
            if direction > 0 and closes[index] < final_lower:
                direction = -1
            elif direction < 0 and closes[index] > final_upper:
                direction = 1
        supertrend[index] = final_lower if direction > 0 else final_upper
        trend[index] = direction

    volatility: list[float | None] = [None] * len(rows)
    for index in range(20, len(rows)):
        window = returns[index - 19 : index + 1]
        mean = sum(window) / len(window)
        volatility[index] = math.sqrt(sum((item - mean) ** 2 for item in window) / len(window))

    zigzag: list[str | None] = [None] * len(rows)
    pivot_index = 0
    pivot_price = closes[0]
    direction_hint = 0
    for index in range(1, len(rows)):
        move = closes[index] / pivot_price - 1
        if direction_hint >= 0 and move <= -zigzag_threshold:
            zigzag[pivot_index] = "peak"
            pivot_index, pivot_price, direction_hint = index, closes[index], -1
        elif direction_hint <= 0 and move >= zigzag_threshold:
            zigzag[pivot_index] = "trough"
            pivot_index, pivot_price, direction_hint = index, closes[index], 1
        elif direction_hint >= 0 and closes[index] > pivot_price:
            pivot_index, pivot_price = index, closes[index]
        elif direction_hint <= 0 and closes[index] < pivot_price:
            pivot_index, pivot_price = index, closes[index]
    zigzag[pivot_index] = "latest_unconfirmed_pivot"

    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        momentum = None if index < 5 else closes[index] / closes[index - 5] - 1
        output.append(
            {
                **row,
                "rsi": rsi[index],
                "macd": macd[index],
                "macd_signal": macd_signal[index],
                "atr": atr[index],
                "supertrend": supertrend[index],
                "trend": trend[index],
                "ema20": ema_20[index],
                "ema50": ema_50[index],
                "momentum5": momentum,
                "volatility20": volatility[index],
                "zigzag": zigzag[index],
            }
        )
    return output


def risk_position_size(
    *,
    equity: float,
    entry_price: float,
    stop_price: float,
    risk_fraction: float = 0.005,
    contract_multiplier: float = 1.0,
    max_notional_fraction: float = 1.0,
) -> dict[str, float]:
    """Return a transparent risk-budget estimate; it does not place an order."""
    values = (equity, entry_price, stop_price, risk_fraction, contract_multiplier, max_notional_fraction)
    if not all(math.isfinite(value) for value in values):
        raise QuantDataError("Risk inputs must be finite numbers.")
    if equity <= 0 or entry_price <= 0 or stop_price <= 0 or contract_multiplier <= 0:
        raise QuantDataError("Equity, prices, and contract multiplier must be positive.")
    if not 0 < risk_fraction <= 0.01:
        raise QuantDataError("Risk per trade must be above 0% and no more than 1%.")
    if not 0 < max_notional_fraction <= 1:
        raise QuantDataError("Maximum notional fraction must be in (0, 1].")
    stop_distance = abs(entry_price - stop_price)
    if stop_distance <= 0:
        raise QuantDataError("Stop price must differ from entry price.")
    risk_budget = equity * risk_fraction
    units_by_risk = risk_budget / (stop_distance * contract_multiplier)
    units_by_exposure = equity * max_notional_fraction / (entry_price * contract_multiplier)
    units = min(units_by_risk, units_by_exposure)
    return {
        "risk_budget": risk_budget,
        "stop_distance": stop_distance,
        "units": units,
        "notional": units * entry_price * contract_multiplier,
        "risk_fraction": risk_fraction,
        "exposure_limited": units_by_exposure < units_by_risk,
    }


def _features_at(rows: list[dict[str, Any]], index: int) -> list[float] | None:
    row = rows[index]
    if any(row.get(key) is None for key in ("rsi", "macd", "atr", "ema20", "ema50", "momentum5", "volatility20")):
        return None
    close = row["close"]
    return [
        max(-0.2, min(0.2, row["close"] / rows[index - 1]["close"] - 1)),
        max(-0.5, min(0.5, row["momentum5"])),
        (row["rsi"] - 50) / 50,
        max(-0.2, min(0.2, row["macd"] / close)),
        max(0.0, min(0.2, row["atr"] / close)),
        max(-0.5, min(0.5, (row["ema20"] - row["ema50"]) / close)),
        max(0.0, min(0.2, row["volatility20"])),
    ]


def _softmax(values: list[float]) -> list[float]:
    peak = max(values)
    exponents = [math.exp(max(-30.0, value - peak)) for value in values]
    total = sum(exponents)
    return [value / total for value in exponents]


def predict_mlp(model: dict[str, Any], features: list[float]) -> list[float]:
    """Return probabilities ordered as down, flat, up."""
    means = model["means"]
    scales = model["scales"]
    values = [
        max(-5.0, min(5.0, (feature - means[index]) / scales[index]))
        for index, feature in enumerate(features)
    ]
    hidden_1 = [
        math.tanh(sum(weight * value for weight, value in zip(row, values)) + bias)
        for row, bias in zip(model["weights_1"], model["biases_1"])
    ]
    hidden_2 = [
        math.tanh(sum(weight * value for weight, value in zip(row, hidden_1)) + bias)
        for row, bias in zip(model["weights_2"], model["biases_2"])
    ]
    logits = [
        sum(weight * value for weight, value in zip(row, hidden_2)) + bias
        for row, bias in zip(model["weights_3"], model["biases_3"])
    ]
    return _softmax(logits)


def train_direction_mlp(
    candles: Any,
    *,
    horizon: int = 3,
    neutral_threshold: float = 0.001,
    epochs: int = 18,
    seed: int = 41,
) -> dict[str, Any]:
    """Train a small two-hidden-layer MLP on an early window; report later windows."""
    if horizon < 1 or horizon > 20 or not 0 <= neutral_threshold < 0.05:
        raise QuantDataError("Model horizon or neutral threshold is outside its safe range.")
    rows = technical_indicators(candles)
    samples: list[tuple[int, list[float], int]] = []
    for index in range(50, len(rows) - horizon):
        features = _features_at(rows, index)
        if features is None:
            continue
        forward_return = rows[index + horizon]["close"] / rows[index]["close"] - 1
        label = CLASS_UP if forward_return > neutral_threshold else CLASS_DOWN if forward_return < -neutral_threshold else CLASS_FLAT
        samples.append((index, features, label))
    if len(samples) < 100:
        raise QuantDataError("At least 100 labeled observations are required for model validation.")

    train_end = int(len(rows) * 0.65)
    validation_end = int(len(rows) * 0.8)
    train = [item for item in samples if item[0] + horizon < train_end]
    validation = [item for item in samples if train_end <= item[0] and item[0] + horizon < validation_end]
    test = [item for item in samples if item[0] >= validation_end and item[0] + horizon < len(rows)]
    if min(len(train), len(validation), len(test)) < 20:
        raise QuantDataError("Not enough candles for chronological train, validation, and test windows.")
    if len(train) > 1_200:
        stride = len(train) / 1_200
        train = [train[min(int(index * stride), len(train) - 1)] for index in range(1_200)]

    means = [sum(item[1][column] for item in train) / len(train) for column in range(FEATURE_COUNT)]
    scales = []
    for column in range(FEATURE_COUNT):
        variance = sum((item[1][column] - means[column]) ** 2 for item in train) / len(train)
        scales.append(max(math.sqrt(variance), 1e-6))
    def scaled(features: list[float]) -> list[float]:
        return [max(-5.0, min(5.0, (feature - means[index]) / scales[index])) for index, feature in enumerate(features)]

    rng = random.Random(seed)
    hidden_1_size, hidden_2_size = 12, 8
    weights_1 = [[rng.uniform(-0.25, 0.25) for _ in range(FEATURE_COUNT)] for _ in range(hidden_1_size)]
    biases_1 = [0.0] * hidden_1_size
    weights_2 = [[rng.uniform(-0.2, 0.2) for _ in range(hidden_1_size)] for _ in range(hidden_2_size)]
    biases_2 = [0.0] * hidden_2_size
    weights_3 = [[rng.uniform(-0.15, 0.15) for _ in range(hidden_2_size)] for _ in range(3)]
    biases_3 = [0.0] * 3
    learning_rate = 0.015

    for _ in range(max(1, min(epochs, 40))):
        order = list(range(len(train)))
        rng.shuffle(order)
        for sample_index in order:
            _, raw_features, label = train[sample_index]
            x = scaled(raw_features)
            h1 = [math.tanh(sum(w * v for w, v in zip(row, x)) + bias) for row, bias in zip(weights_1, biases_1)]
            h2 = [math.tanh(sum(w * v for w, v in zip(row, h1)) + bias) for row, bias in zip(weights_2, biases_2)]
            probabilities = _softmax([
                sum(w * v for w, v in zip(row, h2)) + bias
                for row, bias in zip(weights_3, biases_3)
            ])
            delta_3 = probabilities[:]
            delta_3[label] -= 1.0
            delta_2 = [
                (sum(weights_3[out][unit] * delta_3[out] for out in range(3))) * (1 - h2[unit] ** 2)
                for unit in range(hidden_2_size)
            ]
            delta_1 = [
                (sum(weights_2[mid][unit] * delta_2[mid] for mid in range(hidden_2_size))) * (1 - h1[unit] ** 2)
                for unit in range(hidden_1_size)
            ]
            for out in range(3):
                for unit in range(hidden_2_size):
                    weights_3[out][unit] -= learning_rate * delta_3[out] * h2[unit]
                biases_3[out] -= learning_rate * delta_3[out]
            for mid in range(hidden_2_size):
                for unit in range(hidden_1_size):
                    weights_2[mid][unit] -= learning_rate * delta_2[mid] * h1[unit]
                biases_2[mid] -= learning_rate * delta_2[mid]
            for unit in range(hidden_1_size):
                for feature_index in range(FEATURE_COUNT):
                    weights_1[unit][feature_index] -= learning_rate * delta_1[unit] * x[feature_index]
                biases_1[unit] -= learning_rate * delta_1[unit]

    model = {
        "weights_1": weights_1, "biases_1": biases_1,
        "weights_2": weights_2, "biases_2": biases_2,
        "weights_3": weights_3, "biases_3": biases_3,
        "means": means, "scales": scales, "horizon": horizon,
        "labels": ["down", "flat", "up"],
    }

    def metrics(window: list[tuple[int, list[float], int]]) -> dict[str, Any]:
        correct = 0
        predicted_counts = [0, 0, 0]
        actual_counts = [0, 0, 0]
        confusion = [[0, 0, 0] for _ in range(3)]
        for _, features, label in window:
            predicted = max(range(3), key=lambda item: predict_mlp(model, features)[item])
            correct += int(predicted == label)
            predicted_counts[predicted] += 1
            actual_counts[label] += 1
            confusion[label][predicted] += 1
        class_recalls = [
            confusion[index][index] / actual_counts[index]
            for index in range(3) if actual_counts[index]
        ]
        return {
            "observations": len(window),
            "accuracy": correct / len(window) if window else None,
            "balanced_accuracy": sum(class_recalls) / len(class_recalls) if class_recalls else None,
            "confusion_matrix": confusion,
        }

    return {
        "model": model,
        "training": {"observations": len(train), "epochs": max(1, min(epochs, 40)), "split": "chronological_65_15_20"},
        "validation": metrics(validation),
        "out_of_sample": metrics(test),
        "model_type": "two_hidden_layer_mlp",
        "target": f"{horizon}-bar direction with neutral threshold {neutral_threshold:.4%}",
        "candidate_only": True,
    }


def _state_for(row: dict[str, Any]) -> tuple[int, int, int]:
    direction = 1 if (row["ema20"] or 0) > (row["ema50"] or 0) else 0
    rsi = row["rsi"] or 50
    rsi_bucket = 0 if rsi < 40 else 1 if rsi < 60 else 2
    volatility = row["volatility20"] or 0
    vol_bucket = 0 if volatility < 0.005 else 1 if volatility < 0.015 else 2
    return direction, rsi_bucket, vol_bucket


def train_q_learning(
    candles: Any,
    *,
    episodes: int = 24,
    commission_bps: float = 0.0,
    seed: int = 73,
) -> dict[str, Any]:
    """Train a discrete Q-learning research agent on an early window only."""
    if not math.isfinite(commission_bps) or not 0 <= commission_bps <= 100:
        raise QuantDataError("Commission must be between 0 and 100 basis points.")
    rows = technical_indicators(candles)
    split = int(len(rows) * 0.75)
    warmup = 50
    if split - warmup < 60 or len(rows) - split < 20:
        raise QuantDataError("Not enough candles for a separate Q-learning test window.")
    q_table: dict[tuple[int, int, int], list[float]] = {}
    rng = random.Random(seed)
    actions = [-1, 0, 1]
    cost = commission_bps / 10_000
    for episode in range(max(1, min(episodes, 100))):
        epsilon = max(0.03, 0.25 * (1 - episode / max(episodes, 1)))
        previous_position = 0
        for index in range(warmup, split - 1):
            state = _state_for(rows[index])
            values = q_table.setdefault(state, [0.0, 0.0, 0.0])
            action_index = rng.randrange(3) if rng.random() < epsilon else max(range(3), key=lambda item: values[item])
            action = actions[action_index]
            next_state = _state_for(rows[index + 1])
            next_values = q_table.setdefault(next_state, [0.0, 0.0, 0.0])
            market_return = rows[index + 1]["close"] / rows[index]["close"] - 1
            reward = action * market_return - (cost * abs(action - previous_position))
            values[action_index] += 0.12 * (reward + 0.93 * max(next_values) - values[action_index])
            previous_position = action

    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    previous_position = 0
    changes = 0
    for index in range(split, len(rows) - 1):
        values = q_table.get(_state_for(rows[index]), [0.0, 0.0, 0.0])
        action = actions[max(range(3), key=lambda item: values[item])]
        if action != previous_position:
            changes += 1
        market_return = rows[index + 1]["close"] / rows[index]["close"] - 1
        equity *= max(0.0, 1 + action * market_return - cost * abs(action - previous_position))
        previous_position = action
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, 1 - equity / peak)
    return {
        "model_type": "tabular_q_learning",
        "training_window": {"start": rows[warmup]["timestamp"], "end": rows[split - 1]["timestamp"]},
        "test_window": {"start": rows[split]["timestamp"], "end": rows[-1]["timestamp"]},
        "test_observations": len(rows) - split - 1,
        "out_of_sample_return": equity - 1,
        "out_of_sample_max_drawdown": max_drawdown,
        "position_changes": changes,
        "commission_bps_assumption": commission_bps,
        "candidate_only": True,
    }


def trend_signal(row: dict[str, Any], probabilities: list[float]) -> str:
    """Require indicator agreement plus an out-of-sample MLP confidence gate."""
    if any(row.get(key) is None for key in ("rsi", "macd", "macd_signal", "ema20", "ema50", "trend")):
        return "hold"
    down, _, up = probabilities
    if (
        row["ema20"] > row["ema50"]
        and row["macd"] > row["macd_signal"]
        and row["trend"] == 1
        and 48 <= row["rsi"] <= 72
        and up >= 0.58
        and up - down >= 0.20
    ):
        return "buy"
    if (
        row["ema20"] < row["ema50"]
        and row["macd"] < row["macd_signal"]
        and row["trend"] == -1
        and 28 <= row["rsi"] <= 52
        and down >= 0.58
        and down - up >= 0.20
    ):
        return "sell"
    return "hold"


def run_backtest(
    candles: Any,
    model_result: dict[str, Any],
    *,
    starting_equity: float,
    contract_multiplier: float = 1.0,
    risk_fraction: float = 0.005,
    daily_loss_limit: float = 0.02,
    commission_bps: float = 0.0,
    max_holding_bars: int = 24,
) -> dict[str, Any]:
    """Conservative, long/short trend backtest with stops and daily loss cutoff."""
    rows = technical_indicators(candles)
    if not math.isfinite(starting_equity) or starting_equity <= 0:
        raise QuantDataError("Starting equity must be positive.")
    if not math.isfinite(contract_multiplier) or contract_multiplier <= 0:
        raise QuantDataError("Contract multiplier must be positive and verified for this market.")
    if not 0 < risk_fraction <= 0.01 or not 0 < daily_loss_limit <= 0.05:
        raise QuantDataError("Risk per trade or daily loss limit exceeds the safe research range.")
    if not 0 <= commission_bps <= 100 or not 1 <= max_holding_bars <= 240:
        raise QuantDataError("Trading-cost or holding-period assumptions are invalid.")
    model = model_result.get("model")
    if not isinstance(model, dict):
        raise QuantDataError("An evaluated MLP candidate is required to filter trend signals.")
    test_start = int(len(rows) * 0.8)
    if test_start < 70 or len(rows) - test_start < 20:
        raise QuantDataError("Not enough candles for a separated out-of-sample backtest.")

    equity = starting_equity
    peak_equity = equity
    max_drawdown = 0.0
    day_start_equity = equity
    current_day: str | None = None
    daily_stopped = False
    trades: list[dict[str, Any]] = []
    commission_rate = commission_bps / 10_000
    index = test_start
    while index < len(rows) - 1:
        day = rows[index]["timestamp"][:10]
        if day != current_day:
            current_day = day
            day_start_equity = equity
            daily_stopped = False
        if daily_stopped or rows[index].get("atr") is None:
            index += 1
            continue
        features = _features_at(rows, index)
        if features is None:
            index += 1
            continue
        probabilities = predict_mlp(model, features)
        signal = trend_signal(rows[index], probabilities)
        if signal == "hold":
            index += 1
            continue
        direction = 1 if signal == "buy" else -1
        entry_index = index + 1
        entry = rows[entry_index]["open"]
        entry_spread = rows[entry_index].get("spread")
        if entry_spread is None:
            raise QuantDataError("Real bid/ask spread is missing; cost-aware backtesting is blocked.")
        entry = entry + entry_spread / 2 if direction > 0 else entry - entry_spread / 2
        stop_distance = max(rows[index]["atr"] * 1.5, entry * 0.0001)
        stop = entry - direction * stop_distance
        target = entry + direction * stop_distance * 2
        sizing = risk_position_size(
            equity=equity,
            entry_price=entry,
            stop_price=stop,
            risk_fraction=risk_fraction,
            contract_multiplier=contract_multiplier,
        )
        units = sizing["units"]
        if units <= 0:
            index += 1
            continue

        exit_index = min(len(rows) - 1, entry_index + max_holding_bars)
        exit_price = rows[exit_index]["close"]
        exit_reason = "time_limit"
        best_price = entry
        for cursor in range(entry_index, exit_index + 1):
            candle = rows[cursor]
            # If both levels are touched in one OHLC bar, assume the stop was hit first.
            if direction > 0:
                best_price = max(best_price, candle["high"])
                dynamic_stop = max(stop, best_price - candle["atr"] * 1.5) if candle.get("atr") else stop
                if candle["low"] <= dynamic_stop:
                    exit_index, exit_price, exit_reason = cursor, dynamic_stop, "stop_or_trailing_stop"
                    break
                if candle["high"] >= target:
                    exit_index, exit_price, exit_reason = cursor, target, "take_profit"
                    break
            else:
                best_price = min(best_price, candle["low"])
                dynamic_stop = min(stop, best_price + candle["atr"] * 1.5) if candle.get("atr") else stop
                if candle["high"] >= dynamic_stop:
                    exit_index, exit_price, exit_reason = cursor, dynamic_stop, "stop_or_trailing_stop"
                    break
                if candle["low"] <= target:
                    exit_index, exit_price, exit_reason = cursor, target, "take_profit"
                    break

        exit_spread = rows[exit_index].get("spread")
        if exit_spread is None:
            raise QuantDataError("Real bid/ask spread is missing; cost-aware backtesting is blocked.")
        exit_price = exit_price - exit_spread / 2 if direction > 0 else exit_price + exit_spread / 2
        gross_pnl = direction * (exit_price - entry) * units
        fees = (abs(entry * units) + abs(exit_price * units)) * commission_rate
        net_pnl = gross_pnl - fees
        equity += net_pnl
        peak_equity = max(peak_equity, equity)
        max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity)
        daily_loss = (day_start_equity - equity) / day_start_equity if day_start_equity else 0
        if daily_loss >= daily_loss_limit:
            daily_stopped = True
        trades.append({
            "direction": signal,
            "entry_time": rows[entry_index]["timestamp"],
            "exit_time": rows[exit_index]["timestamp"],
            "entry": entry,
            "exit": exit_price,
            "units": units,
            "net_pnl": net_pnl,
            "return_fraction": net_pnl / max(equity - net_pnl, 1e-12),
            "exit_reason": exit_reason,
            "mlp_probabilities": probabilities,
        })
        index = exit_index + 1

    net = [trade["net_pnl"] for trade in trades]
    wins = [value for value in net if value > 0]
    losses = [value for value in net if value < 0]
    total_return = equity / starting_equity - 1
    avg_return = sum(trade["return_fraction"] for trade in trades) / len(trades) if trades else None
    volatility = math.sqrt(sum((trade["return_fraction"] - avg_return) ** 2 for trade in trades) / max(1, len(trades) - 1)) if trades and avg_return is not None else None
    return {
        "window": {"start": rows[test_start]["timestamp"], "end": rows[-1]["timestamp"]},
        "bars": len(rows) - test_start,
        "starting_equity": starting_equity,
        "ending_equity": equity,
        "net_return": total_return,
        "max_drawdown": max_drawdown,
        "trade_count": len(trades),
        "win_rate": len(wins) / len(trades) if trades else None,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses and wins else None,
        "average_trade_return": avg_return,
        "trade_return_volatility": volatility,
        "risk_adjusted_return": avg_return / volatility if avg_return is not None and volatility and volatility > 0 else None,
        "daily_loss_limit": daily_loss_limit,
        "risk_fraction": risk_fraction,
        "commission_bps_assumption": commission_bps,
        "contract_multiplier_assumption": contract_multiplier,
        "spread_source": "provider_observed_bid_ask",
        "execution": "simulated_only",
        "trades": trades[-200:],
        "not_a_future_return_guarantee": True,
    }


def analyze_market(
    candles: Any,
    *,
    starting_equity: float,
    commission_bps: float = 0.0,
    contract_multiplier: float = 1.0,
) -> dict[str, Any]:
    """Run indicators, supervised candidate, Q-learning candidate, and OOS backtest."""
    rows = validate_candles(candles)
    if not math.isfinite(contract_multiplier) or contract_multiplier <= 0:
        raise QuantDataError("Contract multiplier must be positive and verified for this market.")
    model_result = train_direction_mlp(rows)
    q_result = train_q_learning(rows, commission_bps=commission_bps)
    backtest = run_backtest(
        rows,
        model_result,
        starting_equity=starting_equity,
        contract_multiplier=contract_multiplier,
        commission_bps=commission_bps,
    )
    latest = technical_indicators(rows)[-1]
    features = _features_at(technical_indicators(rows), len(rows) - 1)
    probabilities = predict_mlp(model_result["model"], features) if features else None
    return {
        "data": {
            "source": "provider_required",
            "bars": len(rows),
            "first_timestamp": rows[0]["timestamp"],
            "last_timestamp": rows[-1]["timestamp"],
            "spread_coverage": sum(row["spread"] is not None for row in rows) / len(rows),
        },
        "latest_indicators": {
            key: latest[key]
            for key in ("timestamp", "close", "rsi", "macd", "macd_signal", "atr", "supertrend", "trend", "ema20", "ema50", "momentum5", "volatility20", "zigzag")
        },
        "mlp": {key: value for key, value in model_result.items() if key != "model"},
        "latest_probabilities": probabilities,
        "q_learning": q_result,
        "backtest": backtest,
        "candidate_status": "research_only_not_promoted",
        "assumptions": {
            "contract_multiplier": contract_multiplier,
            "commission_basis_points": commission_bps,
            "spread": "Capital.com observed close bid/ask; applied conservatively to simulated fills",
            "zigzag": "retrospective display only; excluded from model features and trading signals",
            "rl": "offline research policy only; never connected to broker execution",
        },
    }
