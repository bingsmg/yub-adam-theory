"""
Signal quality scoring — pure Adam's Theory criteria.

Quality components:
  - Condition count & strength: 3 conditions > 2, higher strength = better
  - Projection favorability: up direction + convergence = better
  - Volume confirmation: higher relative volume = stronger conviction

Weights are configurable via settings.SCORE_WEIGHTS.
"""

from __future__ import annotations

import numpy as np

from config.schema import AdamSignal
from config.settings import settings


def compute_quality_score(signal: AdamSignal) -> float:
    """Compute quality score 0-100 based on Adam's Theory factors."""
    clue_count = len(signal.clues)
    w_cond, w_proj, w_vol = settings.SCORE_WEIGHTS

    # ── Condition component ──
    if clue_count >= 3:
        avg_strength = float(np.mean([c.strength for c in signal.clues]))
        condition_score = 70 + 30 * avg_strength
    elif clue_count == 2:
        avg_strength = float(np.mean([c.strength for c in signal.clues]))
        condition_score = 40 + 30 * avg_strength
    else:
        condition_score = 10

    # ── Projection component ──
    proj = signal.projection
    if proj.projected_direction == "up":
        proj_score = 60 + 40 * proj.convergence_score
    elif proj.projected_direction == "neutral":
        proj_score = 30 + 30 * proj.convergence_score
    else:
        proj_score = 10 + 20 * proj.convergence_score

    # ── Volume component ──
    if signal.volume_ratio > 2.0:
        vol_score = 100
    elif signal.volume_ratio > 1.5:
        vol_score = 85
    elif signal.volume_ratio > 1.0:
        vol_score = 65
    elif signal.volume_ratio > 0.7:
        vol_score = 45
    else:
        vol_score = 25

    weights = [w_cond, w_proj, w_vol]
    components = [condition_score, proj_score, vol_score]
    quality = sum(w * c for w, c in zip(weights, components))

    return round(min(100.0, max(0.0, quality)), 1)


def rank_signals(signals: list[AdamSignal]) -> list[AdamSignal]:
    """Rank by quality/risk composite."""
    if not signals:
        return []

    scored = [(s, compute_quality_score(s)) for s in signals]
    scored.sort(key=lambda x: x[1] ** 2 / max(x[0].risk_score, 0.1), reverse=True)

    return [s for s, _ in scored]
