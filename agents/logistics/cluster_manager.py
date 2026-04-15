"""
cluster_manager.py
─────────────────
Groups nearby delivery orders into a single cluster.
Determines delivery_mode from total_qty.
"""

import csv
import math
import logging
import os

logger = logging.getLogger(__name__)

# Haversine helper (local, so no circular import)
def _haversine(lat1, lng1, lat2, lng2) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _load_customers(db_path: str) -> dict:
    customers = {}
    with open(os.path.join(db_path, "logistics_customers.csv"), newline="") as f:
        for row in csv.DictReader(f):
            customers[row["customer_id"]] = {
                "customer_id": row["customer_id"],
                "name": row["name"],
                "lat": float(row["lat"]),
                "lng": float(row["lng"]),
                "demand_qty": int(row["demand_qty"]),
            }
    return customers


def _delivery_mode_from_qty(total_qty: int) -> str:
    if total_qty <= 10:
        return "express"
    elif total_qty <= 80:
        return "economic"
    return "standard"


def create_cluster(order_ids: list, db_path: str = "data_base") -> dict:
    """
    Parameters
    ----------
    order_ids : list of order_id strings to include in this plan
    db_path   : directory where CSV files live

    Returns
    -------
    {
        "cluster_id":    str,
        "orders":        [ {order_id, customer_id, name, lat, lng, qty}, ... ],
        "delivery_mode": str,
        "total_qty":     int
    }
    """
    customers = _load_customers(db_path)

    # Load the requested orders
    all_orders = {}
    with open(os.path.join(db_path, "logistics_orders.csv"), newline="") as f:
        for row in csv.DictReader(f):
            all_orders[row["order_id"]] = row

    enriched = []
    for oid in order_ids:
        if oid not in all_orders:
            logger.warning(f"[ClusterManager] Order {oid} not found — skipping.")
            continue
        row = all_orders[oid]
        cid = row["customer_id"]
        cust = customers.get(cid, {})
        enriched.append({
            "order_id":    oid,
            "customer_id": cid,
            "name":        cust.get("name", cid),
            "lat":         cust.get("lat", 0.0),
            "lng":         cust.get("lng", 0.0),
            "qty":         int(row["qty"]),
            "priority":    row["priority"],
        })

    total_qty = sum(o["qty"] for o in enriched)
    mode = _delivery_mode_from_qty(total_qty)

    # Stable cluster_id from sorted order IDs
    cluster_id = "CL_" + str(abs(hash("_".join(sorted(order_ids)))) % 10000).zfill(4)

    cluster = {
        "cluster_id":    cluster_id,
        "orders":        enriched,
        "delivery_mode": mode,
        "total_qty":     total_qty,
    }

    logger.info(
        f"[ClusterManager] cluster={cluster_id} | orders={len(enriched)} "
        f"| total_qty={total_qty} | mode={mode}"
    )
    return cluster
