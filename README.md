# Adam's Theory A-Share Stock Picker

A股亚当理论股票推荐系统。基于 J. Welles Wilder Jr. 的亚当理论（中心对称投影 + 三条件入场），扫描全市场5200+只A股，每日推荐符合亚当理论买入条件的标的。

## 快速开始

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/Scripts/activate  # Windows
pip install -r requirements.txt

# 2. 首次回填全市场数据（5200只股票，2年日K，约2小时）
python scripts/init_backfill.py --limit 200      # 测试：200只
python scripts/init_backfill.py                  # 全量：5200只

# 3. 生成每日推荐
python scripts/daily_update.py --limit 200       # Top 200 活跃股
python scripts/daily_update.py                   # 按配置分析

# 4. 运行测试
python -m pytest tests/ -v
```

## 亚当理论三条件（做多）

| # | 条件 | 判定标准 |
|---|------|----------|
| 1 | 突破 | 收盘价突破近20日最高价 |
| 2 | 趋势改变 | 前期下跌/盘整后，价格反转突破颈线 |
| 3 | 缺口/宽幅 | 跳空高开≥0.5% 或 当日振幅≥1.5x20日均值 |

**入场规则**: 三条件至少满足两个。**止损**: 近40根K线结构低点。

## 项目结构

```
├── main.py                  # CLI入口
├── config/                  # 配置 + 数据模型
├── data/                    # 数据获取 + 存储
│   └── consolidated_store.py  # 单文件存储（all_stocks.parquet）
├── indicators/              # 亚当理论核心算法
│   └── adams_theory.py      # 中心对称投影 + 三条件检测
├── signals/                 # 信号检测 + 评分
├── recommendation/          # 推荐管线 + 解释
├── reporting/               # 控制台 + HTML报告
├── backtesting/             # 回测引擎
├── scripts/                 # 运维脚本
└── tests/                   # 测试（纯合成数据）
```

## 数据来源

- **baostock**（主力）：无频率限制，稳定，前复权数据
- **akshare**（备用）：东方财富数据源，有限流

## 注意事项

- 首次回填约2小时（baostock单session顺序下载），支持断点续传
- 每日增量更新只需更新最近1-2个交易日，速度快
- 所有价格使用**前复权(qfq)**，与交易软件显示一致
- 本系统仅供研究参考，不构成投资建议
