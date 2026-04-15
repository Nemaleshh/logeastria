"""
logistics_routes.py
────────────────────
Blueprint:
  GET  /logistics                   → serve logistics.html
  POST /logistics/plan              → run AutonomousOrchestratorAgent.plan_logistics()

  POST /logistics/delivery/verify   → verify delivery PIN, mark DELIVERED
  GET  /logistics/shipments         → list all shipments
  GET  /logistics/shipments/active  → list IN_TRANSIT + INCIDENT shipments

  POST /logistics/incident/report   → report transport incident → LLM recovery plan
  POST /logistics/incident/resolve  → mark incident as RESOLVED
  GET  /logistics/incidents         → list all incidents
  GET  /logistics/incidents/open    → list OPEN incidents

  GET  /logistics/weather           → weather for a lat/lng (or mock)
"""

import os
import logging
from flask import Blueprint, request, jsonify, render_template

from agents.logistics.autonomous_orchestrator_agent import AutonomousOrchestratorAgent
from agents.logistics import delivery_verifier, transport_fallback_agent, weather_service

logger = logging.getLogger(__name__)

logistics_bp = Blueprint("logistics", __name__)

_agent: AutonomousOrchestratorAgent | None = None


_GEMINI_API_KEY = "AIzaSyCRUmzBqn9WUn8YxlOc5hmN7_JCotCHq_w"


def _get_agent() -> AutonomousOrchestratorAgent:
    global _agent
    if _agent is None:
        api_key = os.environ.get("GEMINI_API_KEY", _GEMINI_API_KEY)
        _agent = AutonomousOrchestratorAgent(api_key=api_key)
    return _agent


# ─────────────────────────────────────────────────────────────────────────────
# Page
# ─────────────────────────────────────────────────────────────────────────────

@logistics_bp.route("/logistics", methods=["GET"])
def logistics_page():
    return render_template("logistics.html")


@logistics_bp.route("/logistics/sim", methods=["GET"])
def logistics_sim():
    return render_template("logistics_sim.html")


# ─────────────────────────────────────────────────────────────────────────────
# Plan
# ─────────────────────────────────────────────────────────────────────────────

@logistics_bp.route("/logistics/plan", methods=["POST"])
def plan_logistics():
    """
    Body: { "orders": ["O001", "O002", "O003"] }

    Returns full plan including shipment_id and delivery_pin.
    """
    body = request.get_json(force=True) or {}
    order_ids = body.get("orders", [])

    if not order_ids:
        return jsonify({"error": "Provide at least one order ID in 'orders' list."}), 400

    try:
        result = _get_agent().plan_logistics(order_ids)
        return jsonify(result), 200
    except RuntimeError as e:
        logger.error(f"[LogisticsRoute] RuntimeError: {e}")
        return jsonify({"error": str(e)}), 422
    except Exception as e:
        logger.exception("[LogisticsRoute] Unexpected error in plan_logistics")
        return jsonify({"error": "Internal server error.", "detail": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
# Delivery Verification
# ─────────────────────────────────────────────────────────────────────────────

@logistics_bp.route("/logistics/delivery/verify", methods=["POST"])
def verify_delivery():
    """
    Body: { "shipment_id": "SHP-XXXX", "pin": "4821", "verified_by": "driver" }

    Returns: { "success": bool, "message": str, "status": str }
    """
    body = request.get_json(force=True) or {}
    shipment_id  = body.get("shipment_id", "").strip()
    entered_pin  = str(body.get("pin", "")).strip()
    verified_by  = body.get("verified_by", "driver")

    if not shipment_id or not entered_pin:
        return jsonify({"error": "Provide 'shipment_id' and 'pin'."}), 400

    result = delivery_verifier.verify_pin(
        shipment_id=shipment_id,
        entered_pin=entered_pin,
        verified_by=verified_by,
    )
    status_code = 200 if result.get("success") else 422
    return jsonify(result), status_code


@logistics_bp.route("/logistics/shipments", methods=["GET"])
def get_shipments():
    return jsonify(delivery_verifier.get_all_shipments()), 200


@logistics_bp.route("/logistics/shipments/active", methods=["GET"])
def get_active_shipments():
    return jsonify(delivery_verifier.get_active_shipments()), 200


# ─────────────────────────────────────────────────────────────────────────────
# Transport Incidents (Fallback)
# ─────────────────────────────────────────────────────────────────────────────

@logistics_bp.route("/logistics/incident/report", methods=["POST"])
def report_incident():
    """
    Body:
    {
      "shipment_id":   "SHP-XXXX",
      "vehicle_id":    "V2",
      "incident_type": "PUNCTURE",
      "description":   "Front tyre burst near Highway 44"
    }

    Returns LLM recovery plan:
    {
      "incident_id", "action", "severity", "estimated_delay_min",
      "steps", "notify_customer", "summary", "status"
    }
    """
    body = request.get_json(force=True) or {}
    required = ["shipment_id", "vehicle_id", "incident_type", "description"]
    for k in required:
        if not body.get(k):
            return jsonify({"error": f"Missing required field: '{k}'."}), 400

    try:
        agent = _get_agent()
        result = transport_fallback_agent.report_incident(
            shipment_id=body["shipment_id"],
            vehicle_id=body["vehicle_id"],
            incident_type=body["incident_type"].upper(),
            description=body["description"],
            model=agent.model,
        )
        return jsonify(result), 200
    except Exception as e:
        logger.exception("[LogisticsRoute] Error in report_incident")
        return jsonify({"error": str(e)}), 500


@logistics_bp.route("/logistics/incident/resolve", methods=["POST"])
def resolve_incident():
    """Body: { "incident_id": "INC-XXXX" }"""
    body = request.get_json(force=True) or {}
    incident_id = body.get("incident_id", "").strip()
    if not incident_id:
        return jsonify({"error": "Provide 'incident_id'."}), 400
    result = transport_fallback_agent.resolve_incident(incident_id)
    return jsonify(result), 200 if result.get("success") else 404


@logistics_bp.route("/logistics/incidents", methods=["GET"])
def get_incidents():
    return jsonify(transport_fallback_agent.get_all_incidents()), 200


@logistics_bp.route("/logistics/incidents/open", methods=["GET"])
def get_open_incidents():
    return jsonify(transport_fallback_agent.get_open_incidents()), 200


# ─────────────────────────────────────────────────────────────────────────────
# Weather
# ─────────────────────────────────────────────────────────────────────────────

@logistics_bp.route("/logistics/weather", methods=["GET"])
def get_weather():
    """
    Query params: ?lat=12.97&lng=77.59
    Returns weather dict (mock or live depending on WEATHER_API_KEY).
    """
    try:
        lat = float(request.args.get("lat", 12.9716))
        lng = float(request.args.get("lng", 77.5946))
    except ValueError:
        return jsonify({"error": "lat/lng must be numeric."}), 400

    return jsonify(weather_service.get_weather(lat, lng)), 200
