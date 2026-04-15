"""
warehouse_routes.py — Flask blueprint for /warehouse/* endpoints
"""
from flask import Blueprint, jsonify, render_template, request
from services.warehouse_service import (
    get_capacity_overview, get_inventory_breakdown,
    get_finished_goods, get_wip_summary, get_ai_insights,
    run_warehouse_agent, run_order_allocation, run_reorder_check,
)

warehouse_bp = Blueprint("warehouse", __name__, url_prefix="/warehouse")

@warehouse_bp.route("/", methods=["GET"])
def warehouse_page():
    return render_template("warehouse.html")

@warehouse_bp.route("/capacity", methods=["GET"])
def capacity():
    return jsonify(get_capacity_overview())

@warehouse_bp.route("/inventory", methods=["GET"])
def inventory():
    return jsonify(get_inventory_breakdown())

@warehouse_bp.route("/finished-goods", methods=["GET"])
def finished_goods():
    return jsonify(get_finished_goods())

@warehouse_bp.route("/wip", methods=["GET"])
def wip():
    return jsonify(get_wip_summary())

@warehouse_bp.route("/insights", methods=["GET"])
def insights():
    return jsonify(get_ai_insights())


# ──────────────────────────────────────────────────────
# AI WAREHOUSE AGENT ENDPOINTS
# ──────────────────────────────────────────────────────

@warehouse_bp.route("/agent/analyze", methods=["POST"])
def agent_analyze():
    """Full warehouse agent analysis — state → rules → Gemini → decision."""
    try:
        result = run_warehouse_agent()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@warehouse_bp.route("/agent/allocate", methods=["POST"])
def agent_allocate():
    """Allocate specific orders to warehouses via Gemini reasoning."""
    try:
        body = request.get_json(silent=True) or {}
        order_ids = body.get("order_ids")
        result = run_order_allocation(order_ids=order_ids)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@warehouse_bp.route("/agent/reorder-check", methods=["GET"])
def agent_reorder_check():
    """Check all materials for reorder needs via Gemini reasoning."""
    try:
        result = run_reorder_check()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
