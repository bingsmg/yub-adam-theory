"""
Notification channel abstract base class.

Implement this to add new notification channels (e.g. DingTalk,
WeChat Work, email, SMS). Each notifier receives the full
DailyRecommendation and returns success/failure.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from config.schema import DailyRecommendation


class Notifier(ABC):
    """Abstract base for notification channels.

    Subclass and implement send() to add a new channel.
    """

    name: str = "base"

    @abstractmethod
    def send(self, recommendation: DailyRecommendation) -> bool:
        """Send a daily recommendation via this channel.

        Returns True on success, False on failure.
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"
