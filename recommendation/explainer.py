"""
Natural-language explanation generator.

Each recommendation must explicitly state:
  1. Which of the 3 conditions were met — with data and logic
  2. Which conditions were NOT met (and why)
  3. The stop-loss price and the reasoning behind it
  4. The center symmetry projection direction as visual confirmation
"""

from __future__ import annotations

from config.schema import AdamSignal


_CONDITION_LABELS = {
    "breakout": "条件1: 突破 (Breakout)",
    "trend_change": "条件2: 趋势改变 (Trend Change)",
    "range_expansion": "条件3: 跳高缺口/宽幅 (Gap / Wide Range)",
}


def build_explanation(signal: AdamSignal) -> str:
    """
    Build a comprehensive, data-driven explanation for the buy signal.
    """
    met_types = {c.clue_type for c in signal.clues}
    all_types = {"breakout", "trend_change", "range_expansion"}

    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"  {signal.name} ({signal.symbol}) — 亚当理论买入推荐")
    lines.append(f"{'='*60}")
    lines.append(f"  分析日期: {signal.signal_date}")
    lines.append(f"  收盘价: {signal.current_close:.2f}")
    lines.append("")

    # ── Condition Summary ────────────────────────────────────────
    met_count = len(signal.clues)
    lines.append(f"  满足条件: {met_count}/3 (需要 >=2)")
    lines.append("")

    for cond_type in ["breakout", "trend_change", "range_expansion"]:
        clue = next((c for c in signal.clues if c.clue_type == cond_type), None)
        status = "[OK] 满足" if clue else "[--] 不满足"
        label = _CONDITION_LABELS.get(cond_type, cond_type)

        if clue:
            lines.append(f"  {status}  {label}")
            lines.append(f"         {clue.detail}")
        else:
            lines.append(f"  {status}  {label}")
            lines.append(f"         该条件未触发，当前走势不满足此判定标准")

        lines.append("")

    # ── Stop Loss ────────────────────────────────────────────────
    stop_pct = (signal.current_close - signal.stop_loss_price) / signal.current_close * 100
    lines.append(f"  止损价位: {signal.stop_loss_price:.2f} (距离入场 -{stop_pct:.1f}%)")
    lines.append(f"  止损逻辑: 基于最近40根K线的结构低点")
    lines.append("")

    # ── Projection ───────────────────────────────────────────────
    proj = signal.projection
    if proj.projected_prices:
        lines.append(f"  中心对称投影方向: {proj.projected_direction.upper()}")
        lines.append(f"  投影收敛度: {proj.convergence_score:.3f} (越接近1越可靠)")
        lines.append(f"  锚点价格: {proj.anchor_price:.2f}")
        proj_first = proj.projected_prices[0]
        proj_last = proj.projected_prices[-1]
        proj_min = min(proj.projected_prices)
        proj_max = max(proj.projected_prices)
        lines.append(f"  投影区间: {proj_min:.2f} ~ {proj_max:.2f}")

        # Whether projection supports the trade
        if proj.projected_direction == "up":
            lines.append(f"  投影确认: 未来走势向上倾斜，支持做多判断")
        elif proj.projected_direction == "neutral":
            lines.append(f"  投影确认: 中性，需结合突破力度综合判断")
        else:
            lines.append(f"  投影警告: 向下倾斜，入场需谨慎")
    else:
        lines.append(f"  中心对称投影: 数据不足，无法计算")
    lines.append("")

    # ── Volume Context ───────────────────────────────────────────
    if signal.volume_ratio > 1.5:
        vol_note = f"放量 ({signal.volume_ratio:.1f}x 均量) — 资金参与度高"
    elif signal.volume_ratio > 1.0:
        vol_note = f"正常 ({signal.volume_ratio:.1f}x 均量)"
    else:
        vol_note = f"缩量 ({signal.volume_ratio:.1f}x 均量) — 需注意突破有效性"
    lines.append(f"  成交量: {vol_note}")
    lines.append("")

    # ── Risk Summary ─────────────────────────────────────────────
    if signal.risk_score <= 3.0:
        risk_desc = "低风险 — 条件共振强，止损紧凑"
    elif signal.risk_score <= 5.0:
        risk_desc = "中等风险 — 正常仓位"
    elif signal.risk_score <= 7.0:
        risk_desc = "偏高 — 建议减仓或等更多确认"
    else:
        risk_desc = "高风险 — 仅适合经验丰富者"
    lines.append(f"  风险评分: {signal.risk_score:.1f}/10 ({risk_desc})")
    lines.append("")

    # ── Action ───────────────────────────────────────────────────
    lines.append(f"  操作建议:")
    lines.append(f"    入场: 明日开盘价附近")
    lines.append(f"    止损: {signal.stop_loss_price:.2f} (到达即离场)")
    lines.append(f"    原则: 永不向下加仓，让利润奔跑，用止损保护本金")
    lines.append(f"{'='*60}")

    return "\n".join(lines)


def brief_reason(signal: AdamSignal) -> str:
    """One-line summary for table display."""
    clue_abbr = {"breakout": "B", "trend_change": "T", "range_expansion": "R"}
    clue_str = "+".join(clue_abbr.get(c.clue_type, "?") for c in signal.clues)

    met = [c.clue_type for c in signal.clues]
    missing = [t for t in ["breakout", "trend_change", "range_expansion"] if t not in met]
    missing_abbr = ",".join(clue_abbr.get(t, "?") for t in missing)

    proj_dir = signal.projection.projected_direction[:2].upper() if signal.projection.projected_direction else "??"

    return (
        f"[{clue_str}] met, [{missing_abbr}] not | "
        f"Proj:{proj_dir} Conv:{signal.projection.convergence_score:.2f} | "
        f"Stop:{signal.stop_loss_price:.2f}(-{(signal.current_close - signal.stop_loss_price) / signal.current_close * 100:.1f}%) | "
        f"Risk:{signal.risk_score:.1f}"
    )
