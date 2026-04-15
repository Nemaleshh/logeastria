"""
warehouse_service.py  — Business logic for warehouse insights
"""
import os, pandas as pd
from datetime import datetime

BASE = os.path.join(os.path.dirname(__file__), "..", "data_base")

def _read(fname):
    try:
        return pd.read_csv(os.path.join(BASE, fname))
    except Exception:
        return pd.DataFrame()

def get_capacity_overview():
    wh = _read("warehouse.csv")
    inv = _read("inventory.csv")
    fgi = _read("finished_goods_inventory.csv")

    warehouses, total_max, total_used = [], 0, 0

    if not wh.empty:
        wh["max_capacity"] = pd.to_numeric(wh["max_capacity"], errors="coerce").fillna(0)
        raw_by_wh = {}
        if not inv.empty and "warehouse_location" in inv.columns:
            inv["current_stock"] = pd.to_numeric(inv["current_stock"], errors="coerce").fillna(0)
            raw_by_wh = inv.groupby("warehouse_location")["current_stock"].sum().to_dict()
        fg_total = 0.0
        if not fgi.empty and "current_stock" in fgi.columns:
            fg_total = pd.to_numeric(fgi["current_stock"], errors="coerce").fillna(0).sum()

        for _, row in wh.iterrows():
            wid = str(row["warehouse_id"])
            max_cap = float(row["max_capacity"])
            occupied = raw_by_wh.get(wid, 0.0) + (fg_total if wid == "WH1" else 0.0)
            free = max(0.0, max_cap - occupied)
            pct = round(occupied / max_cap * 100, 1) if max_cap > 0 else 0.0
            warehouses.append({
                "warehouse_id": wid, "max_capacity": int(max_cap),
                "occupied": float(round(occupied, 1)), "free": float(round(free, 1)),
                "utilization_pct": float(pct), "alert": bool(pct >= 90),
                "status": "CRITICAL" if pct >= 90 else "WARNING" if pct >= 75 else "NORMAL",
            })
            total_max += max_cap; total_used += occupied

    overall_pct = float(round(total_used / total_max * 100, 1)) if total_max > 0 else 0.0
    return {
        "warehouses": warehouses,
        "totals": {"max_capacity": int(total_max), "occupied": float(round(total_used, 1)),
                   "free": float(round(max(0, total_max - total_used), 1)), "utilization_pct": overall_pct},
        "generated_at": datetime.utcnow().isoformat(),
    }

def get_inventory_breakdown():
    inv = _read("inventory.csv")
    if inv.empty:
        return {"items": [], "summary": {}}
    inv["current_stock"] = pd.to_numeric(inv["current_stock"], errors="coerce").fillna(0)
    inv["reserved_stock"] = pd.to_numeric(inv["reserved_stock"], errors="coerce").fillna(0)
    items = []
    for _, row in inv.iterrows():
        t = float(row["current_stock"]); r = float(row["reserved_stock"])
        items.append({"product_id": str(row.get("product_id", "")), "current_stock": float(t),
                      "reserved_stock": float(r), "available_stock": float(round(t - r, 1)),
                      "warehouse_location": str(row.get("warehouse_location", "")),
                      "inventory_type": str(row.get("inventory_type", "RAW")),
                      "last_updated": str(row.get("last_updated", ""))})
    return {"items": items, "summary": {"total_skus": len(items),
            "total_stock": int(inv["current_stock"].sum()), "total_reserved": int(inv["reserved_stock"].sum())}}

def get_finished_goods():
    fgi = _read("finished_goods_inventory.csv")
    if fgi.empty:
        return {"items": [], "total_stock": 0}
    fgi["current_stock"] = pd.to_numeric(fgi["current_stock"], errors="coerce").fillna(0)
    return {"items": fgi.to_dict(orient="records"), "total_stock": int(fgi["current_stock"].sum())}

def get_wip_summary():
    wip = _read("wip_tracking.csv")
    if wip.empty:
        return {"productions": [], "summary": {}}
    wip["quantity"] = pd.to_numeric(wip["quantity"], errors="coerce").fillna(0)
    if "last_updated" in wip.columns:
        wip["last_updated"] = pd.to_datetime(wip["last_updated"], errors="coerce")
        latest = wip.sort_values("last_updated").groupby("production_id").last().reset_index()
    else:
        latest = wip.groupby("production_id").last().reset_index()

    productions = []
    for _, row in latest.iterrows():
        pid = str(row["production_id"])
        stages_df = wip[wip["production_id"] == pid]
        done = len(stages_df[stages_df["status"] == "COMPLETED"])
        total = len(stages_df)
        productions.append({
            "production_id": pid, "current_stage": str(row.get("stage_name", "")),
            "current_status": str(row.get("status", "")), "quantity": int(row.get("quantity", 0)),
            "stages_completed": done, "total_stages": total,
            "progress_pct": round(done / total * 100) if total > 0 else 0,
            "last_updated": str(row.get("last_updated", ""))
        })
    in_prog = [p for p in productions if p["current_status"] == "IN_PROGRESS"]
    done_p  = [p for p in productions if p["current_status"] == "COMPLETED"]
    return {"productions": productions, "summary": {"total_productions": len(productions),
            "in_progress": len(in_prog), "completed": len(done_p),
            "total_units_wip": int(wip[wip["status"] == "IN_PROGRESS"]["quantity"].sum())}}

def get_ai_insights():
    cap = get_capacity_overview()
    inv = get_inventory_breakdown()
    wip = get_wip_summary()
    fgi = get_finished_goods()

    insights, recommendations, alerts = [], [], []

    for wh in cap["warehouses"]:
        p = wh["utilization_pct"]
        if p >= 90:
            alerts.append(f"🚨 CRITICAL: {wh['warehouse_id']} at {p}% capacity ({wh['occupied']}/{wh['max_capacity']} units).")
            recommendations.append(f"Transfer stock from {wh['warehouse_id']} or arrange external storage immediately.")
        elif p >= 75:
            alerts.append(f"⚠️ WARNING: {wh['warehouse_id']} at {p}% — plan reallocation within 7 days.")

    ts = inv["summary"].get("total_stock", 0); tr = inv["summary"].get("total_reserved", 0)
    skus = inv["summary"].get("total_skus", 0)
    insights.append(f"📦 Raw Inventory: {skus} SKUs with {ts:,} total units ({tr:,} reserved).")
    avail = ts - tr
    if avail < 1000:
        recommendations.append("⚡ Available raw stock low. Trigger reorder for critical SKUs immediately.")
    else:
        insights.append(f"✅ {avail:,} units available for production — levels healthy.")

    ws = wip["summary"]
    if ws.get("in_progress", 0) > 0:
        insights.append(f"🏭 WIP: {ws['in_progress']} order(s) in progress, {ws.get('total_units_wip', 0)} units being processed.")
    else:
        insights.append("🏭 WIP: No active production orders.")

    fg = fgi.get("total_stock", 0)
    if fg > 0:
        insights.append(f"🎁 Finished Goods: {fg} units ready for dispatch.")
        if fg > 100:
            recommendations.append("📊 Finished goods stock high — accelerate customer order fulfilment.")
    else:
        insights.append("🎁 Finished Goods: No finished goods in stock.")

    op = float(cap["totals"]["utilization_pct"])
    health = "OPTIMAL" if op < 70 and avail >= 1000 else "AT RISK" if op >= 85 and avail < 500 else "MODERATE"
    strategy = f"Overall {op}% capacity utilised. Health: {health}\n\n"
    strategy += "Actions:\n" + ("\n".join(f"• {r}" for r in recommendations) if recommendations else "• System operating normally.")

    return {"health_status": health, "health_color": "green" if health == "OPTIMAL" else "red" if health == "AT RISK" else "yellow",
            "overall_utilization": float(op), "insights": insights, "alerts": alerts,
            "recommendations": recommendations, "strategy_text": strategy, "generated_at": datetime.utcnow().isoformat()}


# ──────────────────────────────────────────────────────
# AI WAREHOUSE AGENT — Gemini-powered reasoning
# ──────────────────────────────────────────────────────

def _get_agent():
    from agents.warehouse_agent import WarehouseAgent
    return WarehouseAgent()

def run_warehouse_agent():
    """Full warehouse analysis: state → rules → Gemini → decision."""
    return _get_agent().analyze()

def run_order_allocation(order_ids=None):
    """Allocate specific orders to warehouses via Gemini reasoning."""
    return _get_agent().allocate_orders(order_ids=order_ids)

def run_reorder_check():
    """Check all materials for reorder needs via Gemini reasoning."""
    return _get_agent().reorder_check()
