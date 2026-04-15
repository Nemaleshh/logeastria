"""
reorder_service.py

Enterprise-grade Reorder Service Module
----------------------------------------

Responsible for:
- Evaluating reorder conditions
- Calculating reorder points
- Determining recommended order quantities
- Triggering supplier selection and orchestration when required

STRICT DESIGN:
- Deterministic math only
- No hardcoded paths
- No infinite loops
- No schedulers
- No background workers
- No LLM prompt logic
- Event-driven only
- Inventory dataframe must be passed as input
"""

from typing import Dict, Any
import pandas as pd


class ReorderServiceException(Exception):
    """Base exception for ReorderService errors."""
    pass


class InvalidProductException(ReorderServiceException):
    """Raised when product_id is not found in inventory."""
    pass


class InvalidPolicyException(ReorderServiceException):
    """Raised when unsupported reorder policy is provided."""
    pass


class ReorderService:
    """
    Enterprise Reorder Service

    Handles reorder logic independently from inventory feasibility logic.
    """

    def __init__(self):
        pass


    # ---------------------------------------------------------
    # PUBLIC ENTRY POINT
    # ---------------------------------------------------------

    def handle_inventory_update(
        self,
        inventory_df: pd.DataFrame,
        product_id: str,
        demand_params: Dict[str, Any],
        policy_config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Event-driven entry method triggered after inventory update.

        :return: Structured decision payload
        """

        product_row = self._get_product_row(inventory_df, product_id)

        available_stock = self.calculate_available_stock(product_row)

        reorder_point = self.calculate_reorder_point(
            average_daily_demand=demand_params["average_daily_demand"],
            lead_time_days=demand_params["lead_time_days"],
            safety_stock=demand_params["safety_stock"]
        )

        recommended_quantity = self.calculate_order_quantity(
            policy_config=policy_config,
            average_daily_demand=demand_params["average_daily_demand"],
            available_stock=available_stock,
            reorder_point=reorder_point
        )

        reorder_trigger = self.evaluate_reorder(
            available_stock,
            reorder_point
        )

        return self.generate_event_payload(
            product_id=product_id,
            warehouse_location=product_row.get("warehouse_location", "WH1"),
            available_stock=available_stock,
            reorder_point=reorder_point,
            reorder_trigger=reorder_trigger,
            policy_used=policy_config["policy_type"] if reorder_trigger else None,
            recommended_order_quantity=recommended_quantity if reorder_trigger else None
        )


    # ---------------------------------------------------------
    # CORE CALCULATIONS
    # ---------------------------------------------------------

    def calculate_available_stock(self, product_row: pd.Series) -> float:
        """Calculate available stock."""
        return float(product_row["current_stock"] - product_row["reserved_stock"])

    def calculate_reorder_point(
        self,
        average_daily_demand: float,
        lead_time_days: int,
        safety_stock: float
    ) -> float:
        """Calculate reorder point."""
        return (average_daily_demand * lead_time_days) + safety_stock

    def calculate_order_quantity(
        self,
        policy_config: Dict[str, Any],
        average_daily_demand: float,
        available_stock: float,
        reorder_point: float
    ) -> float:
        """Determine order quantity based on selected policy."""

        policy = policy_config["policy_type"]

        if policy == "EOQ":
            return float(policy_config["economic_order_quantity"])

        if policy == "TARGET_LEVEL":
            target_level = policy_config["target_level"]
            return max(0.0, target_level - available_stock)

        if policy == "FIXED_LOT":
            return float(policy_config["fixed_lot_size"])

        raise InvalidPolicyException(f"Unsupported policy type: {policy}")

    def evaluate_reorder(
        self,
        available_stock: float,
        reorder_point: float
    ) -> bool:
        """Evaluate whether reorder should be triggered."""
        return available_stock <= reorder_point

    # ---------------------------------------------------------
    # PAYLOAD GENERATION
    # ---------------------------------------------------------

    def generate_event_payload(
        self,
        product_id: str,
        warehouse_location: str,
        available_stock: float,
        reorder_point: float,
        reorder_trigger: bool,
        policy_used: str = None,
        recommended_order_quantity: float = None,
        supplier_decision: Dict[str, Any] = None,
        llm_reasoning: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """Generate structured event payload."""

        base_payload = {
            "material_id": product_id,
            "warehouse_location": warehouse_location,
            "available_stock": available_stock,
            "reorder_point": reorder_point,
            "reorder_trigger": reorder_trigger
        }

        if not reorder_trigger:
            return base_payload

        base_payload.update({
            "policy_used": policy_used,
            "recommended_order_quantity": recommended_order_quantity,
            "supplier_decision": supplier_decision,
            "llm_reasoning": llm_reasoning
        })

        return base_payload

    # ---------------------------------------------------------
    # INTERNAL UTILITIES
    # ---------------------------------------------------------

    def _get_product_row(
        self,
        inventory_df: pd.DataFrame,
        product_id: str
    ) -> pd.Series:
        """Fetch product row from inventory dataframe."""

        product_rows = inventory_df[inventory_df["product_id"] == product_id]

        if product_rows.empty:
            raise InvalidProductException(
                f"Product ID {product_id} not found in inventory."
            )

        return product_rows.iloc[0]
