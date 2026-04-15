"""
warehouse_agent.py — Hybrid AI Warehouse Agent

Architecture:
    StateBuilder          →  Loads all CSVs, builds structured state
    RuleEngine            →  Computes deterministic facts (available stock, capacity %, breaches)
    GeminiReasoningEngine →  Passes condensed state to gemini-3-flash-preview for strategic decisions
    ActionDispatcher      →  Parses Gemini output into structured action payloads
    WarehouseAgentLogger  →  Logs every run with unique request_id + full reasoning

Design Rules:
    - Gemini NEVER receives raw CSV rows
    - All numerical math is done in RuleEngine BEFORE Gemini
    - Gemini output is strictly structured JSON
    - Every run gets a unique UUID stored in warehouse_agent_log.csv
"""

import os
import csv
import json
import uuid
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

import pandas as pd
import google.generativeai as genai

# ──────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("WarehouseAgent")

BASE = os.path.join(os.path.dirname(__file__), "..", "data_base")


# ══════════════════════════════════════════════════════
# WAREHOUSE AGENT LOGGER
# ══════════════════════════════════════════════════════

class WarehouseAgentLogger:
    """Persists every agent run to warehouse_agent_log.csv."""

    HEADERS = [
        "request_id", "action_type", "input_summary",
        "gemini_reasoning", "decision_json", "risk_level", "timestamp",
    ]

    def __init__(self, log_path: Optional[str] = None):
        self.log_path = log_path or os.path.join(BASE, "warehouse_agent_log.csv")
        if not os.path.exists(self.log_path):
            with open(self.log_path, "w", newline="") as f:
                csv.writer(f).writerow(self.HEADERS)

    def log(
        self,
        action_type: str,
        input_summary: str,
        gemini_reasoning: str,
        decision_json: str,
        risk_level: str = "",
    ) -> str:
        request_id = str(uuid.uuid4())
        with open(self.log_path, "a", newline="") as f:
            csv.writer(f).writerow([
                request_id,
                action_type,
                input_summary,
                gemini_reasoning,
                decision_json,
                risk_level,
                datetime.now().isoformat(),
            ])
        logger.info("Logged warehouse agent run %s [%s]", request_id, action_type)
        return request_id


# ══════════════════════════════════════════════════════
# STATE BUILDER
# ══════════════════════════════════════════════════════

def _read(fname: str) -> pd.DataFrame:
    try:
        return pd.read_csv(os.path.join(BASE, fname))
    except Exception:
        return pd.DataFrame()


class StateBuilder:
    """Load all CSVs and build structured state dictionaries."""

    def build(self) -> Dict[str, Any]:
        return {
            "inventory":          self._inventory_state(),
            "warehouse_capacity": self._warehouse_capacity(),
            "warehouse_geo":      self._warehouse_geo(),
            "pending_orders":     self._pending_orders(),
            "shipments":          self._active_shipments(),
            "production_orders":  self._production_orders(),
            "purchase_orders":    self._purchase_orders(),
            "wip":                self._wip_state(),
            "finished_goods":     self._finished_goods(),
            "material_planning":  self._material_planning(),
        }

    # ── individual builders ──

    def _inventory_state(self) -> List[Dict]:
        df = _read("inventory.csv")
        if df.empty:
            return []
        df["current_stock"] = pd.to_numeric(df["current_stock"], errors="coerce").fillna(0)
        df["reserved_stock"] = pd.to_numeric(df["reserved_stock"], errors="coerce").fillna(0)
        df["available_stock"] = df["current_stock"] - df["reserved_stock"]
        cols = ["product_id", "current_stock", "reserved_stock",
                "available_stock", "warehouse_location", "inventory_type"]
        return df[[c for c in cols if c in df.columns]].to_dict(orient="records")

    def _warehouse_capacity(self) -> List[Dict]:
        df = _read("warehouse.csv")
        if df.empty:
            return []
        df["max_capacity"] = pd.to_numeric(df["max_capacity"], errors="coerce").fillna(0)
        # Recompute occupied from actual inventory
        inv = _read("inventory.csv")
        fgi = _read("finished_goods_inventory.csv")
        raw_by_wh: Dict[str, float] = {}
        if not inv.empty and "warehouse_location" in inv.columns:
            inv["current_stock"] = pd.to_numeric(inv["current_stock"], errors="coerce").fillna(0)
            raw_by_wh = inv.groupby("warehouse_location")["current_stock"].sum().to_dict()
        fg_total = 0.0
        if not fgi.empty and "current_stock" in fgi.columns:
            fg_total = pd.to_numeric(fgi["current_stock"], errors="coerce").fillna(0).sum()

        results = []
        for _, row in df.iterrows():
            wid = str(row["warehouse_id"])
            mx = float(row["max_capacity"])
            occ = raw_by_wh.get(wid, 0.0) + (fg_total if wid == "WH1" else 0.0)
            pct = round(occ / mx * 100, 1) if mx > 0 else 0.0
            results.append({
                "warehouse_id": wid,
                "max_capacity": int(mx),
                "current_occupied": round(occ, 1),
                "free_space": round(max(0, mx - occ), 1),
                "utilization_percent": pct,
                "status": "CRITICAL" if pct >= 90 else "WARNING" if pct >= 75 else "NORMAL",
            })
        return results

    def _warehouse_geo(self) -> List[Dict]:
        df = _read("logistics_warehouse.csv")
        if df.empty:
            return []
        return df.to_dict(orient="records")

    def _pending_orders(self) -> List[Dict]:
        df = _read("logistics_orders.csv")
        if df.empty:
            return []
        df["qty"] = pd.to_numeric(df["qty"], errors="coerce").fillna(0)
        if "priority" in df.columns:
            df["priority"] = df["priority"].str.upper()
        return df.to_dict(orient="records")

    def _active_shipments(self) -> List[Dict]:
        df = _read("logistics_shipments.csv")
        if df.empty:
            return []
        active = df[df["status"] != "DELIVERED"] if "status" in df.columns else df
        return active.to_dict(orient="records")

    def _production_orders(self) -> List[Dict]:
        df = _read("production_orders.csv")
        if df.empty:
            return []
        active = df[df["status"] != "COMPLETED"] if "status" in df.columns else df
        cols = ["production_id", "product_id", "target_quantity", "current_stage", "status"]
        return active[[c for c in cols if c in active.columns]].to_dict(orient="records")

    def _purchase_orders(self) -> List[Dict]:
        df = _read("purchase_orders.csv")
        if df.empty:
            return []
        pending = df[df["status"].isin(["PENDING", "APPROVED"])] if "status" in df.columns else df
        cols = ["po_id", "material_id", "quantity_to_order", "status",
                "expected_delivery_date", "risk_level", "confidence_level"]
        return pending[[c for c in cols if c in pending.columns]].to_dict(orient="records")

    def _wip_state(self) -> List[Dict]:
        df = _read("wip_tracking.csv")
        if df.empty:
            return []
        active = df[df["status"] == "IN_PROGRESS"] if "status" in df.columns else df
        return active.to_dict(orient="records")

    def _finished_goods(self) -> List[Dict]:
        df = _read("finished_goods_inventory.csv")
        if df.empty:
            return []
        df["current_stock"] = pd.to_numeric(df["current_stock"], errors="coerce").fillna(0)
        return df.to_dict(orient="records")

    def _material_planning(self) -> List[Dict]:
        df = _read("material_planning.csv")
        if df.empty:
            return []
        return df.to_dict(orient="records")


# ══════════════════════════════════════════════════════
# RULE ENGINE
# ══════════════════════════════════════════════════════

class RuleEngine:
    """Deterministic computations — no LLM calls."""

    def compute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich state with rule-based flags and computations."""
        flags: Dict[str, Any] = {
            "safety_stock_breaches": [],
            "capacity_warnings": [],
            "reorder_triggers": [],
            "inbound_forecast": [],
        }

        inv_map = {i["product_id"]: i for i in state.get("inventory", [])}
        mat_plan = {m["material_id"]: m for m in state.get("material_planning", [])}

        # Safety stock + reorder evaluation
        for mid, mp in mat_plan.items():
            inv = inv_map.get(mid)
            if not inv:
                continue
            avail = float(inv.get("available_stock", 0))
            safety = float(mp.get("safety_stock", 0))
            demand = float(mp.get("average_daily_demand", 0))
            lead = float(mp.get("lead_time_days", 0))
            eoq = float(mp.get("economic_order_quantity", 0))

            reorder_point = (demand * lead) + safety

            if avail <= safety:
                flags["safety_stock_breaches"].append({
                    "material_id": mid,
                    "available_stock": avail,
                    "safety_stock": safety,
                    "deficit": round(safety - avail, 1),
                    "severity": "CRITICAL",
                })

            if avail <= reorder_point:
                flags["reorder_triggers"].append({
                    "material_id": mid,
                    "available_stock": avail,
                    "reorder_point": reorder_point,
                    "recommended_qty": eoq,
                    "policy_type": mp.get("policy_type", "EOQ"),
                })

        # Capacity warnings
        for wh in state.get("warehouse_capacity", []):
            pct = wh.get("utilization_percent", 0)
            if pct >= 75:
                flags["capacity_warnings"].append({
                    "warehouse_id": wh["warehouse_id"],
                    "utilization_percent": pct,
                    "severity": "CRITICAL" if pct >= 90 else "WARNING",
                    "free_space": wh.get("free_space", 0),
                })

        # Inbound forecast from WIP + purchase orders
        for po in state.get("purchase_orders", []):
            flags["inbound_forecast"].append({
                "type": "PURCHASE_ORDER",
                "material_id": po.get("material_id"),
                "quantity": po.get("quantity_to_order"),
                "expected_date": po.get("expected_delivery_date"),
                "status": po.get("status"),
            })

        for prod in state.get("production_orders", []):
            flags["inbound_forecast"].append({
                "type": "PRODUCTION",
                "product_id": prod.get("product_id"),
                "quantity": prod.get("target_quantity"),
                "stage": prod.get("current_stage"),
                "status": prod.get("status"),
            })

        return flags


# ══════════════════════════════════════════════════════
# GEMINI REASONING ENGINE
# ══════════════════════════════════════════════════════

MASTER_SYSTEM_PROMPT = """
You are an autonomous Warehouse Optimization Agent inside an AI-driven supply chain system.

You operate using structured data inputs from inventory, warehouse, logistics, production, procurement, and material planning datasets.

You do NOT perform raw mathematical calculations unless explicitly provided.
All numerical computations (stock availability, capacity %, safety stock breach) are precomputed before reaching you.

Your role is strategic reasoning, decision-making, risk detection, and optimization.

Return output strictly in structured JSON.

DECISION RULES:
- Use only provided available_stock. Never assume hidden inventory.
- If available_stock < required_qty → consider split fulfillment, wait for inbound, or trigger reorder.
- If utilization_percent > 85% → flag as high load. If > 95% → critical overload.
- HIGH priority orders override MEDIUM and LOW. HIGH can justify split fulfillment.
- Trigger reorder if available_stock ≤ safety_stock or inbound supply is delayed.
- Evaluate stockout risk, delay risk, capacity risk, supplier risk, congestion risk.

REQUIRED OUTPUT FORMAT:
{
  "allocation_plan": [
    {
      "order_id": "",
      "warehouse_id": "",
      "allocated_quantity": 0,
      "split": false,
      "reasoning": ""
    }
  ],
  "reorder_recommendations": [
    {
      "material_id": "",
      "recommended_quantity": 0,
      "urgency_level": "",
      "reasoning": ""
    }
  ],
  "capacity_alerts": [
    {
      "warehouse_id": "",
      "utilization_percent": 0,
      "severity": "",
      "action_suggested": ""
    }
  ],
  "risk_alerts": [
    {
      "risk_type": "",
      "entity_id": "",
      "severity": "",
      "mitigation_strategy": ""
    }
  ],
  "strategic_summary": ""
}

Do NOT return explanations outside JSON.
Do NOT hallucinate data. Do NOT invent warehouses or products.
Be deterministic and structured. Include confidence_score (0-1) for each decision block.
"""


class GeminiReasoningEngine:
    """Calls gemini-3-flash-preview with condensed state for strategic decisions."""

    def __init__(self, api_key: str = "", model_name: str = "gemini-3-flash-preview"):
        _key = api_key or os.environ.get("GEMINI_API_KEY", "") or "AIzaSyCRUmzBqn9WUn8YxlOc5hmN7_JCotCHq_w"
        genai.configure(api_key=_key)
        self.model = genai.GenerativeModel(model_name)

    def reason(
        self,
        state: Dict[str, Any],
        rule_flags: Dict[str, Any],
        action_type: str = "full_analysis",
        order_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Build prompt → call Gemini → parse JSON response."""

        # Build context for Gemini (condensed, never raw CSV)
        context = {
            "inventory_state": state.get("inventory", []),
            "warehouse_capacity": state.get("warehouse_capacity", []),
            "pending_orders": state.get("pending_orders", []),
            "finished_goods": state.get("finished_goods", []),
            "inbound_forecast": rule_flags.get("inbound_forecast", []),
            "safety_stock_breaches": rule_flags.get("safety_stock_breaches", []),
            "reorder_triggers": rule_flags.get("reorder_triggers", []),
            "capacity_warnings": rule_flags.get("capacity_warnings", []),
        }

        # Build action-specific instruction
        if action_type == "allocate" and order_ids:
            task_instruction = (
                f"Focus on allocating these specific orders: {order_ids}. "
                "Decide which warehouse fulfills each, whether to split, and any risks."
            )
        elif action_type == "reorder_check":
            task_instruction = (
                "Focus on reorder analysis. Check all materials against safety stock and "
                "reorder points. Recommend quantities and urgency levels."
            )
        else:
            task_instruction = (
                "Perform a FULL warehouse analysis: order allocation, reorder recommendations, "
                "capacity alerts, and risk assessment."
            )

        prompt = f"""
SYSTEM:
{MASTER_SYSTEM_PROMPT}

TASK: {task_instruction}

PRECOMPUTED STATE:
{json.dumps(context, indent=2, default=str)}

Analyze and produce your decision. Return ONLY valid JSON.
"""

        logger.info("Calling Gemini for warehouse reasoning [%s]…", action_type)
        response = self.model.generate_content(prompt)

        # Parse JSON from response
        raw_text = response.text.strip()
        # Strip markdown fences if present
        if raw_text.startswith("```"):
            raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3].strip()
        if raw_text.startswith("json"):
            raw_text = raw_text[4:].strip()

        try:
            decision = json.loads(raw_text)
        except json.JSONDecodeError:
            logger.error("Gemini did not return valid JSON: %s", raw_text[:200])
            raise ValueError("Gemini did not return valid JSON.")

        return decision


# ══════════════════════════════════════════════════════
# ACTION DISPATCHER
# ══════════════════════════════════════════════════════

class ActionDispatcher:
    """Normalize and return the structured decision payload."""

    @staticmethod
    def dispatch(decision: Dict[str, Any], request_id: str) -> Dict[str, Any]:
        return {
            "request_id": request_id,
            "allocation_plan": decision.get("allocation_plan", []),
            "reorder_recommendations": decision.get("reorder_recommendations", []),
            "capacity_alerts": decision.get("capacity_alerts", []),
            "risk_alerts": decision.get("risk_alerts", []),
            "strategic_summary": decision.get("strategic_summary", ""),
            "generated_at": datetime.now().isoformat(),
        }


# ══════════════════════════════════════════════════════
# WAREHOUSE AGENT (ORCHESTRATOR)
# ══════════════════════════════════════════════════════

class WarehouseAgent:
    """
    Main entry point.
    Sequence: StateBuilder → RuleEngine → GeminiReasoningEngine → ActionDispatcher
    Every run is logged with a unique request_id.
    """

    def __init__(self, api_key: str = ""):
        self.state_builder = StateBuilder()
        self.rule_engine = RuleEngine()
        self.gemini = GeminiReasoningEngine(api_key=api_key)
        self.logger_ = WarehouseAgentLogger()
        self.dispatcher = ActionDispatcher()

    def analyze(self) -> Dict[str, Any]:
        """Full warehouse analysis → Gemini reasoning → logged decision."""
        return self._run("full_analysis")

    def allocate_orders(self, order_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """Order-specific allocation → Gemini reasoning → logged decision."""
        return self._run("allocate", order_ids=order_ids)

    def reorder_check(self) -> Dict[str, Any]:
        """Reorder evaluation → Gemini reasoning → logged decision."""
        return self._run("reorder_check")

    def _run(
        self,
        action_type: str,
        order_ids: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        # Phase 1 — Build deterministic state
        state = self.state_builder.build()

        # Phase 2 — Rule engine computation
        rule_flags = self.rule_engine.compute(state)

        # Phase 3 — Gemini strategic reasoning
        decision = self.gemini.reason(
            state=state,
            rule_flags=rule_flags,
            action_type=action_type,
            order_ids=order_ids,
        )

        # Phase 4 — Build input summary for logging
        input_summary = json.dumps({
            "inventory_count": len(state.get("inventory", [])),
            "pending_orders_count": len(state.get("pending_orders", [])),
            "warehouse_count": len(state.get("warehouse_capacity", [])),
            "safety_breaches": len(rule_flags.get("safety_stock_breaches", [])),
            "reorder_triggers": len(rule_flags.get("reorder_triggers", [])),
            "capacity_warnings": len(rule_flags.get("capacity_warnings", [])),
        })

        # Extract overall risk from decision
        risk_alerts = decision.get("risk_alerts", [])
        overall_risk = "HIGH" if any(
            r.get("severity", "").upper() in ("HIGH", "CRITICAL") for r in risk_alerts
        ) else "MEDIUM" if risk_alerts else "LOW"

        # Phase 5 — Log with unique ID and full reasoning
        request_id = self.logger_.log(
            action_type=action_type,
            input_summary=input_summary,
            gemini_reasoning=decision.get("strategic_summary", ""),
            decision_json=json.dumps(decision, default=str),
            risk_level=overall_risk,
        )

        # Phase 6 — Dispatch formatted response
        return self.dispatcher.dispatch(decision, request_id)
