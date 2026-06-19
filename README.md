# Adam's Theory A-Share Stock Picker · 亚当理论 A 股选股系统

基于 J. Welles Wilder Jr. 的亚当理论（中心对称投影 + 三条件入场），扫描全市场 5200+ 只 A 股，每日推荐符合亚当理论买入条件的标的。

## 快速开始

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/Scripts/activate  # Windows
pip install -e .               # 安装核心依赖
pip install -e .[dev]          # 含测试依赖

# 2. 首次回填全市场数据（5200 只股票，2 年日 K，~30-60 分钟）
python scripts/init_backfill.py --limit 100         # 测试：100 只
python scripts/init_backfill.py                     # 全量：5200 只
python scripts/init_backfill.py --force             # 强制重新下载

# 3. 生成每日推荐
python scripts/daily_update.py --limit 200          # Top 200 活跃股
python scripts/daily_update.py --no-update          # 跳过数据更新，仅分析
python scripts/daily_update.py --output html        # 仅输出 HTML 报告

# 4. 发送飞书通知
python scripts/notify_feishu.py --test              # 测试连接
python scripts/notify_feishu.py                     # 发送最新推荐

# 5. 运行测试
python -m pytest tests/ -v
```

## 亚当理论三条件（做多）

| # | 条件 | 判定标准 |
|---|------|----------|
| 1 | 突破 | 收盘价突破近 20 日最高价 |
| 2 | 趋势改变 | 前期下跌/盘整后，价格反转突破近期摆动高点 |
| 3 | 缺口/宽幅 | 跳空高开 ≥0.5% 或 当日振幅 ≥1.5x 20 日均值 |

**入场规则**: 三条件至少满足两个。**止损**: 近 40 根 K 线结构低点。

## 市场体制检测

系统自动判断当前市场环境，为推荐提供上下文：

| 体制 | 特征 |
|------|------|
| 上升趋势 | 价格持续走高，适合顺势买入 |
| 下降趋势 | 价格持续走低，逆势买入需谨慎 |
| 震荡盘整 | 价格区间波动，突破信号更值得关注 |
| 高波动 | 价格波动剧烈，建议缩小仓位严格止损 |

## 项目结构

```
├── config/                  # 配置层（settings + Pydantic 数据模型）
├── data/                    # 数据层
│   ├── sources/             #   可插拔多数据源（腾讯/baostock/akshare/efinance）
│   ├── store.py             #   按股票分区的 Parquet 存储 I/O
│   ├── filters.py           #   业务过滤（板块分类、活跃度预筛选）
│   └── pipeline.py          #   管道编排（全量回填 + 增量更新）
├── indicators/              # 亚当理论核心算法
│   ├── adams_theory.py      #   中心对称投影 + 三条件检测 + 结构止损
│   └── market_regime.py     #   市场体制检测（趋势/震荡/波动分类）
├── signals/                 # 信号检测 + 质量评分
├── recommendation/          # 推荐排名 + "一问规则" + 中文解释
├── pipeline/                # 每日流水线编排（DailyPipeline）
├── notification/            # 通知通道抽象层（飞书已实现）
├── reporting/               # 控制台 Rich 表格 + HTML Plotly 交互图表
├── scripts/                 # CLI 入口脚本
└── tests/                   # 44 个单元测试（纯合成数据，确定性种子）
```

## 数据来源

系统使用可插拔多数据源架构，按优先级自动选择：

| 数据源 | 速度 | 限流 | 说明 |
|--------|------|------|------|
| 腾讯证券（tencent） | 快 ~0.5s/只 | 较轻 | **默认首选**，通过 akshare 调用腾讯免费 API |
| baostock | 慢 ~1.5s/只 | 无限制 | **稳定备选**，自有服务器，适合全量回填 |
| akshare（东方财富） | 快 | 严重限流 | 备用，800-1500 请求后可能被封锁 |
| efinance | 快 | 较轻 | 实验性，支持批量查询 |

## 配置

所有参数通过 `.env` 文件配置（复制 `.env.example` 并修改）：

```bash
cp .env.example .env
# 编辑 .env 中的参数
```

核心可配置项：
- 数据源优先级和策略
- 检测阈值（突破回看、趋势回看、振幅倍数等）
- 板块权限（创业板/科创板/北交所开关）
- 风险上限和评分权重
- 飞书 Webhook URL

## 注意事项

- 首次回填约 30-60 分钟（多线程并发），支持断点续传
- 每日增量更新只需更新最近 1-2 个交易日，速度快
- 所有价格使用**前复权（qfq）**，与交易软件显示一致
- GitHub Actions 每日 16:00（北京时间）自动运行分析
- 本系统仅供研究参考，不构成投资建议。股市有风险，投资需谨慎。
