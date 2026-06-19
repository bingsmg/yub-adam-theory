# notification/ — 通知通道抽象层

## 概述

可插拔的消息通知框架。通过实现 `Notifier` 抽象基类可添加新通知通道（钉钉、企业微信、邮件、短信等）。

## 架构

```
notification/
├── base.py         # Notifier(ABC) — 通知通道抽象基类
├── feishu.py       # FeishuNotifier — 飞书机器人 webhook 实现
└── __init__.py     # 公共 API 导出
```

## Notifier ABC

```python
class Notifier(ABC):
    name: str = "base"

    @abstractmethod
    def send(self, recommendation: DailyRecommendation) -> bool:
        """发送每日推荐，返回 True/False"""
        ...
```

## 内置实现：FeishuNotifier

```python
from notification import FeishuNotifier

notifier = FeishuNotifier(webhook_url="https://open.feishu.cn/...")
notifier.send(recommendation)           # 富交互卡片
notifier.send_text(recommendation)      # 纯文本备用
notifier.send_test()                    # 测试连接
```

飞书卡片格式：
- 统计摘要（条件分布、平均风险、板块分布）
- Top 20 推荐（条件标记 B/T/R、风险 emoji、成交量热度、投影方向）
- 脚注和图例

## 扩展新通道

```python
from notification.base import Notifier

class DingTalkNotifier(Notifier):
    name = "dingtalk"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, recommendation: DailyRecommendation) -> bool:
        # 构建钉钉消息格式 + HTTP POST
        ...
```

## 配置

```bash
# .env
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
```
