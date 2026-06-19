"""
Daily pipeline — encapsulates the full Adam's Theory workflow.

Orchestrates: update → filter → detect → score → rank → explain → report
All steps are individually callable for testing and customization.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pandas as pd
from loguru import logger

from config.schema import AdamSignal, DailyRecommendation
from config.settings import settings
from data.store import load_stock, load_all_stocks, get_latest_date
from data.filters import get_stock_list, filter_active_stocks
from data.pipeline import update_latest_days
from signals.detector import detect_signal
from signals.scorer import rank_signals
from recommendation.ranking import select_top_recommendations
from recommendation.explainer import build_explanation
from indicators.market_regime import detect_market_regime, describe_market_regime


def _build_market_proxy(master: pd.DataFrame) -> pd.DataFrame | None:
    """Build a synthetic market proxy DataFrame from all stocks' data.

    Groups by date and computes equal-weighted average OHLCV across all stocks
    to create a single "market" time series for regime detection.

    Args:
        master: Full DataFrame from load_all_stocks() with columns:
            date, open, high, low, close, volume, symbol.

    Returns:
        DataFrame with date index and ohlcv columns, or None if insufficient data.
    """
    if master is None or master.empty:
        return None
    if "date" not in master.columns:
        return None

    required = ["open", "high", "low", "close", "volume"]
    if not all(c in master.columns for c in required):
        return None

    try:
        grouped = master.groupby("date")
        proxy = pd.DataFrame({
            "open": grouped["open"].mean(),
            "high": grouped["high"].mean(),
            "low": grouped["low"].mean(),
            "close": grouped["close"].mean(),
            "volume": grouped["volume"].mean(),
        })
        proxy = proxy.sort_index()
        if len(proxy) < 20:
            return None
        return proxy
    except Exception:
        return None


class DailyPipeline:
    """Encapsulates the complete daily recommendation workflow.

    Usage:
        pipeline = DailyPipeline()
        result = pipeline.run(limit=200, skip_update=False)
        # result is a DailyRecommendation ready for reporting

    Individual steps can be called directly for testing:
        pipeline.update_data()
        candidates = pipeline.filter_candidates(limit=200)
        signals = pipeline.detect_signals(candidates)
        result = pipeline.rank_and_explain(signals)
    """

    def __init__(self, fetcher=None):
        self.fetcher = fetcher
        self._stock_list: pd.DataFrame | None = None

    # ── Step 1: Update data ──────────────────────────────────────────

    def update_data(self) -> pd.DataFrame:
        """Fetch latest trading days and return full master DataFrame.

        On failure, falls back to loading cached data.
        """
        logger.info("Updating data to latest trading day...")
        try:
            stock_list = get_stock_list(self.fetcher)
            stock_list.to_csv(settings.STOCK_LIST_PATH, index=False)
            self._stock_list = stock_list
        except Exception:
            logger.warning("Could not fetch stock list, using cached data")
            try:
                master = load_all_stocks()
                stock_list = master[['symbol', 'name']].drop_duplicates()
                self._stock_list = stock_list
            except Exception:
                raise RuntimeError("No data available. Run init_backfill.py first.")

        return update_latest_days(self._stock_list, fetcher=self.fetcher)

    def update_data_or_skip(self, skip_update: bool = False) -> pd.DataFrame:
        """Update data or skip (using cached data only)."""
        if skip_update:
            logger.info("Skipping data fetch (--no-update)")
            try:
                return load_all_stocks()
            except FileNotFoundError:
                raise RuntimeError("No cached data. Run init_backfill.py first or remove --no-update.")
        return self.update_data()

    # ── Step 2: Filter candidates ────────────────────────────────────

    def filter_candidates(self, master: pd.DataFrame, limit: int | None = None) -> list[dict]:
        """Pre-screen active stocks for analysis."""
        candidates = filter_active_stocks(master, top_n=limit)
        logger.info(f"Active candidates for analysis: {len(candidates)}")
        return candidates

    # ── Step 3: Detect signals ───────────────────────────────────────

    def detect_signals(self, candidates: list[dict]) -> list[AdamSignal]:
        """Run Adam's Theory detection on all candidates."""
        signals: list[AdamSignal] = []
        total = len(candidates)

        for i, c in enumerate(candidates):
            sym = c['symbol']
            name = c.get('name', '')

            if i > 0 and i % 20 == 0:
                logger.info(f"Detection: {i}/{total}")

            try:
                df_stock = load_stock(sym)
            except FileNotFoundError:
                logger.warning(f"No data file for {sym}, skipping")
                continue

            if len(df_stock) < 60:
                continue

            signal = detect_signal(df_stock, symbol=sym, name=name)
            if signal:
                signals.append(signal)

        logger.info(f"Signals found: {len(signals)}/{total}")
        return signals

    # ── Step 4: Rank and explain ─────────────────────────────────────

    def rank_and_explain(self, signals: list[AdamSignal]) -> tuple[list[AdamSignal], str | None]:
        """Rank signals, apply one-question rule, build explanations.

        Returns (ranked_signals, latest_date_str).
        """
        recommendations = select_top_recommendations(signals)
        for s in recommendations:
            s.reason = build_explanation(s)

        try:
            latest = get_latest_date()
            latest_str = latest.date().isoformat() if latest else datetime.now().strftime('%Y-%m-%d')
        except Exception:
            latest_str = datetime.now().strftime('%Y-%m-%d')

        return recommendations, latest_str

    # ── Step 5: Save CSV ─────────────────────────────────────────────

    def save_csv(self, recommendations: list[AdamSignal], latest_str: str) -> Path:
        """Save recommendations to CSV. Returns the file path."""
        results_dir = Path(settings.RESULTS_DIR)
        results_dir.mkdir(parents=True, exist_ok=True)
        csv_path = results_dir / f"recommendations_{latest_str}.csv"

        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["rank", "symbol", "name", "close", "clues", "clue_count",
                             "risk_score", "projected_direction", "stop_loss", "volume_ratio", "reason"])
            for i, rec in enumerate(recommendations, 1):
                clue_str = "|".join(c.clue_type for c in rec.clues)
                writer.writerow([i, rec.symbol, rec.name, rec.current_close, clue_str,
                                 len(rec.clues), rec.risk_score, rec.projection.projected_direction,
                                 rec.stop_loss_price, rec.volume_ratio, rec.reason])

        logger.info(f"Saved to {csv_path}")
        return csv_path

    # ── Full run ─────────────────────────────────────────────────────

    def run(
        self,
        limit: int | None = None,
        skip_update: bool = False,
    ) -> DailyRecommendation:
        """Execute the full daily pipeline end-to-end.

        Args:
            limit: Max active stocks to analyze (None = all).
            skip_update: If True, skip data fetch, use cached only.

        Returns:
            DailyRecommendation ready for reporting.
        """
        # 1. Update data
        master = self.update_data_or_skip(skip_update)

        # 2. Filter active stocks
        candidates = self.filter_candidates(master, limit)

        # 3. Detect signals
        signals = self.detect_signals(candidates)

        # 4. Rank and explain
        recommendations, latest_str = self.rank_and_explain(signals)

        # 5. Save CSV
        self.save_csv(recommendations, latest_str)

        # 6. Detect market regime
        try:
            # Use a broad-market proxy: average of all candidate stocks' latest data
            regime = "ranging"  # Default
            regime_desc = describe_market_regime(regime)
            # If we have a master DataFrame, compute regime on the aggregate
            sample_close = master["close"] if "close" in master.columns else None
            if sample_close is not None and len(sample_close) > 0:
                # Build a synthetic "market" OHLCV from all stocks' latest snapshot
                market_df = _build_market_proxy(master)
                if market_df is not None and len(market_df) >= 20:
                    regime = detect_market_regime(market_df)
                    regime_desc = describe_market_regime(regime)
            logger.info(f"Market regime: {regime} — {regime_desc}")
        except Exception:
            regime_desc = "震荡盘整 — 无法判定市场体制"
            logger.warning("Could not detect market regime, using default")

        # 7. Build result
        result = DailyRecommendation(
            generated_at=datetime.now(),
            market_date=datetime.strptime(latest_str, '%Y-%m-%d') if latest_str else datetime.now(),
            total_stocks_analyzed=len(candidates),
            total_signals_found=len(signals),
            recommendations=recommendations,
            market_regime_desc=regime_desc,
        )

        n = len(recommendations)
        if n > 0:
            logger.info(f"{n} buy recommendations for {latest_str}")
        else:
            logger.info(f"No buy signals for {latest_str}")

        return result
