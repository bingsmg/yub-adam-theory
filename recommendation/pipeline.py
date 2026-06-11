"""
Main orchestration pipeline for the daily recommendation workflow.

Flow:
  1. Fetch stock universe + pre-screen candidates
  2. Fetch/update historical data for candidates
  3. Run Adam's Theory signal detection on each
  4. Score, rank, and filter signals
  5. Generate explanations
  6. Output results via reporters
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from loguru import logger

from config.schema import AdamSignal, DailyRecommendation
from config.settings import settings, ensure_dirs
from data.fetcher import fetch_index_hist, fetch_stock_hist
from data.store import ParquetStore
from data.symbols import load_stock_universe, pre_screen_candidates
from data.trading_calendar import is_trading_day, most_recent_trading_day, next_trading_day
from recommendation.explainer import build_explanation, brief_reason
from recommendation.ranking import select_top_recommendations
from signals.detector import detect_signal
from signals.filters import filter_new_listings


class RecommendationPipeline:
    """End-to-end daily stock recommendation pipeline."""

    def __init__(self):
        ensure_dirs()
        self.store = ParquetStore()
        self.universe: pd.DataFrame | None = None

    def run(
        self,
        limit_stocks: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        use_cache_only: bool = False,
    ) -> DailyRecommendation:
        """
        Execute the full daily recommendation pipeline.

        Args:
            limit_stocks: Max stocks to analyze (default from settings).
            start_date: Start date for historical data fetch.
            end_date: End date (default: today).
            use_cache_only: If True, skip API calls and use only local data.

        Returns:
            DailyRecommendation with ranked signals.
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=730)).strftime("%Y%m%d")

        if limit_stocks is None:
            limit_stocks = settings.MAX_STOCKS_TO_ANALYZE

        # Determine the target trading day
        today = date.today()
        if is_trading_day(today):
            market_date = today
        else:
            market_date = most_recent_trading_day(today)

        logger.info("="*60)
        logger.info("Adam's Theory Stock Recommendation Pipeline")
        logger.info("Target trading day: {} ({})", market_date, market_date.strftime("%A"))
        logger.info("="*60)

        # ── Step A: Market context ──────────────────────────────
        logger.info("--- Step A: Market Context ---")
        index_adx, market_regime = self._assess_market_regime()
        logger.info("CSI 300 ADX={:.1f}, Regime: {}", index_adx, market_regime)

        # ── Step B: Load stock universe ─────────────────────────
        logger.info("--- Step B: Stock Universe ---")
        if not use_cache_only:
            try:
                self.universe = load_stock_universe(self.store)
            except Exception as e:
                logger.warning("Failed to load spot list: {}. Trying store cache...", e)
                self.universe = None

        if self.universe is None:
            # Fall back to cached metadata
            meta = self.store.all_meta()
            if meta.empty:
                raise RuntimeError("No stock data available. Run init_backfill.py first.")
            self.universe = meta

        # ── Step C: Pre-screen candidates ───────────────────────
        logger.info("--- Step C: Pre-screen Candidates ---")
        candidates = pre_screen_candidates(self.universe, self.store, top_n=limit_stocks)
        candidates = filter_new_listings(candidates, self.store)
        logger.info("Candidates for analysis: {}", len(candidates))

        # ── Step D: Fetch/update data & detect signals ──────────
        logger.info("--- Step D: Signal Detection ---")
        signals: list[AdamSignal] = []

        for i, c in enumerate(candidates):
            sym = c["code"]
            name = c.get("name", "")
            mcap = c.get("market_cap")

            if i > 0 and i % 20 == 0:
                logger.info("Detection progress: {}/{} ({:.0f}%)", i, len(candidates), 100 * i / len(candidates))

            # Check if we have recent data cached
            latest_stored = self.store.get_latest_date(sym)

            # Determine if we need to fetch
            need_fetch = (
                not use_cache_only
                and (latest_stored is None or latest_stored < market_date)
            )

            if need_fetch:
                df = fetch_stock_hist(
                    sym, start_date=start_date, end_date=end_date, adjust="qfq"
                )
                if df is not None:
                    # Store/update
                    if latest_stored is None:
                        self.store.save(sym, df)
                    else:
                        self.store.append(sym, df)
            else:
                # Load from cache
                df = self.store.load_range(
                    sym,
                    start=market_date - timedelta(days=730),  # 2 years back
                    end=market_date,
                )

            if df is None or df.empty:
                continue

            # Run detection
            signal = detect_signal(df, symbol=sym, name=name, signal_date=market_date, market_cap=mcap)
            if signal is not None:
                signals.append(signal)

        logger.info("Signals detected: {} from {} candidates", len(signals), len(candidates))

        # ── Step E: Rank & select ───────────────────────────────
        logger.info("--- Step E: Ranking ---")
        recommendations = select_top_recommendations(signals)

        # Generate explanations
        for s in recommendations:
            s.reason = build_explanation(s)

        # ── Step F: Build result ────────────────────────────────
        result = DailyRecommendation(
            generated_at=datetime.now(),
            market_date=market_date,
            total_stocks_analyzed=len(candidates),
            total_signals_found=len(signals),
            recommendations=recommendations,
            index_adx=index_adx,
            market_regime_desc=market_regime,
        )

        # ── Step G: Save CSV ────────────────────────────────────
        self._save_csv(result)

        logger.info("Pipeline complete. {} recommendations ready.", len(recommendations))
        return result

    def _assess_market_regime(self) -> tuple[float, str]:
        """Fetch CSI 300 data and compute ADX for market-wide context."""
        try:
            df = fetch_index_hist(symbol="000300", start_date="20240101")
            if df is not None and len(df) >= 40:
                from indicators.market_regime import compute_adx
                adx_df = compute_adx(df["high"], df["low"], df["close"], period=14)
                current_adx = float(adx_df.iloc[-1][f"ADX_14"])
                if current_adx >= 25:
                    regime = "Trending"
                elif current_adx >= 20:
                    regime = "Moderate Trend"
                else:
                    regime = "Ranging / Choppy"
                return round(current_adx, 1), regime
        except Exception as e:
            logger.warning("Market regime assessment failed: {}", e)
        return 0.0, "Unknown"

    def _save_csv(self, result: DailyRecommendation) -> None:
        """Save recommendations to CSV."""
        results_dir = Path(settings.RESULTS_DIR)
        results_dir.mkdir(parents=True, exist_ok=True)

        csv_path = results_dir / f"recommendations_{result.market_date.isoformat()}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "rank", "symbol", "name", "close", "clues", "clue_count", "adx", "er",
                "trend_strength", "risk_score", "projected_direction", "stop_loss",
                "proj_entry_1d", "volume_ratio", "reason",
            ])
            for i, rec in enumerate(result.recommendations, 1):
                clue_str = "|".join(c.clue_type for c in rec.clues)
                writer.writerow([
                    i, rec.symbol, rec.name, rec.current_close, clue_str,
                    len(rec.clues), rec.adx, rec.efficiency_ratio, rec.trend_strength,
                    rec.risk_score, rec.projection.projected_direction, rec.stop_loss_price,
                    rec.projected_entry_price, rec.volume_ratio, rec.reason,
                ])
        logger.info("CSV saved: {}", csv_path)
