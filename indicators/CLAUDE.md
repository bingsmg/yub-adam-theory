# indicators/ — 亚当理论核心算法

## 概述

纯亚当理论（Adam's Theory of Markets）的数学实现。无任何技术指标（ADX/RSI/MACD），仅基于价格行为的三种视觉条件。

## 模块

| 文件 | 用途 |
|------|------|
| `adams_theory.py` | 核心算法：投影、三条件检测、门控、结构止损 |
| `market_regime.py` | 市场体制检测：趋势/震荡/高波动分类 + 风险调整 |
| `__init__.py` | 公共 API 导出 |

## 市场体制检测 `market_regime.py`

基于纯价格行为的市场环境分类：

```python
from indicators.market_regime import detect_market_regime, describe_market_regime, regime_risk_adjustment

regime = detect_market_regime(df)         # → "trending_up" | "trending_down" | "ranging" | "volatile"
desc = describe_market_regime(regime)     # → 中文描述
adj = regime_risk_adjustment(regime)      # → 风险调整倍数
```

算法：通过净价格变化判断趋势方向，ATR/收盘价比率判断波动性，价格区间宽度判断盘整。
- `trending_up`: 价格单调上升 >5%，顺势建议
- `trending_down`: 价格单调下降 >5%，逆势风险
- `ranging`: 价格区间 <3%，突破信号更有价值
- `volatile`: ATR/价格 >4%，建议严格止损

## 核心算法

### 1. 中心对称投影 `compute_center_symmetry_projection()`

亚当理论的核心：将过去价格轨迹围绕锚点 (今收+今开)/2 做水平+垂直翻转，得到市场自身对未来的投影。

```
Projected[i] = 2 × anchor - historical_midpoint[lookback - 1 - i]
```

返回 `AdamProjection`：投影价格序列、锚点、收敛度(0-1)、方向(up/down/neutral)

### 2. 条件一：突破 `detect_breakout()`

今日收盘价 >= 过去 20 根 K 线的最高价。强度取决于突破了多少个前期高点。

### 3. 条件二：趋势改变 `detect_trend_change()`

前期为下降趋势或盘整状态 → 价格从近期摆动低点反弹 → 突破摆动高点。检测 40 根 K 线的半段比较。

### 4. 条件三：缺口/宽幅 `detect_gap_or_wide_range()`

两个子条件（满足任一即可）：
- a) 跳空高开 >= 0.5%
- b) 今日高低差 >= 20 日均值的 1.5 倍

### 5. 买入门控 `check_buy_signal()`

>= 2 of 3 条件满足 = 买入信号。

### 6. 结构止损 `find_structural_stop()`

最近 40 根 K 线的最低低点，若距离当前价格 <1% 则调整为 97% 当前价格。

## 条件注册表（策略模式）

内置 3 个条件在导入时自动注册。外部可动态添加/移除条件：

```python
from indicators.adams_theory import register_condition, unregister_condition

# 添加自定义条件
def my_custom_condition(df: pd.DataFrame) -> SignalClue | None:
    ...

register_condition("my_condition", my_custom_condition)

# 移除默认条件
unregister_condition("breakout")
```

`detect_all_three_conditions()` 遍历注册表中所有条件，收集触发的结果。

## 关键函数

| 函数 | 用途 |
|------|------|
| `compute_center_symmetry_projection(df, lookback=20)` | 中心对称投影 |
| `detect_breakout(df, lookback=20)` | 条件1：突破检测 |
| `detect_trend_change(df, trend_lookback=40, recent_lookback=15)` | 条件2：趋势改变 |
| `detect_gap_or_wide_range(df, lookback=20, gap_min_pct=0.5, range_multiple=1.5)` | 条件3：缺口/宽幅 |
| `detect_all_three_conditions(df)` | 遍历注册表运行所有条件 |
| `check_buy_signal(clues)` | 门控：>=2 条件 = 买入 |
| `find_structural_stop(df, lookback=40)` | 结构止损位 |
| `register_condition(name, detector)` | 注册自定义条件 |
| `unregister_condition(name)` | 移除条件 |
| `list_registered_conditions()` | 列出所有已注册条件 |
