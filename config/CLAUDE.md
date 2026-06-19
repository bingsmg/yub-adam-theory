# config/ — 配置层

## 概述

集中管理所有配置参数和数据模型定义。

## 模块

### settings.py — 全局设置

`AdamSettings(BaseSettings)` 通过 pydantic-settings 从 `.env` 文件加载配置。

配置分类：

| 类别 | 关键字段 |
|------|----------|
| 数据路径 | `STOCKS_DIR`, `DAILY_DIR`, `ALL_STOCKS_PATH`, `STOCK_LIST_PATH` |
| 核心参数 | `LOOKBACK_BARS=20` |
| 检测阈值 | `BREAKOUT_LOOKBACK=20`, `TREND_CHANGE_LOOKBACK=40`, `RANGE_EXPANSION_MULTIPLE=1.5`, `GAP_MIN_PCT=0.5` |
| 过滤 | `MIN_PRICE=3.0`, `MIN_VOLUME_RATIO=0.3`, `MIN_LISTING_DAYS=60`, `MAX_STOCKS_TO_ANALYZE=5000` |
| 板块权限 | `ALLOW_CHINEXT=True`, `ALLOW_STAR_MARKET=True`, `ALLOW_BSE=False` |
| 风险管理 | `MAX_RISK_SCORE=7.0` |
| 数据源 | `DATA_SOURCE_ORDER=["tencent","baostock"]`, `DATA_SOURCE_STRATEGY="priority"`, `FETCH_MAX_WORKERS=1`, `FETCH_DELAY_SECONDS=1.0` |
| 评分排名 | `SCORE_WEIGHTS=[0.50,0.30,0.20]`, `RANK_KEEP_ALL_IF_LE=5`, `RANK_KEEP_FRAC_MID=0.8`, `RANK_KEEP_FRAC_HIGH=0.7` |
| 报告 | `TOP_N_RECOMMENDATIONS=20` |
| 飞书 | `FEISHU_WEBHOOK_URL=""` |

实例化：`settings = AdamSettings()` （模块级单例）
工具函数：`ensure_dirs()` 创建所有输出目录

### schema.py — Pydantic 数据模型

| 模型 | 用途 |
|------|------|
| `AdamProjection` | 中心对称投影结果：投影价格、锚点、收敛度、方向 |
| `SignalClue` | 单个入场线索：类型、强度、详细描述 |
| `AdamSignal` | 完整买入信号：投影、线索、风险、止损、成交量 |
| `DailyRecommendation` | 每日推荐输出：日期、分析数量、推荐列表 |

## 使用

```python
from config.settings import settings
from config.schema import AdamSignal, DailyRecommendation

# 读取配置
lookback = settings.LOOKBACK_BARS

# 创建信号
signal = AdamSignal(symbol="600519", name="贵州茅台", ...)
```
