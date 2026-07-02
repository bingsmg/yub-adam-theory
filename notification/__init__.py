"""
Notification abstraction layer.

Add new channels by subclassing Notifier and implementing send().
Built-in channels:
  - FeishuNotifier: 飞书 bot webhook
  - WecomNotifier: 企业微信群机器人 webhook

Usage:
    from notification import FeishuNotifier
    notifier = FeishuNotifier()
    notifier.send(recommendation)
"""

from __future__ import annotations

from notification.base import Notifier
from notification.feishu import FeishuNotifier, build_feishu_card, build_feishu_card_from_rows, build_feishu_text
from notification.wecom import WecomNotifier

__all__ = [
    "Notifier",
    "FeishuNotifier",
    "WecomNotifier",
    "build_feishu_card",
    "build_feishu_card_from_rows",
    "build_feishu_text",
]
