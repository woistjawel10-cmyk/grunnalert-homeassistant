"""Haalt GrunnAlert-meldingen op: live via WebSocket, met polling als vangnet."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import timedelta
import json
import logging
import random
import time
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    GrunnAlertApiError,
    GrunnAlertClient,
    dedupe_key,
    matches_selection,
    normalize_alert,
)
from .const import (
    CONF_AREA,
    CONF_DISCIPLINES,
    CONF_MAP_MINUTES,
    CONF_PLACES,
    CONF_SCAN_INTERVAL,
    DEFAULT_MAP_MINUTES,
    DEFAULT_SCAN_INTERVAL,
    DISCIPLINES,
    DOMAIN,
    EVENT_ALERT,
    FETCH_LIMIT,
    LIVE_PING_INTERVAL,
    LIVE_RECONNECT_MAX,
    LIVE_RECONNECT_MIN,
    LIVE_URL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

# Een melding die we pas (veel) later via polling zien, bijvoorbeeld na een
# lange storing, sturen we niet meer als event: anders krijgt iemand na een
# herstart ineens een hele stapel oude meldingen.
MAX_EVENT_AGE_MS = 30 * 60 * 1000
SEEN_LIMIT = 1000
# Dezelfde melding komt soms twee keer binnen (GROUP en ALPHA) met een eigen
# id. Gelijke tekst binnen dit venster geeft maar een event.
DUPLICATE_WINDOW_MS = 120 * 1000
# Rem op events, voor het geval de server ooit onzin gaat sturen.
MAX_EVENTS_PER_MINUTE = 30
MAX_LIVE_MESSAGE_BYTES = 64 * 1024
# Zolang de live verbinding werkt is polling bijna overbodig.
LIVE_POLL_INTERVAL_S = 30 * 60

type GrunnAlertConfigEntry = ConfigEntry[GrunnAlertCoordinator]


def entry_settings(entry: ConfigEntry) -> dict[str, Any]:
    """Instellingen uit de setup, overschreven door de opties."""
    settings = {**entry.data, **entry.options}
    settings.setdefault(CONF_PLACES, [])
    settings.setdefault(CONF_DISCIPLINES, list(DISCIPLINES))
    settings.setdefault(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    settings.setdefault(CONF_MAP_MINUTES, DEFAULT_MAP_MINUTES)
    return settings


class GrunnAlertCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Houdt de laatste meldingen bij en vuurt een event per nieuwe melding."""

    config_entry: GrunnAlertConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: GrunnAlertConfigEntry, install_id: str
    ) -> None:
        settings = entry_settings(entry)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=int(settings[CONF_SCAN_INTERVAL])),
        )
        self.area: str = settings[CONF_AREA]
        self.places: list[str] = list(settings[CONF_PLACES])
        self.disciplines: list[str] = list(settings[CONF_DISCIPLINES])
        self.map_minutes: int = int(settings[CONF_MAP_MINUTES])
        self.session = async_get_clientsession(hass)
        self.client = GrunnAlertClient(self.session, install_id)
        self.live_connected = False
        self._last_fetch = 0.0
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._recent_texts: dict[str, float] = {}
        self._event_times: list[float] = []
        self._seeded = False
        self._live_task: asyncio.Task | None = None

    # ---- polling -------------------------------------------------------

    async def _async_update_data(self) -> list[dict[str, Any]]:
        # Live werkt: dan hoeven we de server niet elke paar minuten te
        # bevragen. Valt live weg, dan pakt de normale interval het meteen op.
        if (
            self._seeded
            and self.live_connected
            and time.monotonic() - self._last_fetch < LIVE_POLL_INTERVAL_S
        ):
            return self.data
        try:
            fetched = await self.client.async_get_alerts(
                self.area, self.places, self.disciplines
            )
        except GrunnAlertApiError as err:
            if self._seeded and self.live_connected:
                # Live werkt nog, dus de sensoren niet onbeschikbaar maken.
                _LOGGER.debug("Vangnet-fetch mislukt, live werkt nog: %s", err)
                return self.data
            raise UpdateFailed(str(err)) from err
        self._last_fetch = time.monotonic()

        if not self._seeded:
            # Eerste keer: alles wat er al was geldt als gezien, geen events.
            for alert in reversed(fetched):
                self._mark_seen(alert["id"])
            self._seeded = True
            return fetched

        for alert in sorted(fetched, key=lambda item: item["received_ms"]):
            if self._mark_seen(alert["id"]):
                self._fire(alert)
        return self._merge(fetched)

    # ---- live websocket ------------------------------------------------

    @callback
    def async_start_live(self) -> None:
        """Start de live verbinding op de achtergrond."""
        if self._live_task is None:
            self._live_task = self.config_entry.async_create_background_task(
                self.hass, self._live_loop(), f"{DOMAIN}_live"
            )

    async def async_stop_live(self) -> None:
        if self._live_task is not None:
            self._live_task.cancel()
            try:
                await self._live_task
            except asyncio.CancelledError:
                pass
            self._live_task = None
        self.live_connected = False

    async def _live_loop(self) -> None:
        delay = LIVE_RECONNECT_MIN
        first = True
        while True:
            started = time.monotonic()
            try:
                async with self.session.ws_connect(
                    f"{LIVE_URL}?filter=groningen",
                    headers={"User-Agent": USER_AGENT},
                    heartbeat=None,
                    max_msg_size=MAX_LIVE_MESSAGE_BYTES,
                    timeout=aiohttp.ClientWSTimeout(ws_close=10),
                ) as socket:
                    self._set_live(True)
                    _LOGGER.debug("Live verbonden met GrunnAlert")
                    if not first:
                        # Gemiste meldingen ophalen, verspreid over de tijd
                        # zodat niet alle installaties tegelijk aankloppen.
                        self.config_entry.async_create_background_task(
                            self.hass,
                            self._catch_up(random.uniform(0, 30)),
                            f"{DOMAIN}_catch_up",
                        )
                    first = False
                    await self._read_socket(socket)
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as err:
                _LOGGER.debug(
                    "Live verbinding met GrunnAlert verbroken: %s",
                    str(err) or type(err).__name__,
                )
            except Exception:  # noqa: BLE001
                # Wat er ook misgaat, de live taak mag nooit stoppen.
                _LOGGER.exception("Onverwachte fout in de live verbinding met GrunnAlert")
            finally:
                try:
                    self._set_live(False)
                except Exception:  # noqa: BLE001
                    _LOGGER.exception("Fout bij bijwerken van de GrunnAlert-status")
            if time.monotonic() - started > 120:
                delay = LIVE_RECONNECT_MIN
            # Willekeurige spreiding, zodat na een storing niet iedereen
            # op exact hetzelfde moment opnieuw verbindt.
            await asyncio.sleep(delay * random.uniform(0.5, 1.5))
            delay = min(delay * 2, LIVE_RECONNECT_MAX)

    async def _catch_up(self, delay: float) -> None:
        await asyncio.sleep(delay)
        # Forceer een echte fetch, ook al is live inmiddels weer verbonden.
        self._last_fetch = 0.0
        await self.async_request_refresh()

    async def _read_socket(self, socket: aiohttp.ClientWebSocketResponse) -> None:
        interval = LIVE_PING_INTERVAL.total_seconds()
        while True:
            try:
                message = await socket.receive(timeout=interval)
            except asyncio.TimeoutError:
                # De server antwoordt op "ping" met {"type": "pong"}.
                await socket.send_str("ping")
                message = await socket.receive(timeout=interval)
            if message.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.ERROR,
            ):
                _LOGGER.debug(
                    "GrunnAlert sloot de live verbinding (%s, code %s)",
                    message.type.name,
                    socket.close_code,
                )
                return
            if message.type == aiohttp.WSMsgType.TEXT:
                self._handle_live_message(message.data)

    @callback
    def _handle_live_message(self, data: str) -> None:
        try:
            payload = json.loads(data)
        except (ValueError, RecursionError):
            return
        if not isinstance(payload, dict) or payload.get("type") != "alert":
            return
        alert = normalize_alert(payload.get("alert"))
        if alert is None or not matches_selection(
            alert, self.area, self.places, self.disciplines
        ):
            return
        if not self._mark_seen(alert["id"]):
            return
        self._fire(alert)
        self.async_set_updated_data(self._merge([alert]))

    @callback
    def _set_live(self, connected: bool) -> None:
        if self.live_connected != connected:
            self.live_connected = connected
            self.async_update_listeners()

    # ---- hulpjes -------------------------------------------------------

    def _mark_seen(self, alert_id: str) -> bool:
        """True als deze melding nieuw is."""
        if alert_id in self._seen:
            return False
        self._seen[alert_id] = None
        while len(self._seen) > SEEN_LIMIT:
            self._seen.popitem(last=False)
        return True

    def _merge(self, incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Nieuwe gegevens winnen (bijv. eenheden die later bekend worden)."""
        by_id = {alert["id"]: alert for alert in self.data or []}
        for alert in incoming:
            by_id[alert["id"]] = {**by_id.get(alert["id"], {}), **alert}
        merged = sorted(by_id.values(), key=lambda a: a["received_ms"], reverse=True)
        return merged[:FETCH_LIMIT]

    @callback
    def _fire(self, alert: dict[str, Any]) -> None:
        now_ms = time.time() * 1000
        if now_ms - alert["received_ms"] > MAX_EVENT_AGE_MS:
            return

        self._recent_texts = {
            text: seen
            for text, seen in self._recent_texts.items()
            if now_ms - seen < DUPLICATE_WINDOW_MS
        }
        key = dedupe_key(alert["raw_text"])
        if key in self._recent_texts:
            return
        self._recent_texts[key] = now_ms

        self._event_times = [t for t in self._event_times if now_ms - t < 60_000]
        if len(self._event_times) >= MAX_EVENTS_PER_MINUTE:
            _LOGGER.warning("Te veel GrunnAlert-meldingen tegelijk, event overgeslagen")
            return
        self._event_times.append(now_ms)

        self.hass.bus.async_fire(
            EVENT_ALERT, {**alert, "config_entry_id": self.config_entry.entry_id}
        )
