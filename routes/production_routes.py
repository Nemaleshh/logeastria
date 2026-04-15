from flask import Blueprint, request, jsonify
from services.production_service import ProductionService

production_bp = Blueprint("production", __name__, url_prefix="/production")
service = ProductionService()

from flask import render_template

@production_bp.route("/", methods=["GET"])
def production_ui():
    return render_template("production.html")


@production_bp.route("/create", methods=["POST"])
def create_production():
    return jsonify(service.create_production(request.json))


@production_bp.route("/material-issued", methods=["POST"])
def material_issued():
    return jsonify(service.update_stage(
        request.json, completed_stage="MATERIAL_ISSUED"
    ))


@production_bp.route("/fabrication", methods=["POST"])
def fabrication():
    return jsonify(service.update_stage(
        request.json, completed_stage="FABRICATION"
    ))


@production_bp.route("/assembly", methods=["POST"])
def assembly():
    return jsonify(service.update_stage(
        request.json, completed_stage="ASSEMBLY"
    ))


@production_bp.route("/painting", methods=["POST"])
def painting():
    return jsonify(service.update_stage(
        request.json, completed_stage="PAINTING"
    ))


@production_bp.route("/quality-check", methods=["POST"])
def quality_check():
    return jsonify(service.quality_check(request.json))


import pandas as pd
import os
import json

@production_bp.route("/rejected", methods=["GET"])
def get_rejected_items():
    qc_log_path = "data_base/quality_check_log.csv"
    if not os.path.exists(qc_log_path):
        return jsonify([])
    
    try:
        df = pd.read_csv(qc_log_path)
        # Convert NaN values to None for clean JSON serialization
        df = df.where(pd.notnull(df), None)
        
        items = []
        for _, row in df.iterrows():
            item = row.to_dict()
            # Try to parse the LLM suggestions if it's a JSON string
            if isinstance(item.get("llm_suggestions"), str):
                # Clean up markdown code block formatting if present
                clean_json = item["llm_suggestions"].strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]
                if clean_json.startswith("```"):
                    clean_json = clean_json[3:]
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]
                clean_json = clean_json.strip()
                
                try:
                    item["llm_suggestions"] = json.loads(clean_json)
                except Exception:
                    pass # Keep as string if parsing fails
            items.append(item)
            
        return jsonify(items)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
