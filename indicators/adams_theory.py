"""
亚当理论（Adam's Theory）—— 核心算法。

纯亚当理论实现，依据威尔德的原始著作。
门控逻辑中不包含任何技术指标（ADX、RSI 等），
仅使用图表中的三种视觉线索。

三个入场条件（多头）：
  1. 突破 — 价格突破近期可见高点
  2. 趋势改变 — 前期下降/盘整转为上升趋势
  3. 缺口/宽幅 — 跳空高开或日线范围显著高于均值

信号：3 个条件中须同时满足 >= 2 个。

同时实现了中心对称投影（第二镜像），
作为"一个问题"规则的视觉辅助工具。

── 条件注册表 ──

可通过 register_condition() 动态注册自定义条件。
每个条件是一个可调用对象 (df: pd.DataFrame) -> SignalClue | None。
内置条件在导入时自动注册。
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

from config.schema import AdamProjection, SignalClue
from config.settings import settings


# ── 条件探测器注册表 ─────────────────────────────────────────────────────
# 每项：Callable[[pd.DataFrame], SignalClue | None]
# 内置条件在下方自行注册；外部代码可调用
# register_condition() 来添加自定义探测器。

_CONDITION_REGISTRY: dict[str, Callable[[pd.DataFrame], SignalClue | None]] = {}


def register_condition(name: str, detector: Callable[[pd.DataFrame], SignalClue | None]) -> None:
    """注册自定义亚当理论条件探测器。

    参数:
        name: 唯一条件名称（例如 "my_custom_breakout"）。
        detector: 接受 OHLCV DataFrame 的可调用对象，条件满足时返回
                  SignalClue，否则返回 None。
    """
    _CONDITION_REGISTRY[name] = detector


def unregister_condition(name: str) -> None:
    """从注册表中移除一个条件。"""
    _CONDITION_REGISTRY.pop(name, None)


def list_registered_conditions() -> list[str]:
    """返回所有已注册条件的名称列表。"""
    return list(_CONDITION_REGISTRY.keys())


# ═══════════════════════════════════════════════════════════════════════
# 中心对称投影（"第二镜像"）
# ═══════════════════════════════════════════════════════════════════════

def compute_center_symmetry_projection(
    df: pd.DataFrame,
    lookback: int | None = None,
) -> AdamProjection:
    """
    亚当理论中心对称投影（第二镜像）。

    交易者将过去价格轨迹描在透明胶片上，先水平翻转再垂直翻转，
    将最旧的 K 线与"当前"对齐，得到的曲线就是市场自身对
    未来价格走势的投影。

    数学等价形式：
        Projected[i] = 2 * anchor - historical_midpoint[lookback - 1 - i]

    参数:
        df: OHLCV DataFrame。最近一行 = "中心点"（当前）。
        lookback: 镜像的 K 线数量（默认来自配置）。

    返回:
        AdamProjection，包含 projected_midpoints、anchor、convergence、direction。
    """
    if lookback is None:
        lookback = settings.LOOKBACK_BARS

    if len(df) < lookback + 2:
        raise ValueError(f"Need at least {lookback + 2} bars, got {len(df)}")

    current = df.iloc[-1]
    anchor = (float(current["close"]) + float(current["open"])) / 2.0

    closes = df["close"].values.astype(float)
    opens = df["open"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)

    # 历史段：当前之前的 lookback 根 K 线
    hist_close = closes[-(lookback + 1):-1]
    hist_open = opens[-(lookback + 1):-1]
    hist_high = highs[-(lookback + 1):-1]
    hist_low = lows[-(lookback + 1):-1]

    n = len(hist_close)
    projected_midpoints = []
    projected_highs = []
    projected_lows = []

    for i in range(n):
        hist_idx = n - 1 - i  # 最近的历史 → 最早的未来
        # 中心对称：Proj = 2*Anchor - Hist
        # 高低点反转：过去高点 → 投影低点，过去低点 → 投影高点
        proj_mid = 2.0 * anchor - (hist_close[hist_idx] + hist_open[hist_idx]) / 2.0
        proj_high = 2.0 * anchor - hist_low[hist_idx]
        proj_low = 2.0 * anchor - hist_high[hist_idx]

        projected_midpoints.append(float(proj_mid))
        projected_highs.append(float(proj_high))
        projected_lows.append(float(proj_low))

    # 方向：比较前几根投影 K 线与锚点
    if len(projected_midpoints) >= 5:
        early = np.mean(projected_midpoints[:5])
        late = np.mean(projected_midpoints[-5:])
        delta_pct = (late - early) / anchor * 100
        if delta_pct > 0.5:
            direction = "up"
        elif delta_pct < -0.5:
            direction = "down"
        else:
            direction = "neutral"
    else:
        direction = "neutral"

    # 收敛度：投影序列的聚集紧密程度
    if projected_midpoints:
        std = float(np.std(projected_midpoints))
        convergence = float(1.0 / (1.0 + std / anchor))
        convergence = max(0.0, min(1.0, convergence))
    else:
        convergence = 0.0

    return AdamProjection(
        projected_prices=projected_midpoints,
        anchor_price=round(anchor, 2),
        convergence_score=round(convergence, 4),
        projected_direction=direction,
        lookback_used=lookback,
    )


# ═══════════════════════════════════════════════════════════════════════
# 条件 1：突破
# ═══════════════════════════════════════════════════════════════════════

def detect_breakout(
    df: pd.DataFrame,
    lookback: int | None = None,
) -> SignalClue | None:
    """
    条件 1 — 突破：
    今日收盘价突破近期可见高点。
    突破前盘整越久，意义越重大。

    规则：close >= 过去 N 根 K 线（不含今日）的最高 high
    """
    if lookback is None:
        lookback = settings.BREAKOUT_LOOKBACK

    if len(df) < lookback + 2:
        return None

    recent = df.iloc[-(lookback + 1):-1]  # 排除今日
    current_close = float(df["close"].iloc[-1])
    highest_high = float(recent["high"].max())
    avg_high = float(recent["high"].mean())

    if current_close < highest_high:
        return None

    # 今日收盘价超过了多少根 lookback 内的高点
    bars_broken = int((df["close"].iloc[-1] > recent["high"]).sum())
    coverage_pct = bars_broken / lookback * 100

    excess_pct = (current_close - highest_high) / highest_high * 100

    # 强度：突破的坚决程度
    if coverage_pct >= 80:
        strength = min(1.0, 0.6 + excess_pct / 5.0)
    elif coverage_pct >= 50:
        strength = min(0.8, 0.4 + excess_pct / 5.0)
    else:
        strength = min(0.6, excess_pct / 5.0)

    detail = (
        f"Breakout confirmed: closing price {current_close:.2f} "
        f"breaks above {lookback}-day highest high {highest_high:.2f}, "
        f"exceeding {bars_broken}/{lookback} ({coverage_pct:.0f}%) recent highs"
    )

    return SignalClue(clue_type="breakout", strength=round(max(0.1, strength), 4), detail=detail)


# ═══════════════════════════════════════════════════════════════════════
# 条件 2：趋势改变
# ═══════════════════════════════════════════════════════════════════════

def detect_trend_change(
    df: pd.DataFrame,
    trend_lookback: int | None = None,
    recent_lookback: int | None = None,
) -> SignalClue | None:
    """
    条件 2 — 趋势改变：
    前期价格行为处于下降趋势或盘整中，现在价格已反转向上，
    形成更高的低点并突破近期摆动高点。

    检测：
      1. 前期阶段：更低的高点/更低的低点（下降趋势）
         或横向/收窄（盘整）
      2. 近期摆动低点已形成，价格反弹
      3. 当前收盘价突破低点之后形成的摆动高点
    """
    if trend_lookback is None:
        trend_lookback = settings.TREND_CHANGE_LOOKBACK
    if recent_lookback is None:
        recent_lookback = settings.TREND_CHANGE_RECENT

    if len(df) < trend_lookback + 5:
        return None

    full = df.iloc[-trend_lookback:]
    current_close = float(df["close"].iloc[-1])
    half = len(full) // 2

    first_half = full.iloc[:half]
    second_half = full.iloc[half:]

    first_high_mean = float(first_half["high"].mean())
    first_low_mean = float(first_half["low"].mean())
    second_high_mean = float(second_half["high"].mean())
    second_low_mean = float(second_half["low"].mean())

    # 检测前期阶段类型
    downtrend = (first_high_mean > second_high_mean * 1.02 and
                 first_low_mean > second_low_mean * 1.02)
    consolidation = (abs(first_high_mean - second_high_mean) / max(first_high_mean, 0.01) < 0.03 and
                     abs(first_low_mean - second_low_mean) / max(first_low_mean, 0.01) < 0.03)

    if not (downtrend or consolidation):
        return None

    # 在近期窗口内寻找摆动低点
    recent = df.iloc[-recent_lookback:]
    swing_low_val = float(recent["low"].min())
    swing_low_loc = recent["low"].idxmin()

    # 摆动低点之后的数据
    after_low = df.loc[swing_low_loc:]
    if len(after_low) < 2:
        return None

    # 摆动低点与今日之间的最高高点（不含今日）
    after_except_today = after_low.iloc[:-1]
    if after_except_today.empty:
        return None
    swing_high_after_low = float(after_except_today["high"].max())

    # 必须突破此摆动高点
    if current_close <= swing_high_after_low:
        return None

    # 从摆动低点的反弹幅度
    recovery_pct = (current_close - swing_low_val) / swing_low_val * 100
    if recovery_pct < 2.0:
        return None

    # 强度
    recovery_strength = min(1.0, recovery_pct / 8.0)
    phase_bonus = 1.0 if downtrend else 0.7  # 下降趋势反转 > 盘整突破
    strength = min(1.0, recovery_strength * phase_bonus)

    phase_label = "downtrend reversal" if downtrend else "consolidation breakout"
    detail = (
        f"Trend change ({phase_label}): prior phase was "
        f"{'downtrend' if downtrend else 'consolidation'}. "
        f"Price recovered {recovery_pct:.1f}% from swing low {swing_low_val:.2f}, "
        f"now breaking above recent swing high {swing_high_after_low:.2f}"
    )

    return SignalClue(clue_type="trend_change", strength=round(max(0.1, strength), 4), detail=detail)


# ═══════════════════════════════════════════════════════════════════════
# 条件 3：跳高缺口 / 宽幅
# ═══════════════════════════════════════════════════════════════════════

def detect_gap_or_wide_range(
    df: pd.DataFrame,
    lookback: int | None = None,
    gap_min_pct: float | None = None,
    range_multiple: float | None = None,
) -> SignalClue | None:
    """
    条件 3 — 跳高缺口或宽幅：
    市场从平静期"苏醒"。

    两个子条件（满足任一或两个）：
      a) 跳高缺口：今日开盘 > 昨日收盘
      b) 宽幅：今日高低价差显著超过近期均值
    """
    if lookback is None:
        lookback = settings.BREAKOUT_LOOKBACK
    if gap_min_pct is None:
        gap_min_pct = settings.GAP_MIN_PCT
    if range_multiple is None:
        range_multiple = settings.RANGE_EXPANSION_MULTIPLE

    if len(df) < lookback + 2:
        return None

    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    recent_excl_today = df.iloc[-(lookback + 1):-1]

    today_open = float(today["open"])
    today_high = float(today["high"])
    today_low = float(today["low"])
    yesterday_close = float(yesterday["close"])

    gap_pct = (today_open - yesterday_close) / yesterday_close * 100
    has_gap_up = gap_pct >= gap_min_pct

    avg_range = float((recent_excl_today["high"] - recent_excl_today["low"]).mean())
    today_range = today_high - today_low
    range_ratio = today_range / avg_range if avg_range > 0 else 1.0
    has_wide_range = range_ratio >= range_multiple

    if not (has_gap_up or has_wide_range):
        return None

    parts = []  # 描述片段列表
    strength = 0.0

    if has_gap_up:
        gap_strength = min(1.0, gap_pct / 3.0)
        strength += gap_strength * 0.6
        parts.append(f"gap up {gap_pct:.2f}% (open {today_open:.2f} > prev close {yesterday_close:.2f})")

    if has_wide_range:
        range_strength = min(1.0, (range_ratio - 1.0) / 2.0)
        strength += range_strength * 0.4
        parts.append(f"wide range {today_range:.2f} ({range_ratio:.1f}x {lookback}-day avg {avg_range:.2f})")

    strength = min(1.0, strength)

    detail = "Market activation: " + " | ".join(parts)

    return SignalClue(clue_type="range_expansion", strength=round(max(0.1, strength), 4), detail=detail)


# ═══════════════════════════════════════════════════════════════════════
# 综合检测
# ═══════════════════════════════════════════════════════════════════════

def detect_all_three_conditions(df: pd.DataFrame) -> list[SignalClue]:
    """
    对 DataFrame 运行所有已注册的条件探测器。

    返回触发的条件列表（0-N 个元素）。
    默认运行 3 个内置条件。通过 register_condition()
    注册的自定义条件也会自动包含。
    """
    clues: list[SignalClue] = []
    for detector in _CONDITION_REGISTRY.values():
        try:
            result = detector(df)
            if result is not None:
                clues.append(result)
        except Exception:
            # 静默跳过失败的探测器——自定义条件不应
            # 破坏整个流水线
            continue
    return clues


def check_buy_signal(clues: list[SignalClue]) -> tuple[bool, str]:
    """
    亚当理论买入信号规则：
    3 个条件中至少须同时满足 2 个。

    返回 (is_buy, reason)。
    """
    n = len(clues)
    condition_names = {"breakout": "突破", "trend_change": "趋势改变", "range_expansion": "缺口/宽幅"}

    if n >= 3:
        names = ", ".join(condition_names.get(c.clue_type, c.clue_type) for c in clues)
        return True, f"All 3 conditions met: {names} — strong Adam buy signal"

    if n == 2:
        names = ", ".join(condition_names.get(c.clue_type, c.clue_type) for c in clues)
        return True, f"2 of 3 conditions met: {names} — confirmed Adam buy signal"

    if n == 1:
        missing = set(condition_names.values()) - {condition_names.get(clues[0].clue_type, clues[0].clue_type)}
        return False, f"Only 1 condition met ({clues[0].clue_type}), missing: {', '.join(missing)}"

    return False, "No conditions met — no entry signal"


def find_structural_stop(df: pd.DataFrame, lookback: int = 40) -> float:
    """
    寻找最近摆动低点下方的结构性止损位。

    结构性止损 = 近期 lookback 窗口内的最低低点，
    代表最近的支撑位，若被跌破则多头逻辑失效。

    返回止损价格 (float)。
    """
    if len(df) < 10:
        return float(df["low"].min())

    recent = df.iloc[-lookback:]
    swing_low = float(recent["low"].min())
    current_close = float(df["close"].iloc[-1])

    # 确保止损位至少低于当前价格 1%，预留缓冲空间
    if (current_close - swing_low) / current_close < 0.01:
        swing_low = current_close * 0.97

    return round(swing_low, 2)


# ── 自动注册内置条件 ────────────────────────────────────────────────────
# 这是三个经典的亚当理论入场条件。
# 在导入时自动注册；外部代码可通过
# register_condition() 添加自定义条件，或通过 unregister_condition() 移除默认条件。

register_condition("breakout", detect_breakout)
register_condition("trend_change", detect_trend_change)
register_condition("range_expansion", detect_gap_or_wide_range)
