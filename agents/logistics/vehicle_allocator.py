"""
vehicle_allocator.py
────────────────────
Filters vehicle fleet by capacity and delivery mode.
"""

import csv
import logging
import os

logger = logging.getLogger(__name__)


def _load_vehicles(db_path: str) -> list:
    vehicles = []
    with open(os.path.join(db_path, "logistics_vehicles.csv"), newline="") as f:
        for row in csv.DictReader(f):
            vehicles.append({
                "vehicle_id":    row["vehicle_id"],
                "type":          row["type"],
                "capacity_qty":  int(row["capacity_qty"]),
                "delivery_mode": row["delivery_mode"],
                "lat":           float(row["lat"]),
                "lng":           float(row["lng"]),
            })
    return vehicles


def get_candidates(cluster: dict, db_path: str = "data_base") -> list:
    """
    Filter vehicles that:
    1. Have capacity_qty >= cluster total_qty
    2. Match the cluster delivery_mode

    Returns list of candidate vehicle dicts.
    Falls back to capacity-only filter if no mode-matching vehicles found.
    """
    vehicles = _load_vehicles(db_path)
    total_qty   = cluster["total_qty"]
    mode        = cluster["delivery_mode"]

    candidates = [
        v for v in vehicles
        if v["capacity_qty"] >= total_qty and v["delivery_mode"] == mode
    ]

    if not candidates:
        logger.warning(
            f"[VehicleAllocator] No vehicles match mode='{mode}' with "
            f"capacity>={total_qty}. Falling back to capacity-only filter."
        )
        candidates = [v for v in vehicles if v["capacity_qty"] >= total_qty]

    logger.info(
        f"[VehicleAllocator] cluster={cluster['cluster_id']} | "
        f"total_qty={total_qty} | mode={mode} | candidates={[v['vehicle_id'] for v in candidates]}"
    )
    return candidates
