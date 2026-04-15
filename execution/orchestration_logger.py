import csv
import uuid
from datetime import datetime
import os



class OrchestrationLogger:
    def __init__(self, log_path: str):
        self.log_path = log_path

        if not os.path.exists(log_path):
            with open(log_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "request_id",
                    "product_id",
                    "decision_summary",
                    "overall_risk",
                    "timestamp"
                ])

    def log(self, product_id, decision_summary, overall_risk):
        request_id = str(uuid.uuid4())

        with open(self.log_path, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                request_id,
                product_id,
                decision_summary,
                overall_risk,
                datetime.now()
            ])

        return request_id
