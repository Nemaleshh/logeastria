"""
logistics_logger.py
───────────────────
Appends logistics orchestration decisions to logistics_log.csv.
"""

import csv
import json
import os
import uuid
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

_HEADERS = [
    "log_id",
    "timestamp",
    "cluster_id",
    "vehicle_id",
    "total_qty",
    "total_distance_km",
    "delivery_mode",
    "order_ids",
    "reasoning",
]


class LogisticsLogger:
    def __init__(self, log_path: str):
        self.log_path = log_path
        if not os.path.exists(log_path):
            with open(log_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(_HEADERS)
            logger.info(f"[LogisticsLogger] Created log file: {log_path}")

    def log(
        self,
        cluster_id: str,
        vehicle_id: str,
        total_qty: int,
        total_distance_km: float,
        delivery_mode: str,
        order_ids: list,
        reasoning: list,
    ) -> str:
        log_id = str(uuid.uuid4())
        row = [
            log_id,
            datetime.now().isoformat(timespec="seconds"),
            cluster_id,
            vehicle_id,
            total_qty,
            total_distance_km,
            delivery_mode,
            json.dumps(order_ids),
            json.dumps(reasoning),
        ]
        with open(self.log_path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)

        logger.info(f"[LogisticsLogger] Written log_id={log_id}")
        return log_id
