"""
logistics_reasoning_llm.py
──────────────────────────
Calls Gemini 2.0 Flash Preview to select the best vehicle.
Returns selected_vehicle_id + reasoning list.
"""

import json
import logging
import google.generativeai as genai

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """
You are the Logistics Reasoning Agent in an autonomous supply chain system.

Your ONLY job is to select the BEST vehicle from the candidates provided.

STRICT RULES:
- Choose the vehicle with the best balance of ML priority score, reliability, and sustainability.
- Consider total_qty vs capacity_qty — never select a vehicle that is under capacity.
- Return ONLY valid JSON. No markdown. No explanations outside the JSON.

Return exactly this structure:
{
  "selected_vehicle_id": "<vehicle_id>",
  "reasoning": [
    "<reason 1>",
    "<reason 2>",
    "<reason 3>"
  ]
}
"""


def select_vehicle(cluster: dict, candidates_with_scores: list, model) -> dict:
    """
    Parameters
    ----------
    cluster               : output from cluster_manager.create_cluster()
    candidates_with_scores: output from ml_fetch_service.attach_scores()
    model                 : a google.generativeai.GenerativeModel instance

    Returns
    -------
    {
        "selected_vehicle_id": str,
        "reasoning":           list[str]
    }
    """
    prompt = f"""
SYSTEM:
{_SYSTEM_PROMPT}

CLUSTER INFO:
{json.dumps({
    "cluster_id":    cluster["cluster_id"],
    "total_qty":     cluster["total_qty"],
    "delivery_mode": cluster["delivery_mode"],
    "order_count":   len(cluster["orders"]),
}, indent=2)}

VEHICLE CANDIDATES (with ML scores):
{json.dumps(candidates_with_scores, indent=2)}

Select the best vehicle. Return ONLY valid JSON.
"""

    logger.info(f"[LogisticsReasoningLLM] Sending prompt to Gemini for cluster={cluster['cluster_id']}")

    response = model.generate_content(prompt)

    raw = response.text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        decision = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"[LogisticsReasoningLLM] JSON parse error: {e}\nRaw: {raw}")
        raise ValueError(f"LLM did not return valid JSON: {e}")

    logger.info(
        f"[LogisticsReasoningLLM] Selected: {decision.get('selected_vehicle_id')} | "
        f"Reasons: {len(decision.get('reasoning', []))} points"
    )
    return decision
