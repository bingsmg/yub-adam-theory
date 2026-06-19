"""
通知通道抽象基类。

实现此类以添加新的通知通道（如钉钉、企业微信、邮件、短信）。
每个通知器接收完整的 DailyRecommendation 并返回成功/失败。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from config.schema import DailyRecommendation


class Notifier(ABC):
    """通知通道抽象基类。

    子类化并实现 send() 以添加新通道。
    """

    name: str = "base"

    @abstractmethod
    def send(self, recommendation: DailyRecommendation) -> bool:
        """通过此通道发送每日推荐。

        成功返回 True，失败返回 False。
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"
