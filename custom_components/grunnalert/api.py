"""Kleine client voor de openbare GrunnAlert-API."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import math
import re
import unicodedata
from typing import Any
from urllib.parse import quote

import aiohttp

from .const import (
    API_BASE,
    AREA_GRONINGEN,
    AREA_PLACES,
    ATTRIBUTION,
    DISCIPLINE_LABELS,
    DISCIPLINES,
    FETCH_LIMIT,
    INSTALL_HEADER,
    PLAY_STORE_URL,
    USER_AGENT,
    WEBSITE_URL,
)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)
# Grenzen zodat een kapotte of gehackte server Home Assistant niet kan laten
# vollopen. Echte meldingen blijven hier ruim onder.
MAX_RESPONSE_BYTES = 512 * 1024
MAX_ID_LENGTH = 64
MAX_TEXT_LENGTH = 500
MAX_FIELD_LENGTH = 100
MAX_UNITS = 30
# 1 januari 2100; alles daarna is onzin.
MAX_TIMESTAMP_MS = 4_102_444_800_000
SERVER_FETCH_LIMIT = 100

# "0400272 23:17:09 02-10-26 FLEX-A  GROUP  1600  " vooraan een ruwe FLEX-regel.
_HEADER_RE = re.compile(
    r"^\s*\d{7}\s+\d{2}:\d{2}:\d{2}\s+\d{2}-\d{2}-\d{2}\s+FLEX-\w+\s+\w+\s+\d+\s+"
)
# Afsluitende ritnummers zoals " 011851 013593".
_TRAILER_RE = re.compile(r"(?:\s+\d{5,6})+\s*$")


class GrunnAlertApiError(Exception):
    """De GrunnAlert-API gaf een fout of was onbereikbaar."""


def clean_message(raw_text: str) -> str:
    """Haalt de technische FLEX-kop en het ritnummer van een melding af."""
    text = _HEADER_RE.sub("", raw_text or "")
    text = _TRAILER_RE.sub("", text)
    return " ".join(text.split()) or (raw_text or "").strip()


def dedupe_key(raw_text: str) -> str:
    """Tekst zonder FLEX-kop maar met ritnummer.

    GROUP- en ALPHA-varianten van dezelfde melding vallen hierop samen, twee
    verschillende ritten met verder gelijke tekst niet.
    """
    return " ".join(_HEADER_RE.sub("", raw_text or "").split())


def place_key(value: str | None) -> str:
    """Zelfde normalisatie als de website: accenten weg, kleine letters."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.lower().strip()


def _text(value: Any, limit: int = MAX_FIELD_LENGTH) -> str:
    return str(value or "").strip()[:limit]


def _coordinate(value: Any, bound: float) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or abs(number) > bound:
        return None
    return number


def normalize_alert(value: Any) -> dict[str, Any] | None:
    """Zet een API-melding om naar het formaat dat de integratie doorgeeft.

    Alles wat niet klopt wordt weggegooid of ingekort, zodat een rare melding
    nooit de integratie kan laten vastlopen.
    """
    if not isinstance(value, dict):
        return None
    alert_id = str(value.get("id") or "").strip()
    raw_text = _text(value.get("raw_text"), MAX_TEXT_LENGTH)
    try:
        received_ms = float(value.get("received_at"))
    except (TypeError, ValueError, OverflowError):
        return None
    if (
        not alert_id
        or len(alert_id) > MAX_ID_LENGTH
        or not raw_text
        or not math.isfinite(received_ms)
        or not 0 < received_ms < MAX_TIMESTAMP_MS
    ):
        return None

    discipline = value.get("discipline")
    if discipline not in DISCIPLINES:
        discipline = "other"
    priority = value.get("priority") if value.get("priority") in (1, 2) else None
    city = _text(value.get("city"))
    region = _text(value.get("region"))
    street = _text(value.get("street"))

    latitude = _coordinate(value.get("lat"), 90) if street else None
    longitude = _coordinate(value.get("lon"), 180) if street else None
    if latitude is None or longitude is None:
        street = ""
        latitude = longitude = None

    place = city or region
    location = f"{street}, {place}" if street and place else (street or place)
    if latitude is not None:
        maps_url = f"https://www.google.com/maps?q={latitude},{longitude}"
    elif place:
        maps_url = "https://www.google.com/maps?q=" + quote(f"{place}, Nederland")
    else:
        maps_url = None

    targets = value.get("targets") if isinstance(value.get("targets"), list) else []
    units = [
        _text(target.get("label"))
        for target in targets[:MAX_UNITS]
        if isinstance(target, dict) and _text(target.get("label"))
    ]

    return {
        "id": alert_id,
        "message": clean_message(raw_text),
        "raw_text": raw_text,
        "priority": priority,
        "discipline": discipline,
        "discipline_label": DISCIPLINE_LABELS[discipline],
        "city": city,
        "region": region,
        "street": street,
        "location": location,
        "latitude": latitude,
        "longitude": longitude,
        "maps_url": maps_url,
        "units": units,
        "received_at": datetime.fromtimestamp(
            received_ms / 1000, tz=timezone.utc
        ).isoformat(),
        "received_ms": int(received_ms),
        "source": "GrunnAlert",
        "source_url": WEBSITE_URL,
        "app_url": PLAY_STORE_URL,
        "attribution": ATTRIBUTION,
    }


def matches_selection(
    alert: dict[str, Any],
    area: str,
    places: list[str],
    disciplines: list[str],
) -> bool:
    """Controleert of een (live) melding binnen de gekozen filters valt."""
    if alert["discipline"] not in disciplines:
        return False
    if not alert["region"] or alert["region"] == "Onbekend":
        return False
    if area == AREA_PLACES:
        wanted = {place_key(place) for place in places}
        return place_key(alert["city"]) in wanted
    return True


class GrunnAlertClient:
    """Praat met https://grunnalert.nl."""

    def __init__(
        self, session: aiohttp.ClientSession, install_id: str | None = None
    ) -> None:
        self._session = session
        self._headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if install_id:
            # Anonieme, willekeurige ID zodat GrunnAlert kan tellen hoeveel
            # Home Assistant-installaties er zijn. Bevat geen persoonsgegevens.
            self._headers[INSTALL_HEADER] = install_id

    async def _get_json(self, path: str, params: dict[str, str] | None = None) -> dict:
        try:
            async with self._session.get(
                f"{API_BASE}{path}",
                params=params,
                headers=self._headers,
                timeout=REQUEST_TIMEOUT,
            ) as response:
                if response.status != 200:
                    raise GrunnAlertApiError(f"HTTP {response.status} van GrunnAlert")
                if (getattr(response, "content_length", None) or 0) > MAX_RESPONSE_BYTES:
                    raise GrunnAlertApiError("Antwoord van GrunnAlert is te groot")
                # In stukken lezen: een enkele read() geeft alleen terug wat er
                # op dat moment binnen is, niet het hele antwoord.
                body = bytearray()
                async for chunk in response.content.iter_chunked(16384):
                    body += chunk
                    if len(body) > MAX_RESPONSE_BYTES:
                        raise GrunnAlertApiError("Antwoord van GrunnAlert is te groot")
                payload = json.loads(bytes(body))
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise GrunnAlertApiError(f"GrunnAlert niet bereikbaar: {err}") from err
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise GrunnAlertApiError("Onverwacht antwoord van GrunnAlert")
        return payload

    async def async_get_places(self) -> list[str]:
        """Alle plaatsen waarop GrunnAlert kan filteren."""
        payload = await self._get_json("/v1/filter-options")
        places = payload.get("places")
        if not isinstance(places, list):
            raise GrunnAlertApiError("Geen plaatsenlijst ontvangen")
        return [_text(place) for place in places[:1000] if _text(place)]

    async def async_get_alerts(
        self, area: str, places: list[str], disciplines: list[str]
    ) -> list[dict[str, Any]]:
        """Laatste meldingen binnen de filters, nieuwste eerst.

        We vragen altijd de hele provincie op en filteren hier lokaal. Zo
        hoeft de server nooit te weten welke plaatsen iemand volgt.
        """
        payload = await self._get_json(
            "/v1/alerts",
            {"filter": AREA_GRONINGEN, "limit": str(SERVER_FETCH_LIMIT)},
        )
        alerts = payload.get("alerts")
        if not isinstance(alerts, list):
            raise GrunnAlertApiError("Geen meldingen ontvangen")
        normalized = [
            alert
            for alert in map(normalize_alert, alerts[:SERVER_FETCH_LIMIT])
            if alert and matches_selection(alert, area, places, disciplines)
        ]
        normalized.sort(key=lambda alert: alert["received_ms"], reverse=True)
        return normalized[:FETCH_LIMIT]
