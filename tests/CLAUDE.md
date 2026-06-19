# tests/ — 测试

## 概述

18 个测试，全部使用合成 OHLCV 数据，不调用真实 API。

## 测试文件

| 文件 | 测试数 | 覆盖范围 |
|------|--------|----------|
| `test_adams_theory.py` | 14 | 核心算法：投影(3)、突破(2)、趋势改变(1)、缺口宽幅(2)、组合检测(4)、结构止损(2) |
| `test_detector.py` | 3 | 检测流水线：数据不足、正常数据不崩溃、输出结构验证 |
| `test_sources.py` | 26+ | 数据源层：列标准化(5)、ABC(3)、baostock模拟(4)、akshare模拟(4)、策略(4)、并行(3)、工厂(3) |

## 运行

```bash
source .venv/Scripts/activate
python -m pytest tests/ -v           # 全部 18 个测试
python -m pytest tests/ -v -k breakout  # 只运行匹配关键字的测试
```

## Fixtures (conftest.py)

所有 fixture 使用 `_make_df()` 构建干净的 OHLCV DataFrame：

| Fixture | 描述 |
|---------|------|
| `uptrend_df` | 100 根 K 线，线性上升+噪声 |
| `downtrend_df` | 100 根 K 线，线性下降+噪声 |
| `ranging_df` | 100 根 K 线，横盘震荡 |
| `breakout_df` | 40 根紧缩+5 根突破（放量） |
| `trend_change_df` | 60 根下降+20 根反转上涨 |
| `range_expansion_df` | 60 根低波动+1 根大幅区间扩展 |

## 设计原则

- 永不调用真实 API
- 使用 mock 测试数据源层（unittest.mock.patch）
- 合成数据可精确控制，确保测试确定性
- 测试参数化覆盖边界条件
