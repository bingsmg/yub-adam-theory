"""
Final ranking and the "One Question" rule.

Per Adam's Theory: "Based on what the center symmetry chart shows,
do I want to trade today?" — only if unequivocally YES.

We keep the strongest signals, drop borderline ones.
"""

from __future__ import annotations

from loguru import logger

from config.schema import AdamSignal
from config.settings import settings
from signals.scorer import compute_quality_score


def apply_one_question_rule(signals: list[AdamSignal]) -> list[AdamSignal]:
    """
    Drop the weakest signals.

    Thresholds are configurable via settings:
    - <=RANK_KEEP_ALL_IF_LE signals: keep all
    - RANK_KEEP_ALL_IF_LE+1 ~ RANK_MID_THRESHOLD: keep RANK_KEEP_FRAC_MID fraction
    - >RANK_MID_THRESHOLD: keep RANK_KEEP_FRAC_HIGH fraction
    """
    if len(signals) <= settings.RANK_KEEP_ALL_IF_LE:
        return signals
    if len(signals) <= settings.RANK_MID_THRESHOLD:
        keep_n = max(settings.RANK_MIN_KEEP_MID, int(len(signals) * settings.RANK_KEEP_FRAC_MID))
    else:
        keep_n = max(settings.RANK_MIN_KEEP_HIGH, int(len(signals) * settings.RANK_KEEP_FRAC_HIGH))

    kept = signals[:keep_n]
    logger.info("One-question rule: kept {}/{} signals", len(kept), len(signals))
    return kept


def select_top_recommendations(
    signals: list[AdamSignal],
    top_n: int | None = None,
) -> list[AdamSignal]:
    """
    Rank → one-question filter → top N.
    """
    if top_n is None:
        top_n = settings.TOP_N_RECOMMENDATIONS
    if not signals:
        return []

    # Composite: quality² / risk
    scored = []
    for s in signals:
        q = compute_quality_score(s)
        composite = (q ** 2) / max(s.risk_score, 0.1)
        scored.append((composite, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [s for _, s in scored]

    filtered = apply_one_question_rule(ranked)
    return filtered[:top_n]
