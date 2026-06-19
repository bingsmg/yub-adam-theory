# data/ — 数据层

## 概述

数据层负责 A 股日线数据的获取、存储、过滤和管道编排。采用多层架构，支持可插拔多数据源。

## 架构

```
data/
├── sources/          # 可插拔数据源（多源策略）
│   ├── base.py       # DataSource 抽象基类
│   ├── tx_source.py  # Tencent 腾讯证券（默认首选）
│   ├── baostock_source.py  # baostock 自有服务器（备选）
│   ├── akshare_source.py   # akshare 东方财富（可选）
│   ├── ef_source.py        # efinance 东方财富（存根）
│   ├── strategy.py         # 源选择策略：优先级/竞速/回退
│   └── parallel.py         # ThreadPoolExecutor 并行批量获取
├── store.py          # 纯存储 I/O：按股票分区的 Parquet 读写
├── filters.py        # 业务过滤：板块分类、活跃股预筛选、过期检测
├── pipeline.py       # 管道编排：全量回填 + 增量更新
└── consolidated_store.py  # 向后兼容导入层（re-export）
```

## 关键模块

### store.py — 存储 I/O

`load_stock(symbol)` / `_save_stock()` — 单股票 Parquet 读写
`load_latest_snapshot()` — 每只股票仅读最后一行，O(n) 快速预筛选
`load_all_stocks()` — 全量加载，优先 stock-partitioned → legacy 回退
`get_latest_date()` — 获取最新数据日期

存储格式：`output/stocks/{symbol}.parquet`，每文件一股票，列: date/open/high/low/close/volume/name

### filters.py — 业务过滤

`get_board(symbol)` → 板块分类: main/chinext/star/bse
`get_stock_list(fetcher)` → 通过数据源获取全部股票列表
`get_stale_stocks()` → 检测数据过期的股票（仅读 date 列，高效）
`filter_active_stocks()` → 按活跃度预筛选（排除 ST/仙股/无权限板块）

### pipeline.py — 管道编排

`build_all_stocks_parquet()` → 首次全量回填（分块并行，支持断点续传）
`update_latest_days()` → 增量更新（仅获取过期股票）

## 设计模式

- **策略模式**：数据源选择（priority / fastest_first / fallback / race）
- **模板方法**：DataSource ABC 定义接口，各实现覆盖具体方法
- **单文件存储**：每只股票独立文件，写入无冲突，增量更新只写变更文件
- **兼容层**：`consolidated_store.py` 保留旧 API 的 re-export

## 使用示例

```python
from data.store import load_stock, load_latest_snapshot
from data.filters import get_board, filter_active_stocks
from data.pipeline import build_all_stocks_parquet, update_latest_days
from data.sources import get_fetcher

# 获取数据源
fetcher = get_fetcher()  # 按 settings.DATA_SOURCE_ORDER 选择

# 全量回填
build_all_stocks_parquet(stock_list, "2024-06-01", "2026-06-19")

# 增量更新
master = update_latest_days(stock_list)

# 预筛选活跃股票
candidates = filter_active_stocks(master, top_n=200)
```
