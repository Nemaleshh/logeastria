# agents/inventory_agent.py

import os
import json
import logging
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional
import pandas as pd


# --------------------------------------------------
# Logging Configuration
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)

logger = logging.getLogger("InventoryAgent")


# --------------------------------------------------
# Data Models
# --------------------------------------------------

@dataclass
class Product:
    product_id: str
    product_name: str
    category: str
    unit_type: str
    safety_stock: float
    reorder_point: float
    criticality_level: str


@dataclass
class InventoryRecord:
    product_id: str
    current_stock: float
    reserved_stock: float
    warehouse_location: str
    last_updated: str

    @property
    def available_stock(self) -> float:
        return self.current_stock - self.reserved_stock


@dataclass
class Shortage:
    product_id: str
    required: float
    available: float
    shortage: float
    criticality_level: str


# --------------------------------------------------
# Inventory Agent
# --------------------------------------------------

class InventoryAgent:

    def __init__(self, data_path: str):
        self.data_path = data_path
        self.product_master: pd.DataFrame = pd.DataFrame()
        self.bom: pd.DataFrame = pd.DataFrame()
        self.inventory: pd.DataFrame = pd.DataFrame()

        self.load_data()

    # --------------------------------------------------
    # Load Data
    # --------------------------------------------------

    def load_data(self) -> None:
        try:
            logger.info("Loading CSV data files...")

            self.product_master = pd.read_csv(
                os.path.join(self.data_path, "product_master.csv")
            )

            self.bom = pd.read_csv(
                os.path.join(self.data_path, "bom.csv")
            )

            self.inventory = pd.read_csv(
                os.path.join(self.data_path, "inventory.csv")
            )

            logger.info("Data successfully loaded.")

        except Exception as e:
            logger.error(f"Error loading CSV files: {str(e)}")
            raise

    # --------------------------------------------------
    # Calculate Requirements
    # --------------------------------------------------

    def calculate_requirements(
        self,
        finished_product_id: str,
        quantity_to_produce: float
    ) -> Dict[str, float]:

        logger.info(
            f"Calculating material requirements for "
            f"{finished_product_id} | Quantity: {quantity_to_produce}"
        )

        if finished_product_id not in self.product_master["product_id"].values:
            raise ValueError(f"Finished product '{finished_product_id}' not found.")

        bom_filtered = self.bom[
            self.bom["finished_product_id"] == finished_product_id
        ]

        if bom_filtered.empty:
            raise ValueError(f"No BOM found for '{finished_product_id}'.")

        requirements = {}

        for _, row in bom_filtered.iterrows():
            component_id = row["component_product_id"]
            qty_required = row["quantity_required"] * quantity_to_produce
            requirements[component_id] = qty_required

        logger.info(f"Requirements calculated: {requirements}")
        return requirements

    # --------------------------------------------------
    # Check Inventory
    # --------------------------------------------------

    def check_inventory(
        self,
        requirements: Dict[str, float]
    ) -> Tuple[bool, List[Shortage], List[str]]:

        logger.info("Checking inventory availability...")

        shortages: List[Shortage] = []
        warnings: List[str] = []

        for product_id, required_qty in requirements.items():

            inv_record = self.inventory[
                self.inventory["product_id"] == product_id
            ]

            if inv_record.empty:
                raise ValueError(f"Inventory record missing for '{product_id}'.")

            inv_row = inv_record.iloc[0]

            inventory_obj = InventoryRecord(
                product_id=inv_row["product_id"],
                current_stock=inv_row["current_stock"],
                reserved_stock=inv_row["reserved_stock"],
                warehouse_location=inv_row["warehouse_location"],
                last_updated=inv_row["last_updated"],
            )

            available = inventory_obj.available_stock

            product_row = self.product_master[
                self.product_master["product_id"] == product_id
            ].iloc[0]

            product_obj = Product(
                product_id=product_row["product_id"],
                product_name=product_row["product_name"],
                category=product_row["category"],
                unit_type=product_row["unit_type"],
                safety_stock=product_row["safety_stock"],
                reorder_point=product_row["reorder_point"],
                criticality_level=product_row["criticality_level"],
            )

            # Shortage detection
            if available < required_qty:
                shortage_qty = required_qty - available
                shortages.append(
                    Shortage(
                        product_id=product_id,
                        required=required_qty,
                        available=available,
                        shortage=shortage_qty,
                        criticality_level=product_obj.criticality_level
                    )
                )

            # Safety stock warning
            if available - required_qty < product_obj.safety_stock:
                warnings.append(
                    f"{product_id} will fall below safety stock after production."
                )

            # Reorder point warning
            if available < product_obj.reorder_point:
                warnings.append(
                    f"{product_id} is below reorder point."
                )

        production_feasible = len(shortages) == 0

        logger.info(
            f"Inventory check complete | Feasible: {production_feasible}"
        )

        return production_feasible, shortages, warnings

    # --------------------------------------------------
    # Generate Report
    # --------------------------------------------------

    def generate_report(
        self,
        production_feasible: bool,
        shortages: List[Shortage],
        warnings: List[str]
    ) -> Dict:

        logger.info("Generating structured JSON report...")

        report = {
            "production_feasible": bool(production_feasible),
            "shortages": [
                {
                    "product_id": str(s.product_id),
                    "required": float(s.required),
                    "available": float(s.available),
                    "shortage": float(s.shortage),
                    "criticality_level": str(s.criticality_level),
                }
                for s in shortages
            ],
            "warnings": [str(w) for w in warnings],
        }

        logger.info("Report generated successfully.")
        return report


    # --------------------------------------------------
    # Main Execution API
    # --------------------------------------------------

    def evaluate_production(
        self,
        finished_product_id: str,
        quantity_to_produce: float
    ) -> Dict:

        logger.info("Starting production feasibility evaluation...")

        requirements = self.calculate_requirements(
            finished_product_id,
            quantity_to_produce
        )

        feasible, shortages, warnings = self.check_inventory(requirements)

        return self.generate_report(feasible, shortages, warnings)
