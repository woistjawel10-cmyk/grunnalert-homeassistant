"""Sensoren voor GrunnAlert."""

from __future__ import annotations

from datetime import datetime
import time
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DISCIPLINE_ICONS, PLAY_STORE_URL, PROMO_TEXT, WEBSITE_URL
from .coordinator import GrunnAlertConfigEntry, GrunnAlertCoordinator
from .entity import GrunnAlertEntity

MAX_STATE_LENGTH = 255
RECENT_LIST_LENGTH = 10


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrunnAlertConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            LatestAlertSensor(coordinator),
            LatestAlertTimeSensor(coordinator),
            AlertsLastHourSensor(coordinator),
            ConnectionSensor(coordinator),
        ]
    )


def _latest(coordinator: GrunnAlertCoordinator) -> dict[str, Any] | None:
    return coordinator.data[0] if coordinator.data else None


class LatestAlertSensor(GrunnAlertEntity, SensorEntity):
    """Tekst van de laatste melding, met alle details als attributen."""

    def __init__(self, coordinator: GrunnAlertCoordinator) -> None:
        super().__init__(coordinator, "latest_alert")

    @property
    def native_value(self) -> str | None:
        alert = _latest(self.coordinator)
        if alert is None:
            return None
        return alert["message"][:MAX_STATE_LENGTH]

    @property
    def icon(self) -> str:
        alert = _latest(self.coordinator)
        return DISCIPLINE_ICONS[alert["discipline"]] if alert else "mdi:alarm-light-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        alert = _latest(self.coordinator)
        attributes: dict[str, Any] = {}
        if alert:
            attributes.update(
                {
                    key: alert[key]
                    for key in (
                        "message",
                        "discipline",
                        "discipline_label",
                        "priority",
                        "city",
                        "street",
                        "location",
                        "latitude",
                        "longitude",
                        "maps_url",
                        "units",
                        "received_at",
                        "id",
                    )
                }
            )
        attributes["recent"] = [
            {
                "message": item["message"],
                "location": item["location"],
                "discipline": item["discipline_label"],
                "received_at": item["received_at"],
            }
            for item in (self.coordinator.data or [])[:RECENT_LIST_LENGTH]
        ]
        attributes["source"] = "GrunnAlert"
        attributes["source_url"] = WEBSITE_URL
        attributes["app_url"] = PLAY_STORE_URL
        attributes["app_promo"] = PROMO_TEXT
        return attributes


class LatestAlertTimeSensor(GrunnAlertEntity, SensorEntity):
    """Tijdstip van de laatste melding."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: GrunnAlertCoordinator) -> None:
        super().__init__(coordinator, "latest_alert_time")

    @property
    def native_value(self) -> datetime | None:
        alert = _latest(self.coordinator)
        return datetime.fromisoformat(alert["received_at"]) if alert else None


class AlertsLastHourSensor(GrunnAlertEntity, SensorEntity):
    """Aantal meldingen in het afgelopen uur binnen je filter."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator: GrunnAlertCoordinator) -> None:
        super().__init__(coordinator, "alerts_last_hour")

    @property
    def native_value(self) -> int:
        cutoff = time.time() * 1000 - 3600 * 1000
        return sum(1 for a in self.coordinator.data or [] if a["received_ms"] >= cutoff)


class ConnectionSensor(GrunnAlertEntity, SensorEntity):
    """Laat zien of de live verbinding met GrunnAlert openstaat."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["live", "polling"]
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GrunnAlertCoordinator) -> None:
        super().__init__(coordinator, "connection")

    @property
    def available(self) -> bool:
        # Ook als een vangnet-fetch mislukt willen we zien of live nog werkt.
        return True

    @property
    def native_value(self) -> str:
        return "live" if self.coordinator.live_connected else "polling"

    @property
    def icon(self) -> str:
        return "mdi:access-point-network" if self.coordinator.live_connected else "mdi:sync"
