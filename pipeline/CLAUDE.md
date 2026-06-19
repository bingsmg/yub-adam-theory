# pipeline/ — 管道编排层

## 概述

封装完整的亚当理论日线推荐工作流。将 `scripts/daily_update.py` 的过程式脚本重构为可测试、可组合的 `DailyPipeline` 类。

## DailyPipeline

```python
from pipeline import DailyPipeline

pipeline = DailyPipeline(fetcher=None)  # fetcher 可选，默认从配置读取

# 完整运行
result = pipeline.run(limit=200, skip_update=False)

# 分步运行（便于测试和调试）
master = pipeline.update_data_or_skip(skip_update=False)
candidates = pipeline.filter_candidates(master, limit=200)
signals = pipeline.detect_signals(candidates)
recommendations, latest_str = pipeline.rank_and_explain(signals)
csv_path = pipeline.save_csv(recommendations, latest_str)
```

## 流水线步骤

| 步骤 | 方法 | 描述 |
|------|------|------|
| 1. 数据更新 | `update_data()` / `update_data_or_skip()` | 获取股票列表 + 增量更新最新交易日 |
| 2. 候选筛选 | `filter_candidates(master, limit)` | 按活跃度预筛选 |
| 3. 信号检测 | `detect_signals(candidates)` | 逐只股票运行亚当理论检测 |
| 4. 排名解释 | `rank_and_explain(signals)` | 评分→一问规则→生成中文解释 |
| 5. 保存 CSV | `save_csv(recommendations, date)` | 输出到 output/results/ |

## 返回值

`run()` 返回 `DailyRecommendation` 对象，包含：
- `recommendations`: 排好序的 `AdamSignal` 列表（含完整解释）
- `total_stocks_analyzed`, `total_signals_found`
- `market_date`, `generated_at`

## 设计模式

- **模板方法**：`run()` 定义流水线骨架，每个步骤可独立覆盖
- **依赖注入**：`fetcher` 通过构造函数注入，便于测试
- **关注点分离**：管道编排与数据 I/O、信号检测、报告生成完全解耦

## CLI 使用

`scripts/daily_update.py` 是 DailyPipeline 的命令行包装器：

```bash
python scripts/daily_update.py --limit 200 --no-update --output console
```
