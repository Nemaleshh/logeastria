"""
orchestrator_routes.py — Flask blueprint for the Central Orchestrator chat API

POST /orchestrator/chat   → { "message": "..." }  → Gemini-powered answer
GET  /orchestrator/alerts  → current high-risk alerts across all subsystems
"""

from flask import Blueprint, request, jsonify
import logging

logger = logging.getLogger("ERP.Orchestrator")

orchestrator_bp = Blueprint("orchestrator", __name__, url_prefix="/orchestrator")

# ── lazy singleton ────────────────────────────────────
_agent = None

def _get_agent():
    global _agent
    if _agent is None:
        from agents.central_orchestrator import CentralOrchestrator
        API_KEY = "AIzaSyB-k0qWSfsB4ok2nIyreTuLORsxChbYTAA"
        _agent = CentralOrchestrator(api_key=API_KEY)
    return _agent


@orchestrator_bp.route("/chat", methods=["POST"])
def chat():
    """
    Accepts: { "message": "<user question>" }
    Returns: Gemini structured analysis JSON
    """
    body = request.get_json(force=True, silent=True) or {}
    user_message = body.get("message", "").strip()

    if not user_message:
        return jsonify({"error": "Missing 'message' field"}), 400

    logger.info(f"[Orchestrator Chat] query={user_message[:80]}...")

    try:
        result = _get_agent().answer_query(user_message)
        return jsonify(result), 200
    except Exception as e:
        logger.exception("Orchestrator chat error")
        return jsonify({"error": str(e)}), 500


@orchestrator_bp.route("/alerts", methods=["GET"])
def alerts():
    """
    Returns current high-risk alerts from all subsystems.
    """
    try:
        alert_list = _get_agent().scan_alerts()
        return jsonify(alert_list), 200
    except Exception as e:
        logger.exception("Orchestrator alerts error")
        return jsonify({"error": str(e)}), 500
