from flask import Blueprint, request, jsonify, render_template
from services.procurement_service import ProcurementService

procurement_bp = Blueprint("procurement", __name__, url_prefix="/procurement")
service = ProcurementService()


@procurement_bp.route("/", methods=["GET"])
def procurement_page():
    return render_template("procurement.html")


@procurement_bp.route("/orders", methods=["GET"])
def list_orders():
    status_filter = request.args.get("status")
    orders = service.list_purchase_orders(status_filter=status_filter)
    return jsonify(orders)


@procurement_bp.route("/approve", methods=["POST"])
def approve_order():
    po_id = request.json.get("po_id")
    if not po_id:
        return jsonify({"status": "ERROR", "message": "po_id is required"}), 400
    return jsonify(service.approve_po(po_id))


@procurement_bp.route("/reject", methods=["POST"])
def reject_order():
    po_id = request.json.get("po_id")
    if not po_id:
        return jsonify({"status": "ERROR", "message": "po_id is required"}), 400
    return jsonify(service.reject_po(po_id))

@procurement_bp.route("/receive", methods=["POST"])
def receive_order():
    payload = request.json
    if not payload or not payload.get("po_id"):
        return jsonify({"status": "ERROR", "message": "po_id is required"}), 400
    
    return jsonify(service.receive_po(payload))
