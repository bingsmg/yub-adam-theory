# recommendation/ — 推荐层

## 概述

将检测到的买入信号进行排名、过滤和解释，生成最终推荐列表。

## 模块

### ranking.py — 排名与一问规则

`select_top_recommendations(signals, top_n=20) -> list[AdamSignal]`

流程：
1. 按 `quality² / risk` 复合指标排序
2. 应用"一问规则"（One-Question Rule）：根据亚当理论——"基于中心对称图表显示的信息，我今天想交易吗？"——仅保留明确肯定的信号
3. 截取前 N 个

`apply_one_question_rule(signals)` 阈值（可通过 settings 配置）：

| 信号数量 | 保留规则 |
|----------|----------|
| ≤5 | 全部保留 |
| 6-15 | 保留前 80% (min 5) |
| >15 | 保留前 70% (min 10) |

### explainer.py — 中文解释生成

`build_explanation(signal) -> str`
生成完整的中文分析报告，包含：
- 每个条件的满足/不满足状态及详细数据
- 止损价格和计算逻辑
- 中心对称投影方向和收敛度
- 成交量背景分析
- 风险等级描述（低/中/高）
- 操作建议（入场/止损/原则）

`brief_reason(signal) -> str`
单行摘要，用于表格展示。

## 配置（config/settings.py）

```python
TOP_N_RECOMMENDATIONS: int = 20
RANK_KEEP_ALL_IF_LE: int = 5
RANK_KEEP_FRAC_MID: float = 0.8
RANK_KEEP_FRAC_HIGH: float = 0.7
RANK_MID_THRESHOLD: int = 15
RANK_MIN_KEEP_MID: int = 5
RANK_MIN_KEEP_HIGH: int = 10
```

## 设计模式

- **策略模式（可扩展）**：排名公式 `quality² / risk` 可替换为自定义 RankingStrategy
- 一问规则阈值参数化，无需修改代码即可调整筛选严格度
