"""
transport_fallback_agent.py
────────────────────────────
Handles fallback scenarios during transport.

Incident types:
  - PUNCTURE         : flat tyre
  - BREAKDOWN        : engine/mechanical failure  
  - ACCIDENT         : collision or road incident
  - ROAD_BLOCK       : road blocked (protest, flood, etc.)
  - VEHICLE_THEFT    : cargo or vehicle stolen
  - DRIVER_UNAVAIL   : driver cannot continue
  - WEATHER_HALT     : severe weather stop
  - FUEL_OUT         : fuel exhausted
  - OTHER            : any other situation

Sends incident details to Gemini LLM → returns recovery_plan with:
  - action         : CONTINUE | REROUTE | REPLACE_VEHICLE | ABORT | WAIT
  - estimated_delay_min : estimated delay in minutes
  - steps          : ordered action steps
  - severity       : LOW | MEDIUM | HIGH | CRITICAL
"""

import csv
import json
import logging
import os
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

_HEADERS = [
    "incident_id", "shipment_id", "vehicle_id", "incident_type",
    "description", "severity", "status", "reported_at",
    "resolved_at", "llm_recovery_plan"
]

_SYSTEM_PROMPT = """
You are the Transport Fallback Agent for an autonomous logistics system.

A transport incident has occurred. You must assess the situation and provide a structured recovery plan.

INCIDENT TYPES and typical responses:
- PUNCTURE        → REPLACE_VEHICLE or WAIT (tyre change ~20 min)
- BREAKDOWN       → REPLACE_VEHICLE (critical) or WAIT (minor)
- ACCIDENT        → ABORT or REROUTE depending on severity
- ROAD_BLOCK      → REROUTE
- VEHICLE_THEFT   → ABORT, contact authorities
- DRIVER_UNAVAIL  → REPLACE_VEHICLE or ABORT
- WEATHER_HALT    → WAIT or REROUTE
- FUEL_OUT        → WAIT (fuel delivery ~15–30 min)
- OTHER           → assess contextually

STRICT RULES:
- Return ONLY valid JSON. No markdown. No explanation outside JSON.
- Be practical and realistic with delay estimates.
- steps must be a list of 3-5 actionable strings numbered.

Return exactly:
{
  "action": "CONTINUE|REROUTE|REPLACE_VEHICLE|ABORT|WAIT",
  "severity": "LOW|MEDIUM|HIGH|CRITICAL",
  "estimated_delay_min": <integer>,
  "steps": ["1. ...", "2. ...", "3. ..."],
  "notify_customer": true|false,
  "summary": "<one sentence summary>"
}
"""


def _incident_path(db_path: str) -> str:
    return os.path.join(db_path, "logistics_incidents.csv")


def _ensure_headers(db_path: str):
    path = _incident_path(db_path)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(_HEADERS)


def _load_all(db_path: str) -> list:
    _ensure_headers(db_path)
    with open(_incident_path(db_path), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _save_row(row: dict, db_path: str):
    _ensure_headers(db_path)
    with open(_incident_path(db_path), "a", newline="", encoding="utf-8") as f:
        csv.DictWriter(f, fieldnames=_HEADERS).writerow(row)


def _update_shipment_status(shipment_id: str, new_status: str, db_path: str):
    """Update the status in logistics_shipments.csv."""
    path = os.path.join(db_path, "logistics_shipments.csv")
    if not os.path.exists(path):
        return
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        headers = f.name  # capture field names

    fields = list(rows[0].keys()) if rows else []
    for row in rows:
        if row.get("shipment_id") == shipment_id:
            row["status"] = new_status

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def report_incident(
    shipment_id: str,
    vehicle_id: str,
    incident_type: str,
    description: str,
    model,
    db_path: str = "data_base",
) -> dict:
    """
    Report a transport incident and get an LLM recovery plan.

    Parameters
    ----------
    shipment_id   : active shipment ID
    vehicle_id    : vehicle reporting the incident
    incident_type : see INCIDENT TYPES above
    description   : free-text description from driver
    model         : google.generativeai.GenerativeModel instance
    db_path       : CSV directory

    Returns
    -------
    {
        "incident_id":          str,
        "action":               str,
        "severity":             str,
        "estimated_delay_min":  int,
        "steps":                list[str],
        "notify_customer":      bool,
        "summary":              str,
        "status":               "OPEN"
    }
    """
    incident_id = "INC-" + str(uuid.uuid4())[:8].upper()
    logger.info(
        f"[TransportFallback] ▶ Incident {incident_id} | shipment={shipment_id} "
        f"| vehicle={vehicle_id} | type={incident_type}"
    )

    # ── LLM Recovery Plan ──────────────────────────────────────────────────
    prompt = f"""
SYSTEM:
{_SYSTEM_PROMPT}

INCIDENT DETAILS:
{json.dumps({
    "incident_id":  incident_id,
    "shipment_id":  shipment_id,
    "vehicle_id":   vehicle_id,
    "incident_type": incident_type,
    "description":  description,
    "reported_at":  datetime.now().isoformat(timespec="seconds"),
}, indent=2)}

Provide a structured recovery plan. Return ONLY valid JSON.
"""

    try:
        response = model.generate_content(prompt)
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        recovery = json.loads(raw)
    except Exception as e:
        logger.error(f"[TransportFallback] LLM error: {e}. Using fallback plan.")
        recovery = {
            "action": "WAIT",
            "severity": "MEDIUM",
            "estimated_delay_min": 30,
            "steps": [
                "1. Stop vehicle safely at the side of the road.",
                "2. Contact dispatch for support.",
                "3. Wait for instructions.",
            ],
            "notify_customer": True,
            "summary": f"Incident '{incident_type}' occurred. Awaiting resolution.",
        }

    severity = recovery.get("severity", "MEDIUM")

    # ── Save to CSV ────────────────────────────────────────────────────────
    row = {
        "incident_id":      incident_id,
        "shipment_id":      shipment_id,
        "vehicle_id":       vehicle_id,
        "incident_type":    incident_type,
        "description":      description,
        "severity":         severity,
        "status":           "OPEN",
        "reported_at":      datetime.now().isoformat(timespec="seconds"),
        "resolved_at":      "",
        "llm_recovery_plan": json.dumps(recovery),
    }
    _save_row(row, db_path)

    # ── Update shipment status if HIGH/CRITICAL ────────────────────────────
    if severity in ("HIGH", "CRITICAL") or recovery.get("action") == "ABORT":
        _update_shipment_status(shipment_id, "INCIDENT", db_path)
        logger.warning(
            f"[TransportFallback] Shipment {shipment_id} flagged as INCIDENT "
            f"(severity={severity})"
        )

    logger.info(
        f"[TransportFallback] ✔ Recovery plan: action={recovery.get('action')} "
        f"| delay={recovery.get('estimated_delay_min')} min | severity={severity}"
    )

    return {
        "incident_id":         incident_id,
        "shipment_id":         shipment_id,
        "vehicle_id":          vehicle_id,
        "incident_type":       incident_type,
        **recovery,
        "status":              "OPEN",
    }


def resolve_incident(incident_id: str, db_path: str = "data_base") -> dict:
    """Mark an incident as RESOLVED."""
    rows = _load_all(db_path)
    matched = False
    for row in rows:
        if row["incident_id"] == incident_id:
            row["status"] = "RESOLVED"
            row["resolved_at"] = datetime.now().isoformat(timespec="seconds")
            matched = True
            break

    if not matched:
        return {"success": False, "message": f"Incident {incident_id} not found."}

    fields = list(rows[0].keys()) if rows else _HEADERS
    with open(_incident_path(db_path), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    logger.info(f"[TransportFallback] ✅ Incident {incident_id} resolved.")
    return {"success": True, "incident_id": incident_id, "status": "RESOLVED"}


def get_open_incidents(db_path: str = "data_base") -> list:
    """Return all OPEN incidents."""
    return [r for r in _load_all(db_path) if r["status"] == "OPEN"]


def get_all_incidents(db_path: str = "data_base") -> list:
    return _load_all(db_path)
