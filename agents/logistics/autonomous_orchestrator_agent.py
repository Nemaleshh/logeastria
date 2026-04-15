"""
autonomous_orchestrator_agent.py
─────────────────────────────────
Main brain that coordinates all logistics sub-modules and returns
the final structured delivery plan:

{
  "cluster_id":           str,
  "vehicle_id":           str,
  "stops":                int,
  "route_order":          [{ "name", "lat", "lng", "weather" }, ...],
  "total_distance_km":    float,
  "delivery_mode":        str,
  "reasoning":            list[str],
  "shipment_id":          str,
  "delivery_pin":         str  (4-digit, shown to driver),
  "orchestration_log_id": str
}
"""

import logging
import os
import csv
import google.generativeai as genai

from agents.logistics import cluster_manager
from agents.logistics import distance_engine
from agents.logistics import vehicle_allocator
from agents.logistics import ml_fetch_service
from agents.logistics import logistics_reasoning_llm
from agents.logistics import route_optimizer
from agents.logistics import delivery_verifier
from agents.logistics import weather_service
from execution.logistics_logger import LogisticsLogger

logger = logging.getLogger(__name__)


class AutonomousOrchestratorAgent:
    """
    Coordinates the full logistics planning pipeline.
    """

    def __init__(self, api_key: str = "", model_name: str = "gemini-2.5-flash", db_path: str = "data_base"):
        _key = api_key or os.environ.get("GEMINI_API_KEY", "") or "AIzaSyCRUmzBqn9WUn8YxlOc5hmN7_JCotCHq_w"
        genai.configure(api_key=_key)
        self.model   = genai.GenerativeModel(model_name)
        self.db_path = db_path
        self.log_path = os.path.join(db_path, "logistics_log.csv")
        self.logistics_logger = LogisticsLogger(self.log_path)
        logger.info(f"[AutonomousOrchestratorAgent] Initialized with model={model_name}")

    def _load_warehouse(self) -> dict:
        with open(os.path.join(self.db_path, "logistics_warehouse.csv"), newline="") as f:
            row = next(csv.DictReader(f))
        return {
            "name": row["name"],
            "lat":  float(row["lat"]),
            "lng":  float(row["lng"]),
        }

    def plan_logistics(self, order_ids: list) -> dict:
        """
        Full orchestration pipeline. Logs every stage.

        Parameters
        ----------
        order_ids : list[str]  — e.g. ["O001", "O002", "O003"]

        Returns
        -------
        Final structured delivery plan dict.
        """
        logger.info(f"[Orchestrator] ▶ Starting logistics plan for orders={order_ids}")

        # ── Step 1: Cluster orders ────────────────────────────────────────────
        cluster = cluster_manager.create_cluster(order_ids, self.db_path)
        logger.info(f"[Orchestrator] ✔ Step 1 — Cluster: {cluster['cluster_id']} | mode={cluster['delivery_mode']} | qty={cluster['total_qty']}")

        # ── Step 2: Vehicle candidates ────────────────────────────────────────
        candidates = vehicle_allocator.get_candidates(cluster, self.db_path)
        if not candidates:
            raise RuntimeError(
                f"No vehicles available for cluster {cluster['cluster_id']} "
                f"(qty={cluster['total_qty']}, mode={cluster['delivery_mode']})"
            )
        logger.info(f"[Orchestrator] ✔ Step 2 — Candidates: {[v['vehicle_id'] for v in candidates]}")

        # ── Step 3: ML scoring ────────────────────────────────────────────────
        scored_candidates = ml_fetch_service.attach_scores(candidates)
        logger.info(f"[Orchestrator] ✔ Step 3 — ML scores attached. Top: {scored_candidates[0]['vehicle_id']} (score={scored_candidates[0]['priority_score_ml']})")

        # ── Step 4: LLM vehicle selection ─────────────────────────────────────
        decision = logistics_reasoning_llm.select_vehicle(cluster, scored_candidates, self.model)
        selected_vehicle_id = decision["selected_vehicle_id"]
        reasoning           = decision.get("reasoning", [])
        logger.info(f"[Orchestrator] ✔ Step 4 — LLM selected: {selected_vehicle_id}")

        # ── Step 5: Route optimization ────────────────────────────────────────
        warehouse = self._load_warehouse()
        optimized_route = route_optimizer.optimize(warehouse, cluster["orders"])
        logger.info(f"[Orchestrator] ✔ Step 5 — Route optimized: {len(optimized_route)} stops")

        # ── Step 6: Total distance ────────────────────────────────────────────
        total_distance = distance_engine.calculate_total_distance(warehouse, optimized_route)
        logger.info(f"[Orchestrator] ✔ Step 6 — Total distance: {total_distance} km")

        # ── Step 7: Enrich route with weather ─────────────────────────────────
        route_with_weather = weather_service.get_route_weather(optimized_route)
        logger.info(f"[Orchestrator] ✔ Step 7 — Weather attached to {len(route_with_weather)} stops")

        # ── Step 8: Create shipment + generate delivery PIN ───────────────────
        shipment = delivery_verifier.create_shipment(
            cluster_id=cluster["cluster_id"],
            vehicle_id=selected_vehicle_id,
            order_ids=order_ids,
            db_path=self.db_path,
        )
        logger.info(
            f"[Orchestrator] ✔ Step 8 — Shipment {shipment['shipment_id']} | "
            f"PIN={shipment['delivery_pin']}"
        )

        # ── Step 9: Log to CSV ────────────────────────────────────────────────
        log_id = self.logistics_logger.log(
            cluster_id=cluster["cluster_id"],
            vehicle_id=selected_vehicle_id,
            total_qty=cluster["total_qty"],
            total_distance_km=total_distance,
            delivery_mode=cluster["delivery_mode"],
            order_ids=order_ids,
            reasoning=reasoning,
        )
        logger.info(f"[Orchestrator] ✔ Step 9 — Logged as {log_id}")

        # ── Final JSON ────────────────────────────────────────────────────────
        result = {
            "cluster_id":           cluster["cluster_id"],
            "vehicle_id":           selected_vehicle_id,
            "stops":                len(optimized_route),
            "route_order":          route_with_weather,
            "total_distance_km":    total_distance,
            "delivery_mode":        cluster["delivery_mode"],
            "reasoning":            reasoning,
            "shipment_id":          shipment["shipment_id"],
            "delivery_pin":         shipment["delivery_pin"],
            "orchestration_log_id": log_id,
        }

        logger.info(
            f"[Orchestrator] ✅ Plan complete → cluster={result['cluster_id']} | "
            f"vehicle={result['vehicle_id']} | dist={result['total_distance_km']} km | "
            f"shipment={result['shipment_id']} | PIN={result['delivery_pin']}"
        )
        return result
