"""
distance_engine.py
──────────────────
Haversine distance calculations.
"""

import math
import logging

logger = logging.getLogger(__name__)


def calculate_distance(p1: dict, p2: dict) -> float:
    """
    Haversine distance between two points.
    Points must have 'lat' and 'lng' keys.
    Returns distance in km (rounded to 4 dp).
    """
    R = 6371.0
    lat1, lng1 = math.radians(p1["lat"]), math.radians(p1["lng"])
    lat2, lng2 = math.radians(p2["lat"]), math.radians(p2["lng"])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 4)


def calculate_total_distance(warehouse: dict, route: list) -> float:
    """
    Calculate total route distance.

    Parameters
    ----------
    warehouse : { "lat": float, "lng": float, ... }
    route     : ordered list of stop dicts, each with { "lat", "lng", "name" }
                (does NOT include warehouse — it is prepended automatically)

    Returns
    -------
    Total distance in km (rounded to 2 dp)
    """
    stops = [warehouse] + list(route)
    total = 0.0
    for i in range(len(stops) - 1):
        seg = calculate_distance(stops[i], stops[i + 1])
        total += seg
        logger.debug(
            f"[DistanceEngine] {stops[i].get('name','?')} → "
            f"{stops[i+1].get('name','?')} = {seg} km"
        )
    # Return to warehouse
    if route:
        back = calculate_distance(stops[-1], warehouse)
        total += back
        logger.debug(f"[DistanceEngine] Return to warehouse = {back} km")

    total = round(total, 2)
    logger.info(f"[DistanceEngine] Total route distance = {total} km")
    return total
