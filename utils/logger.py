"""Structured logging via loguru."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logging(log_dir: str | Path = "output", level: str = "INFO") -> None:
    """Configure loguru with console + file sinks."""
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # Remove default handler
    logger.remove()

    # Console — compact format
    logger.add(
        sys.stderr,
        format="<level>{level: <8}</level> | <cyan>{time:HH:mm:ss}</cyan> | <level>{message}</level>",
        level=level,
        colorize=True,
    )

    # File — detailed format with rotation
    logger.add(
        log_dir / "stock_picker_{time:YYYY-MM-DD}.log",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} | {message}",
        level="DEBUG",
        rotation="10 MB",
        retention="30 days",
        encoding="utf-8",
    )

    logger.info("Logging configured — level={}", level)


# Convenience re-export
__all__ = ["logger", "setup_logging"]
