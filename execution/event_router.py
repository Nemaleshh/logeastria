
import logging

logger = logging.getLogger("ERP.EventRouter")

from typing import Dict, Any, List
from datetime import datetime
import pandas as pd


class EventRouterException(Exception):
    """Base exception for EventRouter errors."""
    pass


class InvalidEventStructureException(EventRouterException):
    """Raised when event payload structure is invalid."""
    pass


class ERPEventRouter:
    """
    ERP Event Router

    Coordinates inventory events and triggers reorder evaluation.
    """

    def __init__(self, reorder_service, supplier_agent, orchestrator_agent):
        self.reorder_service = reorder_service
        self.supplier_agent = supplier_agent
        self.orchestrator_agent = orchestrator_agent


    # ---------------------------------------------------------
    # PUBLIC ENTRY POINT
    # ---------------------------------------------------------

    def handle_inventory_event(
        self,
        inventory_df: pd.DataFrame,
        inventory_event: Dict[str, Any],
        demand_config: Dict[str, Dict[str, Any]],
        policy_config: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        inventory_analysis_list = []
        supplier_ranking_results = []

        logger.info("Inventory event received by EventRouter")

        self._validate_event_structure(inventory_event)

        production_id = inventory_event["production_id"]
        print(production_id)
        affected_materials = inventory_event["affected_materials"]
        print(affected_materials)

        logger.info(
            f"Processing INVENTORY_UPDATED for Production {production_id}"
        )
        """
        React to INVENTORY_UPDATED event.

        :param inventory_df: Updated inventory dataframe
        :param inventory_event: Structured inventory update event
        :param demand_config: Per-material demand parameters
        :param policy_config: Per-material policy configuration
        :return: Structured ERP-level response
        """

        self._validate_event_structure(inventory_event)

        production_id = inventory_event["production_id"]
        affected_materials = inventory_event["affected_materials"]

        decisions: List[Dict[str, Any]] = []

        reorder_count = 0
        po_count = 0

        for material in affected_materials:

            material_id = material["material_id"]
            logger.info(
                f"Evaluating reorder for material: {material_id}"
            )
            if material_id not in demand_config:
                raise EventRouterException(
                    f"Demand configuration missing for material: {material_id}"
                )

            if material_id not in policy_config:
                raise EventRouterException(
                    f"Policy configuration missing for material: {material_id}"
                )

            decision = self.reorder_service.handle_inventory_update(
                inventory_df=inventory_df,
                product_id=material_id,
                demand_params=demand_config[material_id],
                policy_config=policy_config[material_id]
            )
            logger.info(f"[DEBUG] Reorder decision for {material_id}: {decision}")


            decisions.append(decision)

            if decision.get("reorder_trigger"):
                    logger.info(f"[DEBUG] Reorder triggered for {material_id}")
                    logger.info(f"[DEBUG] Recommended quantity: {decision.get('recommended_order_quantity')}")

                    reorder_count += 1

                    material_id = decision["material_id"]
                    qty = decision["recommended_order_quantity"]

                    inventory_analysis_list.append({
                        "material_id": material_id,
                        "quantity_to_order": qty
                    })

                    # ---- Supplier Ranking Pipeline ----
                    df = self.supplier_agent.preprocess_data(product_id=material_id)

                    df = self.supplier_agent.feature_engineering(df, required_quantity=qty)
                    self.supplier_agent.train_model(df)
                    df = self.supplier_agent.predict_scores(df)
                    df = self.supplier_agent.compute_confidence_score(df)

                    ranked_df, warning = self.supplier_agent.rank_suppliers(df)
                    supplier_output = self.supplier_agent.generate_output(ranked_df, warning)

                    suppliers = supplier_output.get("top_suppliers") \
                        or supplier_output.get("suppliers") \
                        or supplier_output.get("ranked_suppliers") \
                        or []

                    supplier_ranking_results.append({
                        "material_id": material_id,
                        "suppliers": suppliers
                    })

            
            logger.info(
                f"Reorder Trigger: {decision.get('reorder_trigger')} "
                f"| Purchase Order Created: {bool(decision.get('purchase_order'))}"
            )

        logger.info(
            f"Inventory evaluation completed | "
            f"Reorders: {reorder_count} | POs: {po_count}"
        )

        if inventory_analysis_list:
            structured_input = {
                "production_request": {
                    "order_id": production_id
                },
                "bill_of_materials": affected_materials,
                "inventory_analysis": inventory_analysis_list,
                "supplier_ranking_results": supplier_ranking_results
            }
            logger.info(f"[DEBUG] Structured input to orchestrator: {structured_input}")
            orchestration_result = self.orchestrator_agent.run(structured_input)

        else:

            orchestration_result = None

        return self._generate_response(
            production_id=production_id,
            materials_evaluated=decisions,
            total_checked=len(affected_materials),
            reorder_count=reorder_count,
            po_count=po_count,
            orchestration_result=orchestration_result
        )

    # ---------------------------------------------------------
    # VALIDATION
    # ---------------------------------------------------------

    def _validate_event_structure(self, event: Dict[str, Any]) -> None:
        """
        Validate inventory event contract.
        """

        required_keys = [
            "event_type",
            "source",
            "timestamp",
            "production_id",
            "affected_materials"
        ]

        for key in required_keys:
            if key not in event:
                raise InvalidEventStructureException(
                    f"Missing required event key: {key}"
                )

        if event["event_type"] != "INVENTORY_UPDATED":
            raise InvalidEventStructureException(
                "Invalid event_type. Expected INVENTORY_UPDATED."
            )

        if not isinstance(event["affected_materials"], list):
            raise InvalidEventStructureException(
                "affected_materials must be a list."
            )

        for material in event["affected_materials"]:
            if "material_id" not in material:
                raise InvalidEventStructureException(
                    "Each affected material must contain material_id."
                )

    # ---------------------------------------------------------
    # RESPONSE GENERATION
    # ---------------------------------------------------------

    def _generate_response(
        self,
        production_id: str,
        materials_evaluated: List[Dict[str, Any]],
        total_checked: int,
        reorder_count: int,
        po_count: int,
        orchestration_result: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Generate ERP-level structured response.
        """

        return {
            "event_type": "INVENTORY_EVALUATION_COMPLETED",
            "source": "EventRouter",
            "timestamp": datetime.now().isoformat(),
            "production_id": production_id,
            "materials_evaluated": materials_evaluated,
            "reorder_summary": {
                "total_materials_checked": total_checked,
                "reorders_triggered": reorder_count,
                "purchase_orders_created": po_count
            },
            "orchestration_result": orchestration_result

        }
