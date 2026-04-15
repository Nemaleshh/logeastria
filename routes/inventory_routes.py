from flask import Blueprint, request, jsonify, render_template
from services.inventory_service import InventoryService

inventory_bp = Blueprint("inventory", __name__)
service = InventoryService()


@inventory_bp.route("/", methods=["GET"])
def inventory_page():
    return render_template("inventory.html")


@inventory_bp.route("/evaluate-production", methods=["POST"])
def evaluate_production():
    payload = request.json

    result = service.evaluate_production(
        finished_product_id=payload["finished_product_id"],
        quantity_to_produce=payload["quantity_to_produce"]
    )

    return jsonify(result)
