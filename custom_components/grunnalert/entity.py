"""Gedeelde basis voor GrunnAlert-entiteiten."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, AUTHOR, DOMAIN, NAME, VERSION, WEBSITE_URL
from .coordinator import GrunnAlertCoordinator


def device_info(entry_id: str, title: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name=title,
        manufacturer=f"{NAME} door {AUTHOR}",
        model="P2000-meldingen provincie Groningen",
        sw_version=VERSION,
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=WEBSITE_URL,
    )


class GrunnAlertEntity(CoordinatorEntity[GrunnAlertCoordinator]):
    """Basis met apparaat en bronvermelding."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: GrunnAlertCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = device_info(entry.entry_id, entry.title)
