"""
信号检测流水线 —— 纯亚当理论。

对每只股票：
  1. 加载 OHLCV 数据
  2. 运行三个条件检测器（突破、趋势改变、缺口/宽幅）
  3. 要求 >=2 个条件满足以确认买入信号
  4. 寻找最近摆动低点下方的结构止损位
  5. 计算中心对称投影作为视觉确认
  6. 构建包含完整推理数据的 AdamSignal

门控逻辑中不使用技术指标（ADX、RSI 等）。
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
from loguru import logger

from config.schema import AdamSignal
from config.settings import settings
from indicators.adams_theory import (
    compute_center_symmetry_projection,
    detect_all_three_conditions,
    check_buy_signal,
    find_structural_stop,
)


def detect_signal(
    df: pd.DataFrame,
    symbol: str,
    name: str = "",
    signal_date: date | datetime | None = None,
    market_cap: float | None = None,
) -> AdamSignal | None:
    """
    对单只股票运行纯亚当理论信号检测。

    参数:
        df: 包含 [open, high, low, close, volume] 的 OHLCV DataFrame。
        symbol: 6 位股票代码。
        name: 股票中文名称。
        signal_date: 分析日期（默认：df 中的最后一个日期）。
        market_cap: 市值为上下文提供参考。

    返回:
        若 >=2 个条件满足则返回 AdamSignal，否则返回 None。
    """
    min_bars = settings.TREND_CHANGE_LOOKBACK + settings.LOOKBACK_BARS + 5
    if len(df) < min_bars:
        logger.debug("{}: insufficient data ({} < {} bars)", symbol, len(df), min_bars)
        return None

    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        logger.error("{}: missing columns {}", symbol, missing)
        return None

    df = df.dropna(subset=["open", "high", "low", "close"])
    if len(df) < min_bars:
        return None

    if signal_date is None:
        signal_date = pd.to_datetime(df["date"].iloc[-1]).date() if "date" in df.columns else date.today()

    # ── 1. 检测三个条件 ────────────────────────────
    clues = detect_all_three_conditions(df)

    # ── 2. 要求 >=2 个条件满足 ──────────────────────────────────────
    is_buy, gate_reason = check_buy_signal(clues)

    if not is_buy:
        logger.debug("{}: {} — 无信号", symbol, gate_reason)
        return None

    logger.info("{} [{}]: {} — {} 个条件满足", symbol, name, gate_reason, len(clues))

    # ── 3. 中心对称投影 ────────────────────────────
    try:
        projection = compute_center_symmetry_projection(df, lookback=settings.LOOKBACK_BARS)
    except Exception as e:
        logger.warning("{}: 投影计算失败 — {}", symbol, e)
        projection = None

    # ── 4. 结构止损 ──────────────────────────────────
    current_close = float(df["close"].iloc[-1])
    stop_loss = find_structural_stop(df, lookback=40)
    stop_pct = (current_close - stop_loss) / current_close * 100

    # ── 5. ATR 参考值（不参与门控，仅作上下文） ──────
    current_atr = round(float(df["high"].iloc[-1] - df["low"].iloc[-1]), 2)

    # ── 6. 成交量上下文 ────────────────────────────────────────
    if len(df) >= 21:
        vol_ratio = float(df["volume"].iloc[-1] / df["volume"].iloc[-21:-1].mean())
    else:
        vol_ratio = 1.0

    # ── 7. 计算简单风险评分（1-10） ──────────────────────
    # 仅基于：止损距离、投影收敛度、线索数量
    risk_score = _simple_risk_score(stop_pct, projection, len(clues))

    if risk_score > settings.MAX_RISK_SCORE:
        logger.info("{}: 信号被抑制 — 风险 {:.1f} > 最大 {:.1f}", symbol, risk_score, settings.MAX_RISK_SCORE)
        return None

    # ── 8. 构建信号 ──────────────────────────────────────────
    signal = AdamSignal(
        symbol=str(symbol),
        name=name,
        signal_date=signal_date,
        direction="buy",
        projection=projection or _empty_projection(),
        clues=clues,
        atr=round(current_atr, 2),
        risk_score=round(risk_score, 1),
        stop_loss_price=stop_loss,
        projected_entry_price=round(current_close, 2),
        current_close=round(current_close, 2),
        volume_ratio=round(vol_ratio, 2),
        market_cap=market_cap,
        reason="",  # 由解释器填充
    )

    return signal


def _simple_risk_score(stop_pct: float, projection, clue_count: int) -> float:
    """
    基于结构因素的简单风险评分。

    - 止损距离：止损越紧（2-5%）= 风险越低
    - 投影收敛度：越收敛 = 风险越低
    - 线索数量：3 条线索比 2 条风险更低
    """
    score = 5.0  # 中性基准

    # 止损距离因子
    if stop_pct <= 2.0:
        score -= 1.5  # 止损较紧，触发时损失较小
    elif stop_pct <= 4.0:
        score -= 0.5
    elif stop_pct >= 8.0:
        score += 1.5  # 止损较宽，风险资金更多
    elif stop_pct >= 5.0:
        score += 0.5

    # 投影因子
    if projection is not None and projection.convergence_score > 0:
        if projection.convergence_score > 0.7:
            score -= 1.0
        elif projection.convergence_score < 0.3:
            score += 1.0

    # 线索数量因子
    if clue_count >= 3:
        score -= 1.0
    # 2 条线索 = 中性

    return max(1.0, min(10.0, score))


def _empty_projection():
    """返回一个空的 AdamProjection（计算失败时的兜底值）。"""
    from config.schema import AdamProjection
    return AdamProjection(
        projected_prices=[], anchor_price=1.0,
        convergence_score=0.0, projected_direction="neutral"
    )
