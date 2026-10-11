"""Small SQLite cache for provider candles and research reports.

On a free Hugging Face Space this file is local to the running container and
is not a durable backup. Set QUANT_SQLITE_PATH to a mounted persistent path or
export records elsewhere if long-term retention is required.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class QuantStore:
    def __init__(self, path: str | None = None):
        default_path = Path(__file__).resolve().parent / "quant_data" / "market_research.sqlite3"
        configured = path or os.getenv("QUANT_SQLITE_PATH") or str(default_path)
        self.path = Path(configured)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS market_candles (
                    epic TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL,
                    spread REAL,
                    source TEXT NOT NULL CHECK(source = 'Capital.com'),
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY(epic, resolution, timestamp)
                );
                CREATE INDEX IF NOT EXISTS market_candles_time_idx
                    ON market_candles(epic, resolution, timestamp);
                CREATE TABLE IF NOT EXISTS quant_runs (
                    id TEXT PRIMARY KEY,
                    epic TEXT NOT NULL,
                    resolution TEXT NOT NULL,
                    source TEXT NOT NULL CHECK(source = 'Capital.com'),
                    candle_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    report_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS quant_runs_created_idx
                    ON quant_runs(created_at DESC);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def save_candles(
        self,
        epic: str,
        resolution: str,
        candles: list[dict[str, Any]],
        *,
        source: str,
    ) -> int:
        if source != "Capital.com":
            raise ValueError("Only verified Capital.com market data can be stored.")
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                epic,
                resolution,
                candle["timestamp"],
                candle["open"],
                candle["high"],
                candle["low"],
                candle["close"],
                candle.get("volume"),
                candle.get("spread"),
                source,
                now,
            )
            for candle in candles
        ]
        with self._connection() as connection:
            connection.executemany(
                """
                INSERT INTO market_candles
                    (epic, resolution, timestamp, open, high, low, close, volume, spread, source, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(epic, resolution, timestamp) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close,
                    volume=excluded.volume, spread=excluded.spread, source=excluded.source,
                    fetched_at=excluded.fetched_at
                """,
                rows,
            )
            connection.execute(
                """
                DELETE FROM market_candles
                WHERE epic = ? AND resolution = ? AND timestamp NOT IN (
                    SELECT timestamp FROM market_candles
                    WHERE epic = ? AND resolution = ?
                    ORDER BY timestamp DESC LIMIT 10000
                )
                """,
                (epic, resolution, epic, resolution),
            )
        return len(rows)

    def load_candles(self, epic: str, resolution: str, limit: int = 1_000) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 10_000))
        with self._connection() as connection:
            records = connection.execute(
                """
                SELECT timestamp, open, high, low, close, volume, spread
                FROM market_candles
                WHERE epic = ? AND resolution = ?
                ORDER BY timestamp DESC LIMIT ?
                """,
                (epic, resolution, bounded_limit),
            ).fetchall()
        return [dict(record) for record in reversed(records)]

    def save_run(
        self,
        run_id: str,
        epic: str,
        resolution: str,
        candle_count: int,
        report: dict[str, Any],
        *,
        source: str,
    ) -> None:
        if source != "Capital.com":
            raise ValueError("Only reports built from verified Capital.com data can be stored.")
        created_at = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO quant_runs(id, epic, resolution, source, candle_count, created_at, report_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, epic, resolution, source, candle_count, created_at, json.dumps(report, allow_nan=False)),
            )
            connection.execute(
                "DELETE FROM quant_runs WHERE id NOT IN (SELECT id FROM quant_runs ORDER BY created_at DESC LIMIT 100)"
            )

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 100))
        with self._connection() as connection:
            records = connection.execute(
                "SELECT id, epic, resolution, source, candle_count, created_at, report_json "
                "FROM quant_runs ORDER BY created_at DESC LIMIT ?",
                (bounded_limit,),
            ).fetchall()
        return [
            {
                "id": record["id"],
                "epic": record["epic"],
                "resolution": record["resolution"],
                "source": record["source"],
                "candle_count": record["candle_count"],
                "created_at": record["created_at"],
                "report": json.loads(record["report_json"]),
            }
            for record in records
        ]


quant_store = QuantStore()
