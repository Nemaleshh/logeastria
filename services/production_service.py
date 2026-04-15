from execution.production_execution_agent import ProductionExecutionAgent
from services.reorder_service import ReorderService
from execution.event_router import ERPEventRouter
from agents.supplier_agent import SupplierRankingAgent
from agents.orchestrator_agent import AutonomousOrchestratorAgent
from services.procurement_service import ProcurementService
import pandas as pd
from execution.orchestration_logger import OrchestrationLogger

DB_PATH = "data_base"
API_KEY = "AIzaSyCHhVbcfEzPSdNlCdkEmfcX5E-1PctDXOY"
class ProductionService:

    def __init__(self):

        self.procurement_service = ProcurementService()

        # -----------------------------
        # Initialize Supplier Agent
        # -----------------------------
        supplier_agent = SupplierRankingAgent(
            supplier_master_path="data_base/supplier_master.csv",
            supplier_product_path="data_base/supplier_product.csv",
            supplier_performance_path="data_base/supplier_performance.csv"
        )
        supplier_agent.load_data()

        # -----------------------------
        # Initialize Orchestrator Agent
        # -----------------------------
        orchestrator_agent = AutonomousOrchestratorAgent(API_KEY)

        # -----------------------------
        # Initialize Reorder Service
        # -----------------------------
        reorder_service = ReorderService()

        # -----------------------------
        # Initialize Event Router
        # -----------------------------
        event_router = ERPEventRouter(
            reorder_service=reorder_service,
            supplier_agent=supplier_agent,
            orchestrator_agent=orchestrator_agent
        )


        # -----------------------------
        # Demand + Policy Config
        # -----------------------------
        planning_df = pd.read_csv("data_base/material_planning.csv")

        demand_config = {}
        policy_config = {}

        for _, row in planning_df.iterrows():
            demand_config[row["material_id"]] = {
                "average_daily_demand": row["average_daily_demand"],
                "lead_time_days": row["lead_time_days"],
                "safety_stock": row["safety_stock"]
            }

            policy_config[row["material_id"]] = {
                "policy_type": row["policy_type"],
                "economic_order_quantity": row["economic_order_quantity"]
            }


        self.agent = ProductionExecutionAgent(
            db_path="data_base",
            event_router=event_router,
            demand_config=demand_config,
            policy_config=policy_config,
            api_key=API_KEY
        )


    def create_production(self, payload):
        return self.agent.run({
            "action": "CREATE_PRODUCTION",
            "production_data": payload
        })

    def update_stage(self, payload, completed_stage):
        result = self.agent.run({
            "action": "UPDATE_STAGE",
            "stage_update": {
                "production_id": payload["production_id"],
                "completed_stage": completed_stage,
                "quantity_completed": payload["quantity_completed"]
            }
        })

        # Save procurement plan to purchase_orders.csv if orchestration produced one
        orchestration_result = result.get("orchestration_result")
        if orchestration_result and orchestration_result.get("procurement_plan"):
            po_ids = self.procurement_service.save_procurement_plan(
                orchestration_log_id=orchestration_result.get("orchestration_log_id", ""),
                production_id=payload["production_id"],
                decision=orchestration_result
            )
            result["purchase_order_ids"] = po_ids

        return result

    def quality_check(self, payload):
        return self.agent.run({
            "action": "UPDATE_STAGE",
            "stage_update": {
                "production_id": payload["production_id"],
                "completed_stage": "QUALITY_CHECK",
                "quantity_completed": payload["quantity_completed"],
                "qc_passed": payload["qc_passed"]
            }
        })
