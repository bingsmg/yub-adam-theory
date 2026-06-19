"""通过 loguru 实现结构化日志。"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logging(log_dir: str | Path = "output", level: str = "INFO") -> None:
    """配置 loguru 的控制台和文件输出。"""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # 移除默认处理器
    logger.remove()

    # 控制台 — 紧凑格式
    logger.add(
        sys.stderr,
        format="<level>{level: <8}</level> | <cyan>{time:HH:mm:ss}</cyan> | <level>{message}</level>",
        level=level,
        colorize=True,
    )

    # 文件 — 详细格式，自动轮转
    logger.add(
        log_dir / "stock_picker_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="30 days",
        encoding="utf-8",
    )

    logger.info("Logging configured — level={}", level)


# 便捷再导出
__all__ = ["logger", "setup_logging"]
