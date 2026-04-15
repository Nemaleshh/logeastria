# agents/supplier_agent.py

import logging
from dataclasses import dataclass
from typing import List, Dict, Optional
import pandas as pd
import numpy as np

from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import MinMaxScaler, LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import r2_score

# --------------------------------------------------
# Logging
# --------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# --------------------------------------------------
# Dataclass
# --------------------------------------------------

@dataclass
class SupplierPrediction:
    supplier_id: str
    predicted_performance_score: float
    predicted_risk_score: float
    confidence_score: float
    estimated_total_cost: float
    lead_time_days: float


# --------------------------------------------------
# Supplier Ranking Agent
# --------------------------------------------------

class SupplierRankingAgent:

    def __init__(
        self,
        supplier_master_path: str,
        supplier_product_path: str,
        supplier_performance_path: str,
        weights: Optional[Dict[str, float]] = None,
        confidence_threshold: float = 0.6
    ):

        self.master_path = supplier_master_path
        self.product_path = supplier_product_path
        self.performance_path = supplier_performance_path

        self.performance_model = RandomForestRegressor(
            n_estimators=120,
            random_state=42
        )

        self.risk_model = RandomForestRegressor(
            n_estimators=120,
            random_state=42
        )

        self.scaler = MinMaxScaler()
        self.risk_encoder = LabelEncoder()

        self.confidence_threshold = confidence_threshold

        # Configurable weights (NO hardcoding in logic)
        self.weights = weights or {
            "performance": 0.35,
            "risk": 0.25,
            "cost": 0.15,
            "lead_time_penalty": 0.10,
            "capacity_penalty": 0.10,
            "defect_penalty": 0.05
        }

        self.data = None

    # --------------------------------------------------
    # 1. Load Data
    # --------------------------------------------------

    def load_data(self) -> None:

        master = pd.read_csv(self.master_path)
        product = pd.read_csv(self.product_path)
        performance = pd.read_csv(self.performance_path)

        df = master.merge(product, on="supplier_id", how="left")
        df = df.merge(
            performance,
            on=["supplier_id", "product_id"],
            how="left"
        )

        self.data = df
        logger.info("Data loaded successfully.")

    # --------------------------------------------------
    # 2. Preprocess Data (NO elimination)
    # --------------------------------------------------

    def preprocess_data(self, product_id: str) -> pd.DataFrame:

        df = self.data[self.data["product_id"] == product_id].copy()

        if df.empty:
            # fallback: consider all suppliers for resilience
            logger.warning("Product not found. Using all suppliers as fallback.")
            df = self.data.copy()

        df["risk_level_encoded"] = self.risk_encoder.fit_transform(
            df["risk_level"].astype(str)
        )

        # Handle missing performance data softly
        df["on_time_delivery_rate"] = df["on_time_delivery_rate"].fillna(0.5)
        df["average_delay_days"] = df["average_delay_days"].fillna(
            df["average_delay_days"].mean()
        )
        df["defect_rate"] = df["defect_rate"].fillna(0.1)

        return df

    # --------------------------------------------------
    # 3. Feature Engineering
    # --------------------------------------------------

    def feature_engineering(
        self,
        df: pd.DataFrame,
        required_quantity: float
    ) -> pd.DataFrame:

        df["total_cost_estimate"] = (
            required_quantity * df["cost_per_unit"]
            + df["transport_cost"]
        )

        df["normalized_cost"] = self.scaler.fit_transform(
            df[["total_cost_estimate"]]
        )

        df["normalized_lead_time"] = self.scaler.fit_transform(
            df[["lead_time_days"]]
        )

        # Soft constraint penalties

        df["capacity_penalty"] = np.maximum(
            0,
            (required_quantity - df["max_capacity"]) /
            (df["max_capacity"] + 1)
        )

        df["moq_penalty"] = np.maximum(
            0,
            (df["minimum_order_quantity"] - required_quantity) /
            (df["minimum_order_quantity"] + 1)
        )

        avg_lead_time = df["lead_time_days"].mean()

        df["lead_time_penalty"] = np.maximum(
            0,
            (df["lead_time_days"] - avg_lead_time) /
            (avg_lead_time + 1)
        )

        df["defect_penalty"] = df["defect_rate"]

        return df

    # --------------------------------------------------
    # 4. Train ML Models
    # --------------------------------------------------

    def train_model(self, df: pd.DataFrame) -> None:

        features = df[[
            "normalized_cost",
            "normalized_lead_time",
            "reliability_score",
            "rating",
            "quality_score",
            "on_time_delivery_rate",
            "risk_level_encoded",
            "defect_rate"
        ]]

        performance_target = (
            df["on_time_delivery_rate"] * 0.6
            + (1 - df["defect_rate"]) * 0.4
        )

        risk_target = (
            df["risk_level_encoded"] * 0.6
            + df["average_delay_days"] * 0.4
        )

        X_train, X_test, y_train_perf, y_test_perf = train_test_split(
            features, performance_target, test_size=0.2, random_state=42
        )

        _, _, y_train_risk, y_test_risk = train_test_split(
            features, risk_target, test_size=0.2, random_state=42
        )

        self.performance_model.fit(X_train, y_train_perf)
        self.risk_model.fit(X_train, y_train_risk)

        # Store R2 scores
        self.performance_r2 = r2_score(
            y_test_perf,
            self.performance_model.predict(X_test)
        )

        self.risk_r2 = r2_score(
            y_test_risk,
            self.risk_model.predict(X_test)
        )

        logger.info(f"Performance Model R2: {self.performance_r2:.4f}")
        logger.info(f"Risk Model R2: {self.risk_r2:.4f}")

    # --------------------------------------------------
    # 5. Predict Scores
    # --------------------------------------------------

    def predict_scores(self, df: pd.DataFrame):

        features = df[[
            "normalized_cost",
            "normalized_lead_time",
            "reliability_score",
            "rating",
            "quality_score",
            "on_time_delivery_rate",
            "risk_level_encoded",
            "defect_rate"
        ]]

        df["predicted_performance_score"] = \
            self.performance_model.predict(features)

        df["predicted_risk_score"] = \
            self.risk_model.predict(features)

        return df

    # --------------------------------------------------
    # 6. Compute Confidence Score (Soft Penalty Logic)
    # --------------------------------------------------

    def compute_confidence_score(self, df: pd.DataFrame) -> pd.DataFrame:

        w = self.weights

        df["confidence_score"] = (
            (w["performance"] * df["predicted_performance_score"])
            - (w["risk"] * df["predicted_risk_score"])
            - (w["cost"] * df["normalized_cost"])
            - (w["lead_time_penalty"] * df["lead_time_penalty"])
            - (w["capacity_penalty"] * df["capacity_penalty"])
            - (w["defect_penalty"] * df["defect_penalty"])
        )

        df["confidence_score"] = df["confidence_score"].clip(0, 1)

        return df

    # --------------------------------------------------
    # 7. Rank Suppliers
    # --------------------------------------------------

    def rank_suppliers(self, df: pd.DataFrame) -> pd.DataFrame:

        df_sorted = df.sort_values(
            by="confidence_score",
            ascending=False
        ).reset_index(drop=True)

        high_conf = df_sorted[
            df_sorted["confidence_score"] >= self.confidence_threshold
        ]

        if len(high_conf) >= 2:
            return high_conf.head(2), ""

        warning = (
            "High-confidence suppliers not available. "
            "Returning best possible options."
        )

        return df_sorted.head(2), warning
    
    def evaluate_model(self, X_test, y_test):
        from sklearn.metrics import r2_score
        y_pred = self.model.predict(X_test)
        print("R2:", r2_score(y_test, y_pred))
        return y_pred


    # --------------------------------------------------
    # 8. Generate Output
    # --------------------------------------------------

    def generate_output(
    self,
    ranked_df: pd.DataFrame,
    warning: str
) -> Dict:

        overall_risk = ranked_df["predicted_risk_score"].mean()

        overall_risk_level = (
            "LOW" if overall_risk < 0.3
            else "MEDIUM" if overall_risk < 0.6
            else "HIGH"
        )

        output = {
            "top_suppliers": [],
            "overall_risk_level": overall_risk_level,
            "model_performance": {
                "performance_model_r2": round(float(self.performance_r2), 4),
                "risk_model_r2": round(float(self.risk_r2), 4)
            },
            "selection_reasoning_summary":
                "Suppliers ranked using ML-based performance prediction "
                "with soft constraint penalties for resilience optimization.",
            "warning": warning
        }

        for idx, row in ranked_df.iterrows():
            output["top_suppliers"].append({
                "supplier_id": row["supplier_id"],
                "predicted_performance_score": float(row["predicted_performance_score"]),
                "predicted_risk_score": float(row["predicted_risk_score"]),
                "confidence_score": float(row["confidence_score"]),
                "estimated_total_cost": float(row["total_cost_estimate"]),
                "lead_time_days": float(row["lead_time_days"]),
                "ranking_position": idx + 1
            })

        return output
