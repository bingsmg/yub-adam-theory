# scripts/ — 入口脚本

## 概述

用户直接运行的命令行入口。每个脚本有独立的 argparse 参数。

## 脚本清单

| 脚本 | 用途 | 频率 |
|------|------|------|
| `init_backfill.py` | 首次全量回填：下载所有 A 股 2 年日线 | 一次性 |
| `daily_update.py` | 每日增量更新 + 亚当理论检测 + 报告生成 | 每日 |
| `check_coverage.py` | 数据覆盖率诊断：文件数、最新日期、预筛选模拟 | 按需 |
| `notify_feishu.py` | 飞书机器人推送推荐结果 | 每日（CI/cron 调用） |
| `cron_daily.sh` | WSL cron 定时任务脚本 | 定时 |
| `run_daily.bat` | Windows 任务计划程序入口（.bat 版本） | 定时 |
| `run_daily.ps1` | Windows 任务计划程序入口（PowerShell 增强版，含通知） | 定时 |

## 常用命令

```bash
# 激活虚拟环境（必须）
source .venv/Scripts/activate

# 首次回填
python scripts/init_backfill.py                       # 全量 ~30-60min
python scripts/init_backfill.py --limit 100           # 测试 100 只

# 每日更新
python scripts/daily_update.py                        # 完整流程
python scripts/daily_update.py --no-update --limit 200  # 快扫 200 只
python scripts/daily_update.py --output html           # 仅 HTML

# 覆盖率检查
python scripts/check_coverage.py

# 飞书通知
python scripts/notify_feishu.py --test                 # 测试连接
python scripts/notify_feishu.py                        # 发送最新推荐
```

## 设计原则

- `daily_update.py` 委托给 `pipeline.DailyPipeline`，脚本层仅处理 CLI 参数
- `notify_feishu.py` 委托给 `notification.FeishuNotifier`
- 所有脚本通过 `sys.path.insert` 确保可从项目根目录运行
- 数据源可通过环境变量动态覆盖：`DATA_SOURCE_ORDER='["baostock"]' python scripts/daily_update.py`
