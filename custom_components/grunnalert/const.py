"""Constanten voor de GrunnAlert-integratie."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "grunnalert"
NAME: Final = "GrunnAlert"
VERSION: Final = "1.0.1"
AUTHOR: Final = "StarlightFM"

API_BASE: Final = "https://grunnalert.nl"
LIVE_URL: Final = "wss://grunnalert.nl/v1/live"
WEBSITE_URL: Final = "https://grunnalert.nl"
PLAY_STORE_URL: Final = (
    "https://play.google.com/store/apps/details?id=com.starlightfm.p2000monitor"
)
USER_AGENT: Final = f"HomeAssistant-GrunnAlert/{VERSION} (+{WEBSITE_URL})"
INSTALL_HEADER: Final = "X-GrunnAlert-Install"

ATTRIBUTION: Final = "Meldingen geleverd door GrunnAlert (grunnalert.nl)"
PROMO_TEXT: Final = (
    "Ook onderweg op de hoogte? Download de gratis GrunnAlert-app: "
    f"{PLAY_STORE_URL}"
)

EVENT_ALERT: Final = "grunnalert_alert"

CONF_AREA: Final = "area"
CONF_PLACES: Final = "places"
CONF_DISCIPLINES: Final = "disciplines"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_MAP_MINUTES: Final = "map_minutes"

AREA_GRONINGEN: Final = "groningen"
AREA_PLACES: Final = "places"
AREAS: Final = [AREA_GRONINGEN, AREA_PLACES]
AREA_LABELS: Final = {
    AREA_GRONINGEN: "provincie Groningen",
    AREA_PLACES: "eigen plaatsen",
}

DISCIPLINES: Final = ["fire", "ambulance", "police", "other"]
DISCIPLINE_LABELS: Final = {
    "fire": "Brandweer",
    "ambulance": "Ambulance",
    "police": "Politie",
    "other": "Overig",
}
DISCIPLINE_ICONS: Final = {
    "fire": "mdi:fire-truck",
    "ambulance": "mdi:ambulance",
    "police": "mdi:police-badge",
    "other": "mdi:alarm-light",
}

# Polling is alleen nog een vangnet naast de live WebSocket, dus rustig aan
# doen voor de GrunnAlert-server.
DEFAULT_SCAN_INTERVAL: Final = 120
MIN_SCAN_INTERVAL: Final = 60
MAX_SCAN_INTERVAL: Final = 900
DEFAULT_MAP_MINUTES: Final = 60

FETCH_LIMIT: Final = 25
LIVE_PING_INTERVAL: Final = timedelta(seconds=30)
LIVE_RECONNECT_MIN: Final = 5
LIVE_RECONNECT_MAX: Final = 300
