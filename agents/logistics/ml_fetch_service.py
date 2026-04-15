"""
ml_fetch_service.py
────────────────────
Attaches deterministic ML-style scores to vehicle candidates.
No external ML API required — scores are computed from vehicle properties.
"""

import logging

logger = logging.getLogger(__name__)

# Sustainability index (lower environmental impact = higher score)
_SUSTAINABILITY = {"Bike": 1.0, "Van": 0.75, "Truck": 0.50}

# Mode urgency multiplier
_MODE_MULTIPLIER = {"express": 1.2, "economic": 1.0, "standard": 0.85}


def attach_scores(candidates: list) -> list:
    """
    Enriches each candidate vehicle with:
    - priority_score_ml    : composite score (capacity efficiency × mode fit)
    - reliability_score    : fixed per vehicle type
    - sustainability_score : eco-friendliness index

    Returns the enriched list sorted by priority_score_ml descending.
    """
    if not candidates:
        logger.warning("[MLFetchService] No candidates to score.")
        return candidates

    # Normalise capacity_qty for scoring
    max_cap = max(v["capacity_qty"] for v in candidates)

    enriched = []
    for v in candidates:
        cap_norm       = v["capacity_qty"] / max_cap            # 0–1
        mode_mult      = _MODE_MULTIPLIER.get(v["delivery_mode"], 1.0)
        sustainability = _SUSTAINABILITY.get(v["type"], 0.6)
        reliability    = round(0.7 + (cap_norm * 0.25), 4)     # 0.70–0.95 range

        priority_score = round(
            (cap_norm * 0.40) + (sustainability * 0.35) + (reliability * 0.25) * mode_mult,
            4,
        )

        enriched.append({
            **v,
            "priority_score_ml":  priority_score,
            "reliability_score":  reliability,
            "sustainability_score": sustainability,
        })

        logger.debug(
            f"[MLFetchService] {v['vehicle_id']} | "
            f"priority={priority_score} | reliability={reliability} | "
            f"sustainability={sustainability}"
        )

    enriched.sort(key=lambda x: x["priority_score_ml"], reverse=True)
    logger.info(
        f"[MLFetchService] Scored {len(enriched)} candidates. "
        f"Top pick: {enriched[0]['vehicle_id']} (score={enriched[0]['priority_score_ml']})"
    )
    return enriched
