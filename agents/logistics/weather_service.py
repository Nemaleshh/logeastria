"""
weather_service.py
───────────────────
Weather via WeatherAPI.com (https://www.weatherapi.com/)

API Base : http://api.weatherapi.com/v1
Endpoint : /current.json?key=<KEY>&q=<lat,lon>&aqi=no

`requests` is imported lazily (inside the function) so a missing
package never crashes Flask blueprint registration.
"""

import logging
import os

logger = logging.getLogger(__name__)

# ── API configuration ─────────────────────────────────────────────────────────
_BASE_URL  = "http://api.weatherapi.com/v1"
_HARD_KEY  = "6a207d99900c4ce2bc783139262102"   # WeatherAPI.com key
_TIMEOUT_S = 6

# ── Mock fallback ──────────────────────────────────────────────────────────────
_MOCK = [
    {"condition": "Sunny",         "temp_c": 29.0, "humidity_pct": 42, "wind_kmh": 10, "risk": "LOW"},
    {"condition": "Partly Cloudy", "temp_c": 25.0, "humidity_pct": 60, "wind_kmh": 18, "risk": "LOW"},
    {"condition": "Heavy Rain",    "temp_c": 21.0, "humidity_pct": 90, "wind_kmh": 38, "risk": "HIGH"},
    {"condition": "Thunderstorm",  "temp_c": 19.0, "humidity_pct": 95, "wind_kmh": 58, "risk": "CRITICAL"},
    {"condition": "Fog",           "temp_c": 18.0, "humidity_pct": 88, "wind_kmh": 5,  "risk": "MEDIUM"},
]


def _api_key() -> str:
    return os.environ.get("WEATHER_API_KEY", _HARD_KEY).strip()


def _assess_risk(condition: str, wind_kph: float, precip_mm: float) -> str:
    c = condition.lower()
    if "thunder" in c or wind_kph > 80 or precip_mm > 30:
        return "CRITICAL"
    if "heavy rain" in c or "blizzard" in c or wind_kph > 50 or precip_mm > 15:
        return "HIGH"
    if "rain" in c or "fog" in c or "mist" in c or "drizzle" in c or wind_kph > 30:
        return "MEDIUM"
    return "LOW"


def _mock_weather(lat: float, lng: float) -> dict:
    idx = int(abs(lat * 10 + lng * 7)) % len(_MOCK)
    w   = _MOCK[idx].copy()
    w["precip_mm"]     = 0.0
    w["visibility_km"] = 10.0
    w["icon"]          = ""
    w["is_mock"]       = True
    w["source"]        = "mock"
    return w


def get_weather(lat: float, lng: float) -> dict:
    """
    Fetch current weather from WeatherAPI.com.
    Falls back to deterministic mock on any error.
    """
    try:
        import requests  # lazy — keeps import from crashing blueprint on startup

        key  = _api_key()
        url  = f"{_BASE_URL}/current.json"
        resp = requests.get(url, params={"key": key, "q": f"{lat},{lng}", "aqi": "no"}, timeout=_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()

        cur       = data["current"]
        cond_text = cur["condition"]["text"]
        wind_kph  = float(cur.get("wind_kph", 0))
        precip_mm = float(cur.get("precip_mm", 0))
        risk      = _assess_risk(cond_text, wind_kph, precip_mm)

        result = {
            "condition":     cond_text,
            "temp_c":        cur.get("temp_c"),
            "humidity_pct":  cur.get("humidity"),
            "wind_kmh":      wind_kph,
            "precip_mm":     precip_mm,
            "visibility_km": cur.get("vis_km"),
            "risk":          risk,
            "icon":          "https:" + cur["condition"]["icon"],
            "is_mock":       False,
            "source":        "weatherapi",
        }
        logger.info(f"[WeatherService] ({lat},{lng}) → {cond_text} | {cur.get('temp_c')}°C | risk={risk}")
        return result

    except Exception as e:
        logger.warning(f"[WeatherService] Live fetch failed: {e} — using mock.")
        return _mock_weather(lat, lng)


def get_route_weather(route: list) -> list:
    """Enrich each stop dict with a 'weather' key."""
    return [{**stop, "weather": get_weather(stop["lat"], stop["lng"])} for stop in route]
