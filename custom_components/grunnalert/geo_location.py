"""Recente GrunnAlert-meldingen als punten op de Home Assistant-kaart."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.geo_location import GeolocationEvent
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.location import distance

from .const import ATTRIBUTION, DISCIPLINE_ICONS, DOMAIN, WEBSITE_URL
from .coordinator import GrunnAlertConfigEntry, GrunnAlertCoordinator

MAX_MARKERS = 25


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrunnAlertConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    markers: dict[str, GrunnAlertMarker] = {}

    @callback
    def _sync() -> None:
        wanted = _wanted_alerts(coordinator)
        for alert_id in list(markers):
            if alert_id not in wanted:
                hass.async_create_task(markers.pop(alert_id).async_remove())
        new = [
            GrunnAlertMarker(coordinator, alert)
            for alert_id, alert in wanted.items()
            if alert_id not in markers
        ]
        for marker in new:
            markers[marker.alert_id] = marker
        for alert_id, marker in markers.items():
            marker.update_alert(wanted[alert_id])
        if new:
            async_add_entities(new)

    _sync()
    entry.async_on_unload(coordinator.async_add_listener(_sync))


def _wanted_alerts(coordinator: GrunnAlertCoordinator) -> dict[str, dict[str, Any]]:
    if coordinator.map_minutes <= 0:
        return {}
    cutoff = time.time() * 1000 - coordinator.map_minutes * 60 * 1000
    wanted = [
        alert
        for alert in coordinator.data or []
        if alert["latitude"] is not None and alert["received_ms"] >= cutoff
    ]
    return {alert["id"]: alert for alert in wanted[:MAX_MARKERS]}


class GrunnAlertMarker(GeolocationEvent):
    """Eén melding op de kaart."""

    _attr_should_poll = False
    _attr_source = DOMAIN
    _attr_attribution = ATTRIBUTION
    _attr_unit_of_measurement = UnitOfLength.KILOMETERS

    def __init__(self, coordinator: GrunnAlertCoordinator, alert: dict[str, Any]) -> None:
        self._coordinator = coordinator
        self.alert_id: str = alert["id"]
        self._alert = alert

    @callback
    def update_alert(self, alert: dict[str, Any]) -> None:
        changed = alert != self._alert
        self._alert = alert
        if changed and self.hass is not None:
            self.async_write_ha_state()

    @property
    def name(self) -> str:
        return f"{self._alert['discipline_label']}: {self._alert['message']}"[:100]

    @property
    def icon(self) -> str:
        return DISCIPLINE_ICONS[self._alert["discipline"]]

    @property
    def latitude(self) -> float | None:
        return self._alert["latitude"]

    @property
    def longitude(self) -> float | None:
        return self._alert["longitude"]

    @property
    def distance(self) -> float | None:
        if self.hass is None or self.latitude is None:
            return None
        meters = distance(
            self.hass.config.latitude,
            self.hass.config.longitude,
            self.latitude,
            self.longitude,
        )
        return round(meters / 1000, 1) if meters is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "message": self._alert["message"],
            "location": self._alert["location"],
            "discipline": self._alert["discipline_label"],
            "priority": self._alert["priority"],
            "units": self._alert["units"],
            "received_at": self._alert["received_at"],
            "maps_url": self._alert["maps_url"],
            # Niet "source" noemen: dat veld gebruikt de kaart om te filteren.
            "provider": "GrunnAlert",
            "provider_url": WEBSITE_URL,
        }
