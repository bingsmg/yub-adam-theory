from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings


class AdamSettings(BaseSettings):
    """Global configuration for Adam's Theory stock picker."""

    # --- Data paths ---
    RESULTS_DIR: Path = Path("output/results")
    REPORTS_DIR: Path = Path("output/reports")
    ALL_STOCKS_PATH: Path = Path("output/all_stocks.parquet")  # Consolidated single-file store (legacy backup)
    DAILY_DIR: Path = Path("output/daily")                     # Date-partitioned parquet files (legacy)
    STOCKS_DIR: Path = Path("output/stocks")                   # Stock-partitioned parquet files (primary)
    STOCK_LIST_PATH: Path = Path("output/stock_list.csv")      # Stock universe cache

    # --- Adam's Theory core parameters ---
    LOOKBACK_BARS: int = 20          # Center symmetry projection lookback window

    # --- Detection thresholds ---
    BREAKOUT_LOOKBACK: int = 20      # Bars to consider for breakout high
    TREND_CHANGE_LOOKBACK: int = 40  # Longer window for trend change detection
    TREND_CHANGE_RECENT: int = 15    # Recent window for swing low/high identification
    RANGE_EXPANSION_MULTIPLE: float = 1.5  # Current range vs average range multiplier
    GAP_MIN_PCT: float = 0.5         # Minimum gap % to qualify as range expansion

    # --- Stock filtering (pre-screen) ---
    MIN_PRICE: float = 3.0           # Exclude penny stocks below this price (RMB)
    MAX_STOCKS_TO_ANALYZE: int = 5000  # Pre-screen to top N candidates (5000 = effectively all)

    # --- Board permissions ---
    # Set to True if you have trading permission for these boards.
    # Chinese A-share board prefix mapping:
    #   Main (default): 600-603,605, 000-003     — always allowed
    #   创业板 ChiNext: 300, 301                   — requires separate permission
    #   科创板 STAR Market: 688, 689               — requires separate permission
    #   北交所 BSE: 8xxxxx, 4xxxxx                 — requires separate permission
    ALLOW_CHINEXT: bool = True        # 创业板 (300/301xxx)
    ALLOW_STAR_MARKET: bool = True    # 科创板 (688/689xxx)
    ALLOW_BSE: bool = False           # 北交所 (8/4xxxxx) — usually excluded

    # --- Risk management ---
    MAX_RISK_SCORE: float = 7.0      # Max acceptable risk score (1-10 scale)

    # --- Data source selection ---
    # Source priority order: first available wins when strategy is "priority".
    # Built-in sources: "tencent", "akshare", "baostock", "efinance"
    # NOTE: "tencent" uses Tencent's free API (via akshare) — less aggressive
    # rate limiting than EastMoney. "akshare" (EastMoney) may be blocked.
    DATA_SOURCE_ORDER: list[str] = ["tencent", "baostock"]  # tencent primary (Tencent API), baostock fallback
    DATA_SOURCE_STRATEGY: str = "priority"      # "priority" | "fastest_first"

    # --- Data fetching parameters ---
    FETCH_DELAY_SECONDS: float = 1.0   # Min delay between sequential requests (sequential mode, 1s is safe)
    FETCH_MAX_WORKERS: int = 1         # Sequential fetch. Thread pool hangs with akshare multi-threaded.
    FETCH_RETRY_COUNT: int = 3         # Max retries per stock

    # --- Feishu notification ---
    FEISHU_WEBHOOK_URL: str = ""     # Feishu bot webhook URL for daily push

    # --- Scoring ---
    # Weights for compute_quality_score: [condition_count, projection, volume]
    SCORE_WEIGHTS: list[float] = [0.50, 0.30, 0.20]

    # --- Ranking ---
    # One-question rule: keep-N thresholds
    RANK_KEEP_ALL_IF_LE: int = 5      # Keep all if <= this many signals
    RANK_KEEP_FRAC_MID: float = 0.8   # Keep fraction when 6-15 signals
    RANK_KEEP_FRAC_HIGH: float = 0.7  # Keep fraction when >15 signals
    RANK_MID_THRESHOLD: int = 15      # Boundary between mid and high signal counts
    RANK_MIN_KEEP_MID: int = 5        # Minimum keep when mid count
    RANK_MIN_KEEP_HIGH: int = 10      # Minimum keep when high count

    # --- Reporting ---
    TOP_N_RECOMMENDATIONS: int = 20  # Number of recommendations to output

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "case_sensitive": False, "extra": "ignore"}


# Singleton
settings = AdamSettings()


def ensure_dirs() -> None:
    """Create output directories if they don't exist."""
    for d in [settings.RESULTS_DIR, settings.REPORTS_DIR, settings.DAILY_DIR, settings.STOCKS_DIR]:
        d.mkdir(parents=True, exist_ok=True)
