# data/sources/ — 可插拔多数据源层

## 概述

抽象 A 股日线数据获取，支持 4 个数据源，可通过配置动态切换。每个源返回统一的 OHLCV DataFrame。

## 架构

```
DataSource(ABC)              # 抽象契约
├── TencentDataSource        # 腾讯证券 API（默认首选，通过 akshare 调用）
├── BaostockDataSource       # baostock 自有服务器（无频控，但较慢）
├── AkshareDataSource        # 东方财富爬虫（最快，但可能被限流）
└── EfinanceDataSource       # 东方财富批量接口（存根，标记为实验性）

策略层：
  select_source("priority")     → 返回 DATA_SOURCE_ORDER 第一个可用源
  select_source("fastest_first") → 基准测试选最快源
  fetch_with_fallback(symbol)   → 按顺序回退
  race_fetch(symbol)            → 并行竞速，返回最快结果

并行层：
  fetch_batch_parallel()        → ThreadPoolExecutor 批量并发获取
```

## 关键类

### DataSource(ABC)

```python
class DataSource(ABC):
    name: str                          # "tencent" | "baostock" | "akshare" | "efinance"
    is_available() -> bool             # 检查依赖是否安装且可用
    get_stock_list() -> DataFrame      # 返回 symbol, name, code
    fetch_daily_kline(symbol, start, end) -> DataFrame  # QFQ 前复权日线
    fetch_batch(symbols, start, end) -> dict            # 批量获取
```

### normalize_columns(df, source_name)

将各源特定列名映射到统一英文名：date/open/high/low/close/volume/amount/symbol/name

### get_fetcher(strategy, order)

工厂函数，返回最佳可用 DataSource 实例。

## 数据源对比

| 源 | 速度 | 稳定性 | 频控风险 | 批量支持 |
|----|------|--------|----------|----------|
| tencent | ~0.5s | 高 | 低 | 无（循环调用） |
| baostock | ~1.5s | 中（会话不稳定） | 无 | 无（连接模式） |
| akshare | ~0.3s | 低 | 高（800-1500次后限流） | 无 |
| efinance | ~0.3s | 低 | 高 | 原生批量（未完成） |

## 配置

```bash
# .env
DATA_SOURCE_ORDER=["tencent", "baostock"]   # 优先级顺序
DATA_SOURCE_STRATEGY=priority                # priority | fastest_first
FETCH_MAX_WORKERS=1                          # 并行线程数
FETCH_DELAY_SECONDS=1.0                      # 请求间隔
```

## 扩展新数据源

1. 新建 `my_source.py`，继承 `DataSource`
2. 实现 `is_available()`, `get_stock_list()`, `fetch_daily_kline()`
3. 在 `strategy.py` 的 `_resolve_source()` 注册表中添加映射
