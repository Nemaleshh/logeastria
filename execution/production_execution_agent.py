import pandas as pd
from datetime import datetime
import os
import json
import logging
import google.generativeai as genai
logger = logging.getLogger("ERP.Production")


STAGE_SEQUENCE = [
    "MATERIAL_ISSUED",
    "FABRICATION",
    "ASSEMBLY",
    "PAINTING",
    "QUALITY_CHECK",
    "COMPLETED"
]


class ProductionExecutionAgent:

    def __init__(self, db_path: str, event_router=None, demand_config=None, policy_config=None, api_key=None):


        self.db_path = db_path
        self.event_router = event_router
        self.production_orders_path = f"{db_path}/production_orders.csv"
        self.wip_path = f"{db_path}/wip_tracking.csv"
        self.fg_inventory_path = f"{db_path}/finished_goods_inventory.csv"
        self.inventory_path = f"{db_path}/inventory.csv"
        self.bom_path = f"{db_path}/bom.csv"
        self.qc_log_path = f"{db_path}/quality_check_log.csv"
        self.demand_config = demand_config or {}
        self.policy_config = policy_config or {}

        # Gemini model for QC failure suggestions
        if api_key:
            genai.configure(api_key=api_key)
            self.qc_model = genai.GenerativeModel("gemini-2.0-flash")
        else:
            self.qc_model = None

        self._initialize_files()

    def _initialize_files(self):

        os.makedirs(self.db_path, exist_ok=True)

        files = {
            self.production_orders_path: [
                "production_id","order_id","product_id",
                "target_quantity","current_stage","status",
                "created_at","last_updated"
            ],
            self.wip_path: [
                "production_id","stage_name","quantity",
                "status","last_updated"
            ],
            self.fg_inventory_path: [
                "product_id","current_stock","last_updated"
            ],
            self.inventory_path: [
                "product_id","current_stock","last_updated"
            ],
            self.bom_path: [
                "finished_product_id","component_product_id","quantity_required"
            ],
            self.qc_log_path: [
                "production_id","product_id","quantity_failed",
                "stage_returned_to","timestamp","llm_suggestions"
            ]
        }

        for path, columns in files.items():
            if not os.path.exists(path):
                pd.DataFrame(columns=columns).to_csv(path, index=False)

    def run(self, input_data):

        action = input_data.get("action")

        if action == "CREATE_PRODUCTION":
            return self._create_production(input_data["production_data"])

        if action == "UPDATE_STAGE":
            return self._update_stage(input_data["stage_update"])

        return {
            "status": "ERROR",
            "message": "Invalid action"
        }

    # ---------------- CREATE ---------------- #

    def _create_production(self, data):
        now = datetime.now().isoformat()

        prod_df = pd.read_csv(self.production_orders_path)
        wip_df = pd.read_csv(self.wip_path)

        # -----------------------------
        # DUPLICATE CHECK (IMPORTANT)
        # -----------------------------
        if data["production_id"] in prod_df["production_id"].values:
            return {
                "status": "ERROR",
                "message": "Production ID already exists in production_orders"
            }

        if data["production_id"] in wip_df["production_id"].values:
            return {
                "status": "ERROR",
                "message": "Production ID already exists in WIP"
            }

        # -----------------------------
        # CREATE PRODUCTION ORDER
        # -----------------------------
        new_row = {
            "production_id": data["production_id"],
            "order_id": data["order_id"],
            "product_id": data["product_id"],
            "target_quantity": data["target_quantity"],
            "current_stage": "MATERIAL_ISSUED",
            "status": "CREATED",
            "created_at": now,
            "last_updated": now
        }

        prod_df = pd.concat([prod_df, pd.DataFrame([new_row])], ignore_index=True)
        prod_df.to_csv(self.production_orders_path, index=False)

        # -----------------------------
        # CREATE WIP ENTRY
        # -----------------------------
        wip_row = {
            "production_id": data["production_id"],
            "stage_name": "MATERIAL_ISSUED",
            "quantity": data["target_quantity"],
            "status": "IN_PROGRESS",
            "last_updated": now
        }

        wip_df = pd.concat([wip_df, pd.DataFrame([wip_row])], ignore_index=True)
        wip_df.to_csv(self.wip_path, index=False)

        return {
            "status": "SUCCESS",
            "production_id": data["production_id"],
            "previous_stage": "",
            "new_stage": "MATERIAL_ISSUED",
            "quantity_processed": data["target_quantity"],
            "production_status": "CREATED",
            "message": "Production created"
        }


    # ---------------- UPDATE ---------------- #

    def _update_stage(self, data):

        now = datetime.now().isoformat()
        logger.info(f"Event Router attached? {self.event_router is not None}")

        prod_df = pd.read_csv(self.production_orders_path)
        wip_df = pd.read_csv(self.wip_path)
        fg_df = pd.read_csv(self.fg_inventory_path)

        production_id = data["production_id"]
        completed_stage = data["completed_stage"]
        quantity_completed = data["quantity_completed"]
        qc_passed = data.get("qc_passed", True)

        prod_row = prod_df[prod_df["production_id"] == production_id]

        if prod_row.empty:
            return {"status": "ERROR", "message": "Production not found"}

        current_stage = prod_row.iloc[0]["current_stage"]

        if completed_stage != current_stage:
            return {"status": "ERROR", "message": "Invalid stage transition"}

        # ============================================================
        # 🔽 INVENTORY REDUCTION LOGIC ADDED (MATERIAL_ISSUED ONLY)
        # ============================================================
        if completed_stage == "MATERIAL_ISSUED":
                        
            inventory_df = pd.read_csv(self.inventory_path)
            bom_df = pd.read_csv(self.bom_path)

            product_id = prod_row.iloc[0]["product_id"]

            product_bom = bom_df[
                bom_df["finished_product_id"] == product_id
            ]

            if product_bom.empty:
                return {
                    "status": "ERROR",
                    "message": "No BOM defined for this product"
                }

            # VALIDATION FIRST
            for _, bom_row in product_bom.iterrows():

                component_id = bom_row["component_product_id"]
                per_unit_required = bom_row["quantity_required"]

                total_required = per_unit_required * quantity_completed

                inv_row = inventory_df[
                    inventory_df["product_id"] == component_id
                ]

                if inv_row.empty or \
                inv_row.iloc[0]["current_stock"] < total_required:

                    return {
                        "status": "ERROR",
                        "message": "Insufficient raw material",
                        "product_id": component_id
                    }

            # REDUCTION (after validation)
            affected_materials = []

            for _, bom_row in product_bom.iterrows():

                component_id = bom_row["component_product_id"]
                per_unit_required = bom_row["quantity_required"]

                total_required = per_unit_required * quantity_completed

                # get correct inventory row
                inv_row = inventory_df[
                    inventory_df["product_id"] == component_id
                ]

                # optional warehouse column support
                if "warehouse_location" in inventory_df.columns:
                    warehouse_location = inv_row.iloc[0]["warehouse_location"]
                else:
                    warehouse_location = "WH1"

                # reduce stock
                inventory_df.loc[
                    inventory_df["product_id"] == component_id,
                    "current_stock"
                ] -= total_required

                inventory_df.loc[
                    inventory_df["product_id"] == component_id,
                    "last_updated"
                ] = now

                affected_materials.append({
                    "material_id": component_id,
                    "quantity_consumed": total_required,
                    "warehouse_location": warehouse_location
                })
            inventory_df.to_csv(self.inventory_path, index=False)

            # Emit event only if router exists
            if self.event_router:

                inventory_event = {
                    "event_type": "INVENTORY_UPDATED",
                    "source": "ProductionExecutionAgent",
                    "timestamp": now,
                    "production_id": production_id,
                    "finished_product_id": product_id,
                    "affected_materials": affected_materials
                }
                logger.info(
                    f"Emitting INVENTORY_UPDATED event for Production {production_id}"
                )

                erp_response = self.event_router.handle_inventory_event(
                    inventory_df=inventory_df,
                    inventory_event=inventory_event,
                    demand_config=self.demand_config,
                    policy_config=self.policy_config
                )
                orchestration_result = erp_response.get("orchestration_result") if erp_response else None
            else:
                orchestration_result = None
        else:
            orchestration_result = None
        # ============================================================

        # QUALITY CHECK SPECIAL LOGIC
        if completed_stage == "QUALITY_CHECK":

            if qc_passed:

                prod_df.loc[prod_df["production_id"] == production_id,
                            ["current_stage","status","last_updated"]] = [
                                "COMPLETED","COMPLETED",now
                            ]

                product_id = prod_row.iloc[0]["product_id"]

                if product_id in fg_df["product_id"].values:
                    fg_df.loc[fg_df["product_id"] == product_id,
                              "current_stock"] += quantity_completed
                    fg_df.loc[fg_df["product_id"] == product_id,
                              "last_updated"] = now
                else:
                    fg_df = pd.concat([fg_df, pd.DataFrame([{
                        "product_id": product_id,
                        "current_stock": quantity_completed,
                        "last_updated": now
                    }])])

                wip_df.loc[
                    (wip_df["production_id"] == production_id) &
                    (wip_df["stage_name"] == completed_stage),
                    ["status","last_updated"]
                ] = ["COMPLETED", now]

                prod_df.to_csv(self.production_orders_path, index=False)
                wip_df.to_csv(self.wip_path, index=False)
                fg_df.to_csv(self.fg_inventory_path, index=False)

                return {
                    "status": "SUCCESS",
                    "production_id": production_id,
                    "previous_stage": "QUALITY_CHECK",
                    "new_stage": "COMPLETED",
                    "quantity_processed": quantity_completed,
                    "production_status": "COMPLETED",
                    "message": "Production completed"
                }

            else:

                prod_df.loc[prod_df["production_id"] == production_id,
                            ["current_stage","status","last_updated"]] = [
                                "ASSEMBLY","REWORK",now
                            ]

                wip_df = pd.concat([wip_df, pd.DataFrame([{
                    "production_id": production_id,
                    "stage_name": "ASSEMBLY",
                    "quantity": quantity_completed,
                    "status": "REWORK",
                    "last_updated": now
                }])])

                prod_df.to_csv(self.production_orders_path, index=False)
                wip_df.to_csv(self.wip_path, index=False)

                # -----------------------------------------
                # LLM Recovery Suggestions (Gemini)
                # -----------------------------------------
                llm_suggestions = ""
                if self.qc_model:
                    try:
                        product_id = prod_row.iloc[0]["product_id"]
                        prompt = f"""You are a manufacturing quality control expert.

A product has FAILED quality check in our production line. Provide recovery suggestions.

Context:
- Production ID: {production_id}
- Product ID: {product_id}
- Quantity Failed: {quantity_completed}
- Stage Returned To: ASSEMBLY (for rework)

Provide your response as JSON with this structure:
{{
  "root_cause_analysis": ["possible cause 1", "possible cause 2"],
  "corrective_actions": ["action 1", "action 2"],
  "rework_recommendations": "detailed rework steps",
  "preventive_measures": ["measure 1", "measure 2"],
  "alternative_approach": "alternative manufacturing suggestion if rework fails",
  "estimated_rework_time": "estimated time",
  "quality_risk_level": "LOW/MEDIUM/HIGH"
}}

Return ONLY valid JSON."""
                        response = self.qc_model.generate_content(prompt)
                        llm_suggestions = response.text
                        # Try to parse to validate it's JSON
                        try:
                            json.loads(llm_suggestions)
                        except Exception:
                            # If not valid JSON, wrap it
                            llm_suggestions = json.dumps({"raw_suggestions": llm_suggestions})
                    except Exception as e:
                        logger.error(f"LLM call failed for QC recovery: {e}")
                        llm_suggestions = json.dumps({"error": "LLM unavailable", "message": str(e)})

                # -----------------------------------------
                # Log QC Failure to CSV
                # -----------------------------------------
                qc_log_df = pd.read_csv(self.qc_log_path)
                qc_log_df = pd.concat([qc_log_df, pd.DataFrame([{
                    "production_id": production_id,
                    "product_id": prod_row.iloc[0]["product_id"],
                    "quantity_failed": quantity_completed,
                    "stage_returned_to": "ASSEMBLY",
                    "timestamp": now,
                    "llm_suggestions": llm_suggestions
                }])], ignore_index=True)
                qc_log_df.to_csv(self.qc_log_path, index=False)

                return {
                    "status": "SUCCESS",
                    "production_id": production_id,
                    "previous_stage": "QUALITY_CHECK",
                    "new_stage": "ASSEMBLY",
                    "quantity_processed": quantity_completed,
                    "production_status": "REWORK",
                    "message": "Moved to rework",
                    "llm_suggestions": llm_suggestions
                }

        # NORMAL FLOW
        current_index = STAGE_SEQUENCE.index(current_stage)

        if current_index + 1 >= len(STAGE_SEQUENCE):
            return {"status": "ERROR", "message": "Already at final stage"}

        next_stage = STAGE_SEQUENCE[current_index + 1]


        wip_df.loc[
            (wip_df["production_id"] == production_id) &
            (wip_df["stage_name"] == completed_stage),
            ["status","last_updated"]
        ] = ["COMPLETED", now]

        wip_df = pd.concat([wip_df, pd.DataFrame([{
            "production_id": production_id,
            "stage_name": next_stage,
            "quantity": quantity_completed,
            "status": "IN_PROGRESS",
            "last_updated": now
        }])])

        prod_df.loc[prod_df["production_id"] == production_id,
                    ["current_stage","status","last_updated"]] = [
                        next_stage,"IN_PROGRESS",now
                    ]

        prod_df.to_csv(self.production_orders_path, index=False)
        wip_df.to_csv(self.wip_path, index=False)

        result = {
            "status": "SUCCESS",
            "production_id": production_id,
            "previous_stage": completed_stage,
            "new_stage": next_stage,
            "quantity_processed": quantity_completed,
            "production_status": "IN_PROGRESS",
            "message": "Stage updated"
        }

        if orchestration_result:
            result["orchestration_result"] = orchestration_result

        return result
