from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings


class AdamSettings(BaseSettings):
    """Global configuration for Adam's Theory stock picker."""

    # --- Data paths ---
    DATA_DIR: Path = Path("output/parquet")
    RESULTS_DIR: Path = Path("output/results")
    REPORTS_DIR: Path = Path("output/reports")
    ALL_STOCKS_PATH: Path = Path("output/all_stocks.parquet")  # Consolidated single-file store
    STOCK_LIST_PATH: Path = Path("output/stock_list.csv")      # Stock universe cache

    # --- Adam's Theory core parameters ---
    LOOKBACK_BARS: int = 20          # Center symmetry projection lookback window
    ADX_THRESHOLD: float = 25.0      # Minimum ADX for strong trend confirmation
    ADX_WEAK_THRESHOLD: float = 20.0 # Minimum ADX for weak trend (needs 2+ clues)
    ER_MIN: float = 0.3              # Minimum Efficiency Ratio for valid trend
    ER_PERIOD: int = 20              # Period for Efficiency Ratio calculation
    ADX_PERIOD: int = 14             # ADX calculation period
    ATR_PERIOD: int = 14             # ATR calculation period

    # --- Detection thresholds ---
    BREAKOUT_LOOKBACK: int = 20      # Bars to consider for breakout high
    BREAKOUT_THRESHOLD_PCT: float = 0.98  # Close must exceed this fraction of lookback high
    TREND_CHANGE_LOOKBACK: int = 40  # Longer window for trend change detection
    TREND_CHANGE_RECENT: int = 15    # Recent window for swing low/high identification
    RANGE_EXPANSION_MULTIPLE: float = 1.5  # Current range vs average range multiplier
    GAP_MIN_PCT: float = 0.5         # Minimum gap % to qualify as range expansion

    # --- Stock filtering (pre-screen) ---
    MIN_PRICE: float = 3.0           # Exclude penny stocks below this price (RMB)
    MIN_VOLUME_RATIO: float = 0.3    # Minimum 5-day volume ratio for liquidity
    MIN_LISTING_DAYS: int = 60       # Stock must have at least this many trading days
    MAX_STOCKS_TO_ANALYZE: int = 200 # Pre-screen to top N candidates for deep analysis

    # --- Risk management ---
    MAX_RISK_SCORE: float = 7.0      # Max acceptable risk score (1-10 scale)
    STOP_LOSS_ATR_MULTIPLE: float = 2.0  # Stop = entry - N * ATR

    # --- API / Rate limiting ---
    AKSHARE_DELAY_MIN: float = 0.5   # Minimum seconds between akshare API calls
    AKSHARE_DELAY_MAX: float = 2.0   # Maximum seconds
    PARALLEL_WORKERS: int = 4        # Maximum concurrent fetch workers

    # --- Reporting ---
    TOP_N_RECOMMENDATIONS: int = 20  # Number of recommendations to output

    # --- Backtesting ---
    BACKTEST_START: str = "2023-01-01"
    BACKTEST_END: str = "2024-12-31"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "case_sensitive": False}


# Singleton
settings = AdamSettings()


def ensure_dirs() -> None:
    """Create output directories if they don't exist."""
    for d in [settings.DATA_DIR, settings.RESULTS_DIR, settings.REPORTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
