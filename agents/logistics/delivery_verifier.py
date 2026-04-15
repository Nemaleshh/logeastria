"""
delivery_verifier.py
─────────────────────
Handles delivery PIN generation and verification.

Flow:
  1. plan_logistics() calls create_shipment() → generates 4-digit PIN, saves to CSV
  2. Transport agent shows PIN to driver → driver asks customer to read it
  3. Frontend calls verify_pin(shipment_id, entered_pin) → marks DELIVERED if correct
"""

import csv
import json
import logging
import os
import random
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

_HEADERS = [
    "shipment_id", "cluster_id", "vehicle_id", "order_ids",
    "delivery_pin", "status", "created_at", "delivered_at", "pin_verified_by"
]


def _shipment_path(db_path: str) -> str:
    return os.path.join(db_path, "logistics_shipments.csv")


def _ensure_headers(db_path: str):
    path = _shipment_path(db_path)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(_HEADERS)


def _load_all(db_path: str) -> list:
    _ensure_headers(db_path)
    with open(_shipment_path(db_path), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _save_all(rows: list, db_path: str):
    with open(_shipment_path(db_path), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_HEADERS)
        w.writeheader()
        w.writerows(rows)


def create_shipment(cluster_id: str, vehicle_id: str, order_ids: list, db_path: str = "data_base") -> dict:
    """
    Create a shipment record with a randomly generated 4-digit delivery PIN.

    Returns
    -------
    {
        "shipment_id": str,
        "delivery_pin": str (4 digits, zero-padded),
        "status": "IN_TRANSIT"
    }
    """
    _ensure_headers(db_path)
    shipment_id  = "SHP-" + str(uuid.uuid4())[:8].upper()
    delivery_pin = str(random.randint(1000, 9999))

    row = {
        "shipment_id":    shipment_id,
        "cluster_id":     cluster_id,
        "vehicle_id":     vehicle_id,
        "order_ids":      json.dumps(order_ids),
        "delivery_pin":   delivery_pin,
        "status":         "IN_TRANSIT",
        "created_at":     datetime.now().isoformat(timespec="seconds"),
        "delivered_at":   "",
        "pin_verified_by": "",
    }

    with open(_shipment_path(db_path), "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=_HEADERS).writerow(row)

    logger.info(
        f"[DeliveryVerifier] Shipment created: {shipment_id} | "
        f"vehicle={vehicle_id} | PIN={delivery_pin} | status=IN_TRANSIT"
    )
    return {"shipment_id": shipment_id, "delivery_pin": delivery_pin, "status": "IN_TRANSIT"}


def verify_pin(shipment_id: str, entered_pin: str, verified_by: str = "driver", db_path: str = "data_base") -> dict:
    """
    Cross-verify the customer-provided PIN and mark the shipment as DELIVERED.

    Returns
    -------
    {
        "success": bool,
        "message": str,
        "shipment_id": str,
        "status": str
    }
    """
    rows = _load_all(db_path)
    match = None
    for row in rows:
        if row["shipment_id"] == shipment_id:
            match = row
            break

    if not match:
        logger.warning(f"[DeliveryVerifier] Shipment {shipment_id} not found.")
        return {"success": False, "message": f"Shipment '{shipment_id}' not found.", "status": "NOT_FOUND"}

    if match["status"] == "DELIVERED":
        return {"success": False, "message": "Shipment already marked as DELIVERED.", "status": "DELIVERED"}

    if match["status"] != "IN_TRANSIT":
        return {"success": False, "message": f"Cannot verify — shipment status is {match['status']}.", "status": match["status"]}

    if str(entered_pin).strip() != str(match["delivery_pin"]).strip():
        logger.warning(f"[DeliveryVerifier] PIN mismatch for {shipment_id}: entered={entered_pin} expected={match['delivery_pin']}")
        return {"success": False, "message": "❌ PIN mismatch. Please check and retry.", "status": "IN_TRANSIT", "shipment_id": shipment_id}

    # PIN matched — mark delivered
    for row in rows:
        if row["shipment_id"] == shipment_id:
            row["status"]         = "DELIVERED"
            row["delivered_at"]   = datetime.now().isoformat(timespec="seconds")
            row["pin_verified_by"] = verified_by
            break

    _save_all(rows, db_path)
    logger.info(f"[DeliveryVerifier] ✅ Shipment {shipment_id} marked DELIVERED by {verified_by}")

    return {
        "success":     True,
        "message":     "✅ PIN verified. Shipment marked as DELIVERED.",
        "shipment_id": shipment_id,
        "status":      "DELIVERED",
    }


def get_active_shipments(db_path: str = "data_base") -> list:
    """Return all IN_TRANSIT and INCIDENT shipments."""
    rows = _load_all(db_path)
    return [r for r in rows if r["status"] in ("IN_TRANSIT", "INCIDENT")]


def get_all_shipments(db_path: str = "data_base") -> list:
    return _load_all(db_path)
