"""Instelscherm voor GrunnAlert."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import GrunnAlertApiError, GrunnAlertClient
from .const import (
    AREA_GRONINGEN,
    AREA_LABELS,
    AREA_PLACES,
    AREAS,
    CONF_AREA,
    CONF_DISCIPLINES,
    CONF_MAP_MINUTES,
    CONF_PLACES,
    CONF_SCAN_INTERVAL,
    DEFAULT_MAP_MINUTES,
    DEFAULT_SCAN_INTERVAL,
    DISCIPLINES,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    NAME,
)

MAX_PLACES = 50


def _area_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=AREAS, mode=SelectSelectorMode.LIST, translation_key=CONF_AREA
        )
    )


def _discipline_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=DISCIPLINES,
            multiple=True,
            mode=SelectSelectorMode.LIST,
            translation_key=CONF_DISCIPLINES,
        )
    )


def _places_selector(places: list[str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=places, multiple=True, mode=SelectSelectorMode.DROPDOWN, sort=True
        )
    )


def entry_title(area: str, places: list[str]) -> str:
    if area == AREA_PLACES:
        shown = ", ".join(places[:3]) + (" en meer" if len(places) > 3 else "")
        return f"{NAME} ({shown})"
    return f"{NAME} ({AREA_LABELS[AREA_GRONINGEN]})"


async def _async_fetch_places(flow: ConfigFlow | OptionsFlow) -> list[str]:
    client = GrunnAlertClient(async_get_clientsession(flow.hass))
    return await client.async_get_places()


def _validate_places(selected: list[str], known: list[str]) -> str | None:
    if not selected:
        return "no_places"
    if len(selected) > MAX_PLACES:
        return "too_many_places"
    if any(place not in known for place in selected):
        return "unknown_place"
    return None


class GrunnAlertConfigFlow(ConfigFlow, domain=DOMAIN):
    """Toevoegen van GrunnAlert."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._places: list[str] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> GrunnAlertOptionsFlow:
        return GrunnAlertOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_DISCIPLINES]:
                errors["base"] = "no_disciplines"
            else:
                try:
                    self._places = await _async_fetch_places(self)
                except GrunnAlertApiError:
                    errors["base"] = "cannot_connect"
                else:
                    self._data = {
                        CONF_AREA: user_input[CONF_AREA],
                        CONF_DISCIPLINES: user_input[CONF_DISCIPLINES],
                        CONF_PLACES: [],
                    }
                    if user_input[CONF_AREA] == AREA_PLACES:
                        return await self.async_step_places()
                    return self._async_finish()

        schema = vol.Schema(
            {
                vol.Required(CONF_AREA, default=AREA_GRONINGEN): _area_selector(),
                vol.Required(
                    CONF_DISCIPLINES, default=list(DISCIPLINES)
                ): _discipline_selector(),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_places(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            error = _validate_places(user_input.get(CONF_PLACES, []), self._places)
            if error:
                errors["base"] = error
            else:
                self._data[CONF_PLACES] = user_input[CONF_PLACES]
                return self._async_finish()

        schema = vol.Schema(
            {vol.Required(CONF_PLACES, default=[]): _places_selector(self._places)}
        )
        return self.async_show_form(step_id="places", data_schema=schema, errors=errors)

    @callback
    def _async_finish(self) -> ConfigFlowResult:
        from . import async_show_welcome

        async_show_welcome(self.hass)
        return self.async_create_entry(
            title=entry_title(self._data[CONF_AREA], self._data[CONF_PLACES]),
            data=self._data,
        )


class GrunnAlertOptionsFlow(OptionsFlow):
    """Filters en verversing achteraf aanpassen."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}
        self._places: list[str] = []

    def _current(self, key: str, default: Any) -> Any:
        return self.config_entry.options.get(
            key, self.config_entry.data.get(key, default)
        )

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_DISCIPLINES]:
                errors["base"] = "no_disciplines"
            else:
                try:
                    self._places = await _async_fetch_places(self)
                except GrunnAlertApiError:
                    errors["base"] = "cannot_connect"
                else:
                    self._options = {
                        **user_input,
                        CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                        CONF_MAP_MINUTES: int(user_input[CONF_MAP_MINUTES]),
                        CONF_PLACES: [],
                    }
                    if user_input[CONF_AREA] == AREA_PLACES:
                        return await self.async_step_places()
                    return self._async_save()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_AREA, default=self._current(CONF_AREA, AREA_GRONINGEN)
                ): _area_selector(),
                vol.Required(
                    CONF_DISCIPLINES,
                    default=self._current(CONF_DISCIPLINES, list(DISCIPLINES)),
                ): _discipline_selector(),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self._current(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=MIN_SCAN_INTERVAL,
                        max=MAX_SCAN_INTERVAL,
                        step=30,
                        unit_of_measurement="s",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_MAP_MINUTES,
                    default=self._current(CONF_MAP_MINUTES, DEFAULT_MAP_MINUTES),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=0, max=720, step=5, unit_of_measurement="min",
                        mode=NumberSelectorMode.BOX,
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)

    @callback
    def _async_save(self) -> ConfigFlowResult:
        # De titel werkt __init__ bij tijdens het herladen.
        return self.async_create_entry(data=self._options)

    async def async_step_places(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            error = _validate_places(user_input.get(CONF_PLACES, []), self._places)
            if error:
                errors["base"] = error
            else:
                self._options[CONF_PLACES] = user_input[CONF_PLACES]
                return self._async_save()

        current = [p for p in self._current(CONF_PLACES, []) if p in self._places]
        schema = vol.Schema(
            {vol.Required(CONF_PLACES, default=current): _places_selector(self._places)}
        )
        return self.async_show_form(step_id="places", data_schema=schema, errors=errors)
