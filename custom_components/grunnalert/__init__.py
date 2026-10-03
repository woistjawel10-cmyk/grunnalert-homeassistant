"""GrunnAlert: P2000-meldingen uit de provincie Groningen in Home Assistant.

Data van GrunnAlert (https://grunnalert.nl), gemaakt door StarlightFM.
"""

from __future__ import annotations

import hashlib

from homeassistant.components import persistent_notification
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import instance_id

from .const import CONF_AREA, CONF_PLACES, DOMAIN, NAME, PLAY_STORE_URL, WEBSITE_URL
from .coordinator import GrunnAlertConfigEntry, GrunnAlertCoordinator, entry_settings

PLATFORMS: list[Platform] = [Platform.GEO_LOCATION, Platform.SENSOR]


async def _async_install_id(hass: HomeAssistant) -> str:
    """Anonieme ID per Home Assistant-installatie.

    Een hash van de interne instance-ID met een vaste GrunnAlert-prefix, zodat
    hij niet terug te rekenen is naar de echte ID en nergens anders bruikbaar is.
    """
    raw = await instance_id.async_get(hass)
    return hashlib.sha256(f"grunnalert-ha:{raw}".encode()).hexdigest()


async def async_setup_entry(hass: HomeAssistant, entry: GrunnAlertConfigEntry) -> bool:
    from .config_flow import entry_title

    # Titel laten kloppen met de gekozen plaatsen, behalve als iemand de
    # integratie zelf een andere naam heeft gegeven.
    settings = entry_settings(entry)
    title = entry_title(settings[CONF_AREA], settings[CONF_PLACES])
    if entry.title != title and entry.title.startswith(f"{NAME} ("):
        hass.config_entries.async_update_entry(entry, title=title)

    coordinator = GrunnAlertCoordinator(hass, entry, await _async_install_id(hass))
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start_live()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GrunnAlertConfigEntry) -> bool:
    await entry.runtime_data.async_stop_live()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: GrunnAlertConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def async_show_welcome(hass: HomeAssistant) -> None:
    """Welkomstbericht na de eerste installatie."""
    persistent_notification.async_create(
        hass,
        (
            "GrunnAlert is toegevoegd. Je ziet nu live P2000-meldingen uit de "
            "provincie Groningen in Home Assistant.\n\n"
            "**Automatiseren:** gebruik het event `grunnalert_alert` of de "
            "kant-en-klare blueprint.\n\n"
            f"**Ook onderweg op de hoogte?** Download de gratis GrunnAlert-app "
            f"voor Android: [Google Play]({PLAY_STORE_URL})\n\n"
            f"Meer info: [grunnalert.nl]({WEBSITE_URL})"
        ),
        title="Welkom bij GrunnAlert",
        notification_id=f"{DOMAIN}_welcome",
    )
