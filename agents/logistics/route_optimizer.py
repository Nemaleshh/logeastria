"""
route_optimizer.py
──────────────────
Nearest-neighbor greedy TSP to order delivery stops.
Returns an ordered list of { name, lat, lng } dicts.
"""

import logging
import math

logger = logging.getLogger(__name__)


def _haversine(p1: dict, p2: dict) -> float:
    R = 6371.0
    lat1, lng1 = math.radians(p1["lat"]), math.radians(p1["lng"])
    lat2, lng2 = math.radians(p2["lat"]), math.radians(p2["lng"])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def optimize(warehouse: dict, orders: list) -> list:
    """
    Nearest-neighbor greedy route from warehouse through all order stops.

    Parameters
    ----------
    warehouse : { name, lat, lng }
    orders    : list of { order_id, name, lat, lng, qty, ... }

    Returns
    -------
    Ordered list of stops (excluding warehouse start):
    [ { "name": str, "lat": float, "lng": float }, ... ]
    """
    if not orders:
        logger.warning("[RouteOptimizer] No orders to route.")
        return []

    stops = [
        {"name": o["name"], "lat": o["lat"], "lng": o["lng"]}
        for o in orders
    ]

    current   = warehouse
    remaining = stops.copy()
    route     = []

    while remaining:
        nearest = min(remaining, key=lambda s: _haversine(current, s))
        route.append(nearest)
        remaining.remove(nearest)
        current = nearest

    logger.info(
        f"[RouteOptimizer] Optimized {len(route)} stops: "
        + " → ".join(s["name"] for s in route)
    )
    return route
