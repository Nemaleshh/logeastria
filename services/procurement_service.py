import csv
import uuid
import os
from datetime import datetime
import pandas as pd
import logging

logger = logging.getLogger("ERP.Procurement")

PO_CSV_PATH = "data_base/purchase_orders.csv"

PO_COLUMNS = [
    "po_id", "orchestration_log_id", "production_id", "material_id",
    "selected_supplier", "quantity_to_order", "risk_level", "confidence_level",
    "mitigation_strategy", "reasoning", "status", "created_at", "approved_at", "expected_delivery_date"
]


class ProcurementService:

    def __init__(self, csv_path: str = PO_CSV_PATH):
        self.csv_path = csv_path
        if not os.path.exists(csv_path):
            pd.DataFrame(columns=PO_COLUMNS).to_csv(csv_path, index=False)

    # --------------------------------------------------
    # Save procurement plan from orchestrator output
    # --------------------------------------------------

    def save_procurement_plan(self, orchestration_log_id: str, production_id: str, decision: dict):
        """
        Parse the orchestrator's procurement_plan list and write
        one PO row per material into purchase_orders.csv.
        """
        plan = decision.get("procurement_plan", [])
        if not plan:
            logger.warning("No procurement_plan found in orchestrator decision.")
            return []

        now = datetime.now().isoformat()
        created_pos = []

        for item in plan:
            po_id = f"PO-{uuid.uuid4().hex[:8].upper()}"
            row = {
                "po_id": po_id,
                "orchestration_log_id": orchestration_log_id,
                "production_id": production_id,
                "material_id": item.get("material_id", ""),
                "selected_supplier": item.get("selected_supplier", ""),
                "quantity_to_order": item.get("quantity_to_order", ""),
                "risk_level": item.get("risk_level", ""),
                "confidence_level": item.get("confidence_level", ""),
                "mitigation_strategy": item.get("mitigation_strategy", ""),
                "reasoning": item.get("reasoning", ""),
                "status": "PENDING",
                "created_at": now,
                "approved_at": "",
                "expected_delivery_date": ""
            }

            with open(self.csv_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PO_COLUMNS)
                writer.writerow(row)

            created_pos.append(po_id)
            logger.info(f"Purchase Order {po_id} created for {item.get('material_id')}")

        return created_pos

    # --------------------------------------------------
    # List purchase orders
    # --------------------------------------------------

    def list_purchase_orders(self, status_filter: str = None) -> list:
        df = pd.read_csv(self.csv_path)
        df = df.fillna("")  # prevent NaN breaking JSON serialization
        if status_filter:
            df = df[df["status"] == status_filter]
        return df.to_dict(orient="records")

    # --------------------------------------------------
    # Approve a purchase order
    # --------------------------------------------------

    def approve_po(self, po_id: str) -> dict:
        return self._update_status(po_id, "APPROVED")

    # --------------------------------------------------
    # Reject a purchase order
    # --------------------------------------------------

    def reject_po(self, po_id: str) -> dict:
        return self._update_status(po_id, "REJECTED")

    # --------------------------------------------------
    # Internal: update PO status
    # --------------------------------------------------

    def _update_status(self, po_id: str, new_status: str) -> dict:
        df = pd.read_csv(self.csv_path)
        mask = df["po_id"] == po_id

        if mask.sum() == 0:
            return {"status": "ERROR", "message": f"PO {po_id} not found"}

        current = df.loc[mask, "status"].iloc[0]
        if current != "PENDING":
            return {"status": "ERROR", "message": f"PO {po_id} is already {current}"}

        now = datetime.now()
        df.loc[mask, "status"] = new_status
        if new_status == "APPROVED":
            df.loc[mask, "approved_at"] = now.isoformat()
            
            # Calculate Expected Delivery Date
            material_id = df.loc[mask, "material_id"].iloc[0]
            supplier_id = df.loc[mask, "selected_supplier"].iloc[0]
            
            try:
                sup_prod_df = pd.read_csv("data_base/supplier_product.csv")
                sp_row = sup_prod_df[(sup_prod_df["supplier_id"] == supplier_id) & (sup_prod_df["product_id"] == material_id)]
                if not sp_row.empty:
                    lead_time = int(sp_row.iloc[0]["lead_time_days"])
                    from datetime import timedelta
                    expected_date = now + timedelta(days=lead_time)
                    df.loc[mask, "expected_delivery_date"] = expected_date.strftime("%Y-%m-%d")
                    logger.info(f"Calculated expected delivery for {po_id}: {expected_date.strftime('%Y-%m-%d')} (Lead Time: {lead_time} days)")
            except Exception as e:
                logger.error(f"Failed to calculate expected delivery date for {po_id}: {e}")

        df.to_csv(self.csv_path, index=False)

        logger.info(f"PO {po_id} status changed to {new_status}")
        return {
            "status": "SUCCESS",
            "po_id": po_id,
            "new_status": new_status,
            "message": f"Purchase order {new_status.lower()}"
        }

    # --------------------------------------------------
    # Receive Good (Update Inventory & Supplier Score)
    # --------------------------------------------------

    def receive_po(self, payload: dict) -> dict:
        po_id = payload.get("po_id")
        received_quantity = float(payload.get("received_quantity", 0))
        delay_days = float(payload.get("delay_days", 0))
        low_quality = payload.get("low_quality", False)
        
        response_data = {
            "status": "SUCCESS",
            "po_id": po_id,
            "message": f"Received {received_quantity} units. Inventory and supplier scores updated.",
            "inventory_update": {},
            "supplier_performance_update": {},
            "supplier_master_update": {},
            "shipment_verdict": ""
        }
        
        # 1. Update PO Status
        po_df = pd.read_csv(self.csv_path)
        mask = po_df["po_id"] == po_id
        
        if mask.sum() == 0:
            response_data["status"] = "ERROR"
            response_data["message"] = f"PO {po_id} not found"
            return response_data
            
        po_row = po_df.loc[mask].iloc[0]
        if po_row["status"] != "APPROVED":
            response_data["status"] = "ERROR"
            response_data["message"] = f"Cannot receive PO {po_id} - status is {po_row['status']}"
            return response_data
            
        # Complete the PO
        po_df.loc[mask, "status"] = "COMPLETED"
        po_df.to_csv(self.csv_path, index=False)
        
        material_id = po_row["material_id"]
        supplier_id = po_row["selected_supplier"]
        now = datetime.now().isoformat()
        
        # 2. Update Inventory
        inv_path = "data_base/inventory.csv"
        inv_df = pd.read_csv(inv_path)
        
        old_stock = 0
        if material_id in inv_df["product_id"].values:
            old_stock = inv_df.loc[inv_df["product_id"] == material_id, "current_stock"].iloc[0]
            inv_df.loc[inv_df["product_id"] == material_id, "current_stock"] += received_quantity
            inv_df.loc[inv_df["product_id"] == material_id, "last_updated"] = now
        else:
            # Create new row if not exists
            new_inv = pd.DataFrame([{
                "product_id": material_id,
                "current_stock": received_quantity,
                "reserved_stock": 0,
                "warehouse_location": "WH1",
                "last_updated": now,
                "inventory_type": "RAW"
            }])
            inv_df = pd.concat([inv_df, new_inv], ignore_index=True)
            
        new_stock = inv_df.loc[inv_df["product_id"] == material_id, "current_stock"].iloc[0]
        inv_df.to_csv(inv_path, index=False)

        response_data["inventory_update"] = {
            "material_id": material_id,
            "old_stock": old_stock,
            "new_stock": new_stock,
            "received_quantity": received_quantity
        }
        
        # 3. Update Supplier Performance
        perf_path = "data_base/supplier_performance.csv"
        perf_df = pd.read_csv(perf_path)
        
        mask_perf = (perf_df["supplier_id"] == supplier_id) & (perf_df["product_id"] == material_id)
        
        old_avg_delay = None
        old_ontime_rate = None
        old_defect_rate = None

        if mask_perf.sum() > 0:
            row_idx = perf_df[mask_perf].index[0]
            
            old_avg_delay = perf_df.loc[row_idx, "average_delay_days"]
            old_ontime_rate = perf_df.loc[row_idx, "on_time_delivery_rate"]
            old_defect_rate = perf_df.loc[row_idx, "defect_rate"]

            # Simple exponential moving average update (alpha = 0.2)
            alpha = 0.2
            
            # Update average delay
            curr_delay = perf_df.loc[row_idx, "average_delay_days"]
            perf_df.loc[row_idx, "average_delay_days"] = round((curr_delay * (1 - alpha)) + (delay_days * alpha), 2)
            
            # Update on-time rate
            curr_ontime = perf_df.loc[row_idx, "on_time_delivery_rate"]
            is_ontime = 1.0 if delay_days <= 0 else 0.0
            perf_df.loc[row_idx, "on_time_delivery_rate"] = round((curr_ontime * (1 - alpha)) + (is_ontime * alpha), 3)
            
            # Update defect rate
            curr_defect = perf_df.loc[row_idx, "defect_rate"]
            is_defect = 1.0 if low_quality else 0.0
            perf_df.loc[row_idx, "defect_rate"] = round((curr_defect * (1 - alpha)) + (is_defect * alpha), 3)
            
            perf_df.loc[row_idx, "last_updated"] = datetime.today().strftime('%Y-%m-%d')
            
            perf_df.to_csv(perf_path, index=False)
            logger.info(f"Updated supplier performance for {supplier_id} on {material_id}")

            response_data["supplier_performance_update"] = {
                "supplier_id": supplier_id,
                "material_id": material_id,
                "average_delay_days": {"before": old_avg_delay, "after": perf_df.loc[row_idx, "average_delay_days"]},
                "on_time_delivery_rate": {"before": old_ontime_rate, "after": perf_df.loc[row_idx, "on_time_delivery_rate"]},
                "defect_rate": {"before": old_defect_rate, "after": perf_df.loc[row_idx, "defect_rate"]}
            }
        else:
            logger.warning(f"Supplier performance record not found for {supplier_id} and {material_id}. No performance update.")
            response_data["supplier_performance_update"] = {"message": "No existing performance record to update."}


        # 4. Update Supplier Master (Reliability Score)
        master_path = "data_base/supplier_master.csv"
        old_reliability_score = None
        try:
            master_df = pd.read_csv(master_path)
            master_df.columns = master_df.columns.str.strip()
            
            # Ensure supplier_id is stripped of whitespace for accurate matching
            master_df['supplier_id'] = master_df['supplier_id'].astype(str).str.strip()
            supplier_id_clean = str(supplier_id).strip()
            
            mask_master = master_df["supplier_id"] == supplier_id_clean
            if mask_master.sum() > 0:
                idx_master = master_df[mask_master].index[0]
                old_reliability_score = float(master_df.loc[idx_master, "reliability_score"])
                curr_reliability = old_reliability_score
                
                # Calculate penalty/reward
                score_adjustment = 0.0
                
                # Quality penalty is severe
                if low_quality:
                    score_adjustment -= 0.05
                else:
                    score_adjustment += 0.01  # Slight reward for good quality
                    
                # Delay penalty (0.01 penalty per day late, max 0.05)
                if delay_days > 0:
                    delay_penalty = min(0.05, delay_days * 0.01)
                    score_adjustment -= delay_penalty
                elif delay_days < 0:
                    score_adjustment += 0.01  # Slight reward for early delivery
                    
                new_reliability = round(curr_reliability + score_adjustment, 2)
                
                # Bound between 0.01 and 1.00
                new_reliability = max(0.01, min(1.00, new_reliability))
                
                master_df.loc[idx_master, "reliability_score"] = new_reliability
                master_df.to_csv(master_path, index=False)
                logger.info(f"Updated Master Supplier Reliability for {supplier_id}: {curr_reliability} -> {new_reliability}")

                response_data["supplier_master_update"] = {
                    "supplier_id": supplier_id,
                    "reliability_score": {"before": old_reliability_score, "after": new_reliability}
                }
            else:
                logger.warning(f"Supplier ID {supplier_id_clean} not found in master_df. No reliability score update.")
                response_data["supplier_master_update"] = {"message": f"Supplier ID {supplier_id_clean} not found in master."}
        except Exception as e:
            logger.error(f"Failed to update Supplier Master: {e}")
            response_data["supplier_master_update"] = {"message": f"Failed to update Supplier Master: {e}"}

        # 5. Determine Shipment Verdict
        verdict_parts = []
        if delay_days > 0:
            verdict_parts.append("Delayed")
        elif delay_days < 0:
            verdict_parts.append("Early")
        else:
            verdict_parts.append("On-Time")

        if low_quality:
            verdict_parts.append("Poor Quality")
        else:
            verdict_parts.append("Good Quality")
        
        response_data["shipment_verdict"] = " & ".join(verdict_parts)
            
        return response_data
