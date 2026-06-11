"""Parquet-based data store with SQLite metadata tracking."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from loguru import logger

from config.settings import settings


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS stock_meta (
    symbol      TEXT PRIMARY KEY,
    name        TEXT,
    exchange    TEXT,
    market_cap  REAL,
    listing_date TEXT,
    last_updated TEXT,
    data_start   TEXT,
    total_bars   INTEGER DEFAULT 0
);
"""


class ParquetStore:
    """
    On-disk storage: one Parquet file per stock + SQLite metadata.

    Directory structure:
        output/parquet/600519.parquet
        output/parquet/000001.parquet

    The SQLite metadata DB lives at output/parquet/_meta.db
    """

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = Path(data_dir or settings.DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "_meta.db"
        self._init_db()

    # ── DB helpers ──────────────────────────────────────────────────

    def _init_db(self) -> None:
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute(_SCHEMA_SQL)
            conn.commit()

    def _file_path(self, symbol: str) -> Path:
        return self.data_dir / f"{symbol}.parquet"

    # ── Read ────────────────────────────────────────────────────────

    def has_data(self, symbol: str) -> bool:
        return self._file_path(symbol).exists()

    def load(self, symbol: str) -> pd.DataFrame | None:
        """Load full history for a symbol. Returns None if not found."""
        fp = self._file_path(symbol)
        if not fp.exists():
            return None
        return pd.read_parquet(fp)

    def load_range(
        self, symbol: str, start: date | None = None, end: date | None = None
    ) -> pd.DataFrame | None:
        """Load history for a symbol filtered by date range."""
        df = self.load(symbol)
        if df is None:
            return None
        if "date" not in df.columns:
            logger.warning("{} parquet missing 'date' column — returning raw", symbol)
            return df
        df["date"] = pd.to_datetime(df["date"])
        if start:
            df = df[df["date"] >= pd.Timestamp(start)]
        if end:
            df = df[df["date"] <= pd.Timestamp(end)]
        return df

    def get_latest_date(self, symbol: str) -> date | None:
        """Return the most recent date in stored data, or None."""
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT last_updated FROM stock_meta WHERE symbol = ?", (symbol,)
            ).fetchone()
        if row and row[0]:
            return datetime.fromisoformat(row[0]).date()
        # Fallback: peek at parquet
        df = self.load(symbol)
        if df is not None and not df.empty and "date" in df.columns:
            latest = pd.to_datetime(df["date"]).max()
            return latest.date()
        return None

    def get_start_date(self, symbol: str) -> date | None:
        """Return the earliest date in stored data, or None."""
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute(
                "SELECT data_start FROM stock_meta WHERE symbol = ?", (symbol,)
            ).fetchone()
        if row and row[0]:
            return datetime.fromisoformat(row[0]).date()
        return None

    def list_symbols(self) -> list[str]:
        """Return all symbols that have data stored."""
        rows = []
        with sqlite3.connect(str(self.db_path)) as conn:
            rows = conn.execute("SELECT symbol FROM stock_meta").fetchall()
        if rows:
            return [r[0] for r in rows]
        # Fallback: glob parquet files
        parquet_files = list(self.data_dir.glob("*.parquet"))
        return [p.stem for p in parquet_files if not p.name.startswith("_")]

    # ── Write ───────────────────────────────────────────────────────

    def save(self, symbol: str, df: pd.DataFrame) -> None:
        """Save a DataFrame as parquet. Overwrites if exists."""
        fp = self._file_path(symbol)
        # Ensure date column is present
        if "date" not in df.columns and df.index.name != "date":
            logger.warning("DataFrame for {} has no 'date' column", symbol)
        df.to_parquet(fp, index=False)
        logger.debug("Saved {} → {} rows", symbol, len(df))

    def append(self, symbol: str, new_df: pd.DataFrame) -> None:
        """
        Append new rows, deduplicating on 'date'.
        If no existing file, just saves.
        """
        existing = self.load(symbol)
        if existing is not None and not existing.empty:
            combined = pd.concat([existing, new_df], ignore_index=True)
            if "date" in combined.columns:
                combined = combined.drop_duplicates(subset=["date"], keep="last")
            combined = combined.sort_values("date", ignore_index=True)
        else:
            combined = new_df

        self.save(symbol, combined)

    def update_meta(
        self,
        symbol: str,
        name: str = "",
        exchange: str = "",
        market_cap: float | None = None,
        listing_date: date | None = None,
    ) -> None:
        """Insert or update metadata for a symbol."""
        now_iso = date.today().isoformat()
        with sqlite3.connect(str(self.db_path)) as conn:
            # Get existing row
            row = conn.execute(
                "SELECT symbol FROM stock_meta WHERE symbol = ?", (symbol,)
            ).fetchone()
            if row:
                conn.execute(
                    """UPDATE stock_meta SET name=?, exchange=?, market_cap=?,
                       listing_date=COALESCE(?, listing_date), last_updated=?""",
                    (name or "", exchange, market_cap,
                     listing_date.isoformat() if listing_date else None, now_iso),
                )
            else:
                conn.execute(
                    """INSERT INTO stock_meta (symbol, name, exchange, market_cap,
                       listing_date, last_updated) VALUES (?,?,?,?,?,?)""",
                    (symbol, name or "", exchange, market_cap,
                     listing_date.isoformat() if listing_date else None, now_iso),
                )
            conn.commit()

    # ── Bulk / convenience ──────────────────────────────────────────

    def all_meta(self) -> pd.DataFrame:
        """Return all metadata rows as a DataFrame."""
        with sqlite3.connect(str(self.db_path)) as conn:
            return pd.read_sql_query("SELECT * FROM stock_meta", conn)
