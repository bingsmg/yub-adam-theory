# signals/ — 信号检测与评分

## 概述

将原始 OHLCV 数据转换为标准化的买入信号，并计算质量评分。是核心算法（indicators/）与推荐层（recommendation/）之间的桥梁。

## 模块

### detector.py — 信号检测流水线

`detect_signal(df, symbol, name, signal_date, market_cap) -> AdamSignal | None`

流水线步骤：
1. 数据验证（最少 K 线数、必需列存在）
2. 调用 `detect_all_three_conditions()` 运行所有条件检测器
3. `check_buy_signal()` 门控：>=2 条件 = 买入
4. 计算中心对称投影、结构止损、ATR、成交量比
5. `_simple_risk_score()` 计算风险评分 (1-10)
6. 风险检查：超过 `MAX_RISK_SCORE` 则抑制信号

### scorer.py — 质量评分

`compute_quality_score(signal) -> float` (0-100)

三维评分（权重可通过 settings.SCORE_WEIGHTS 配置）：
- **条件计数和强度** (默认 50%)：3 条件 = 70-100 分，2 条件 = 40-70 分
- **投影方向和收敛度** (默认 30%)：上涨+强收敛 = 60-100 分
- **成交量确认** (默认 20%)：>2x 放量 = 100 分

`rank_signals(signals) -> list[AdamSignal]`
按 `quality² / risk` 复合指标排序

## 配置（config/settings.py）

```python
MAX_RISK_SCORE: float = 7.0         # 风险评分上限
SCORE_WEIGHTS: list[float] = [0.50, 0.30, 0.20]  # 质量评分权重
```

## 使用示例

```python
from signals.detector import detect_signal
from signals.scorer import compute_quality_score, rank_signals

# 对单只股票检测
signal = detect_signal(df, symbol="600519", name="贵州茅台")

# 评分排名
quality = compute_quality_score(signal)
ranked = rank_signals(signals)
```
