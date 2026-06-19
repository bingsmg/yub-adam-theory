"""
Pipeline orchestration layer.

DailyPipeline encapsulates the full Adam's Theory workflow:
update → filter → detect → score → rank → explain → report

Usage:
    from pipeline import DailyPipeline
    pipeline = DailyPipeline()
    result = pipeline.run(limit=200)
"""

from __future__ import annotations

from pipeline.daily_pipeline import DailyPipeline

__all__ = ["DailyPipeline"]
