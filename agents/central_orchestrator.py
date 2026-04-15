"""
central_orchestrator.py — Central Supply-Chain Orchestrator Agent

Aggregates state from every CSV, builds query-specific context,
calls Gemini for reasoning, and surfaces high-risk alerts.
Leaves the existing orchestrator_agent.py untouched.
"""

import json
import os
import uuid
import csv
import time
from datetime import datetime
from typing import Dict, Any, List

import pandas as pd
import google.generativeai as genai

# ── paths ────────────────────────────────────────────
BASE = os.path.join(os.path.dirname(__file__), "..", "data_base")
CHAT_LOG = os.path.join(BASE, "orchestrator_chat_log.csv")

CHAT_LOG_COLUMNS = [
    "message_id", "user_query", "analysis", "risk_level",
    "confidence_score", "timestamp"
]


# ──────────────────────────────────────────────────────
# SYSTEM PROMPT
# ──────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are the Central Supply Chain Orchestrator Agent for LOGISTRIA.

You have full visibility over:
- Warehouse operations (capacity, utilisation)
- Production flow (orders, WIP, stages)
- Procurement activities (purchase orders, supplier risk)
- Logistics shipments (status, delays)
- Inventory levels (raw materials, finished goods)
- Material planning (demand, safety stock)
- Past orchestration decisions

STRICT RULES:
- Do NOT fabricate data. Reason ONLY from the structured state provided.
- Do NOT compute math — use the numbers as given.
- Identify bottlenecks, diagnose delays, and recommend corrective actions.
- When the user asks about a specific entity (shipment, order, material),
  focus your analysis on that entity and its upstream/downstream dependencies.

Always respond in this JSON format (no markdown fences):

{
  "analysis": "<clear, conversational explanation>",
  "root_cause": "<if applicable, otherwise null>",
  "affected_entities": ["<entity_id>", ...],
  "risk_level": "LOW | MEDIUM | HIGH | CRITICAL",
  "recommended_actions": ["<action1>", ...],
  "confidence_score": 0.0
}
"""


def _read(fname: str) -> pd.DataFrame:
    path = os.path.join(BASE, fname)
    if os.path.exists(path):
        try:
            return pd.read_csv(path)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


class CentralOrchestrator:
    """
    Stateless orchestrator — every call re-reads CSVs so state is always fresh.
    """

    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash"):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        self._ensure_log()

    # ── state aggregation ─────────────────────────────
    def gather_global_state(self) -> Dict[str, Any]:
        inventory = _read("inventory.csv")
        warehouse = _read("warehouse.csv")
        shipments = _read("logistics_shipments.csv")
        production = _read("production_orders.csv")
        purchase   = _read("purchase_orders.csv")
        planning   = _read("material_planning.csv")
        wip        = _read("wip_tracking.csv")
        orch_log   = _read("orchestration_log.csv")

        return {
            "inventory_summary": inventory.to_dict(orient="records") if not inventory.empty else [],
            "warehouse_utilization": warehouse.to_dict(orient="records") if not warehouse.empty else [],
            "active_shipments": shipments.to_dict(orient="records") if not shipments.empty else [],
            "production_status": production.to_dict(orient="records") if not production.empty else [],
            "purchase_orders": purchase.to_dict(orient="records") if not purchase.empty else [],
            "material_planning": planning.to_dict(orient="records") if not planning.empty else [],
            "wip_tracking": wip.to_dict(orient="records") if not wip.empty else [],
            "orchestration_history": orch_log.to_dict(orient="records") if not orch_log.empty else [],
        }

    # ── alert scanner ─────────────────────────────────
    def scan_alerts(self) -> List[Dict[str, Any]]:
        alerts: List[Dict[str, Any]] = []

        # 1. Warehouse near capacity (>85 %)
        wh = _read("warehouse.csv")
        if not wh.empty:
            for _, r in wh.iterrows():
                try:
                    pct = float(r["current_occupied"]) / float(r["max_capacity"])
                    if pct > 0.85:
                        alerts.append({
                            "type": "WAREHOUSE_CAPACITY",
                            "entity_id": r["warehouse_id"],
                            "risk_level": "CRITICAL" if pct > 0.95 else "HIGH",
                            "message": f"Warehouse {r['warehouse_id']} at {pct*100:.0f}% capacity ({r['current_occupied']}/{r['max_capacity']})"
                        })
                except Exception:
                    pass

        # 2. Low inventory (current_stock <= 2× safety_stock)
        inv = _read("inventory.csv")
        plan = _read("material_planning.csv")
        if not inv.empty and not plan.empty:
            safety_map = dict(zip(plan["material_id"], plan["safety_stock"]))
            for _, r in inv.iterrows():
                ss = safety_map.get(r["product_id"], 0)
                try:
                    if float(r["current_stock"]) <= 2 * float(ss) and float(ss) > 0:
                        alerts.append({
                            "type": "LOW_INVENTORY",
                            "entity_id": r["product_id"],
                            "risk_level": "CRITICAL" if float(r["current_stock"]) <= float(ss) else "HIGH",
                            "message": f"Material {r['product_id']} stock={r['current_stock']} (safety_stock={ss})"
                        })
                except Exception:
                    pass

        # 3. High-risk purchase orders still pending
        po = _read("purchase_orders.csv")
        if not po.empty:
            for _, r in po.iterrows():
                rl = str(r.get("risk_level", "")).lower()
                status = str(r.get("status", "")).upper()
                if status == "PENDING" and ("high" in rl or "critical" in rl):
                    alerts.append({
                        "type": "HIGH_RISK_PO",
                        "entity_id": r["po_id"],
                        "risk_level": "HIGH",
                        "message": f"PO {r['po_id']} for {r.get('material_id','')} is PENDING with risk={r['risk_level']}"
                    })

        # 4. Stalled production (IN_PROGRESS but not updated in 24h)
        prod = _read("production_orders.csv")
        if not prod.empty:
            now = datetime.now()
            for _, r in prod.iterrows():
                if str(r.get("status", "")).upper() == "IN_PROGRESS":
                    try:
                        lu = pd.to_datetime(r["last_updated"])
                        hours = (now - lu).total_seconds() / 3600
                        if hours > 24:
                            alerts.append({
                                "type": "STALLED_PRODUCTION",
                                "entity_id": r["production_id"],
                                "risk_level": "HIGH",
                                "message": f"Production {r['production_id']} stuck at {r['current_stage']} for {hours:.0f}h"
                            })
                    except Exception:
                        pass

        # 5. Shipments in transit too long (>48h)
        ship = _read("logistics_shipments.csv")
        if not ship.empty:
            now = datetime.now()
            for _, r in ship.iterrows():
                if str(r.get("status", "")).upper() == "IN_TRANSIT":
                    try:
                        ca = pd.to_datetime(r["created_at"])
                        hours = (now - ca).total_seconds() / 3600
                        if hours > 48:
                            alerts.append({
                                "type": "DELAYED_SHIPMENT",
                                "entity_id": r["shipment_id"],
                                "risk_level": "HIGH",
                                "message": f"Shipment {r['shipment_id']} in transit for {hours:.0f}h"
                            })
                    except Exception:
                        pass

        return alerts

    # ── chat handler ──────────────────────────────────
    def answer_query(self, user_query: str) -> Dict[str, Any]:
        state = self.gather_global_state()
        alerts = self.scan_alerts()

        prompt = f"""{SYSTEM_PROMPT}

CURRENT GLOBAL STATE:
{json.dumps(state, indent=2, default=str)}

ACTIVE ALERTS:
{json.dumps(alerts, indent=2, default=str)}

USER QUERY:
{user_query}

Analyze the state and answer the user's question. Return ONLY valid JSON."""

        try:
            # Retry with backoff for free-tier rate limits
            last_err = None
            for attempt in range(3):
                try:
                    response = self.model.generate_content(prompt)
                    raw = response.text.strip()
                    break
                except Exception as retry_err:
                    last_err = retry_err
                    if attempt < 2:
                        time.sleep(35 * (attempt + 1))  # 35s, 70s
                    continue
            else:
                raise last_err  # all retries failed

            # strip markdown fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1]
                if raw.endswith("```"):
                    raw = raw[:-3]
                raw = raw.strip()
            decision = json.loads(raw)
        except json.JSONDecodeError:
            decision = {
                "analysis": response.text if 'response' in dir() else "Failed to parse AI response.",
                "root_cause": None,
                "affected_entities": [],
                "risk_level": "UNKNOWN",
                "recommended_actions": ["Retry the query or rephrase."],
                "confidence_score": 0.0,
            }
        except Exception as e:
            decision = {
                "analysis": f"Error communicating with AI: {str(e)}",
                "root_cause": None,
                "affected_entities": [],
                "risk_level": "UNKNOWN",
                "recommended_actions": ["Check API key and network connectivity."],
                "confidence_score": 0.0,
            }

        # log
        self._log_chat(user_query, decision)

        return decision

    # ── logging ───────────────────────────────────────
    def _ensure_log(self):
        if not os.path.exists(CHAT_LOG):
            with open(CHAT_LOG, "w", newline="") as f:
                csv.writer(f).writerow(CHAT_LOG_COLUMNS)

    def _log_chat(self, query: str, decision: dict):
        with open(CHAT_LOG, "a", newline="") as f:
            csv.writer(f).writerow([
                str(uuid.uuid4()),
                query,
                decision.get("analysis", ""),
                decision.get("risk_level", ""),
                decision.get("confidence_score", 0),
                datetime.now().isoformat(),
            ])
