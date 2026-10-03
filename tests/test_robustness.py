"""Tests voor de grenzen en randgevallen uit de securityreview."""

from __future__ import annotations

import json

import pytest
from pytest_homeassistant_custom_component.common import async_capture_events

from homeassistant.core import HomeAssistant

from custom_components.grunnalert.api import (
    MAX_RESPONSE_BYTES,
    GrunnAlertApiError,
    GrunnAlertClient,
)
from custom_components.grunnalert.const import EVENT_ALERT

from .test_grunnalert import ALERTS_URL, feed, live, raw_alert, setup_entry


class _Content:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        for chunk in self._chunks:
            yield chunk


class _Response:
    def __init__(self, chunks: list[bytes], length: int | None = None) -> None:
        self.status = 200
        self.content = _Content(chunks)
        self.content_length = length

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _Session:
    def __init__(self, response: _Response) -> None:
        self._response = response

    def get(self, *args, **kwargs):
        return self._response


def _split(data: bytes, size: int) -> list[bytes]:
    return [data[i : i + size] for i in range(0, len(data), size)]


async def test_response_arriving_in_pieces_is_read_completely():
    body = json.dumps(feed(*[raw_alert(f"id{i}") for i in range(100)])).encode()
    assert len(body) > 30_000
    client = GrunnAlertClient(_Session(_Response(_split(body, 1000))))
    alerts = await client.async_get_alerts("groningen", [], ["fire"])
    assert len(alerts) == 25


async def test_too_large_response_is_refused():
    big = [b"x" * 100_000] * 6
    client = GrunnAlertClient(_Session(_Response(big)))
    with pytest.raises(GrunnAlertApiError):
        await client.async_get_alerts("groningen", [], ["fire"])
    client = GrunnAlertClient(_Session(_Response([b"{}"], MAX_RESPONSE_BYTES + 1)))
    with pytest.raises(GrunnAlertApiError):
        await client.async_get_alerts("groningen", [], ["fire"])


async def test_no_polling_while_live(hass: HomeAssistant, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock, [])
    coordinator = entry.runtime_data
    calls = aioclient_mock.call_count
    coordinator._set_live(True)
    await coordinator.async_refresh()
    assert aioclient_mock.call_count == calls
    coordinator._set_live(False)
    await coordinator.async_refresh()
    assert aioclient_mock.call_count == calls + 1


async def test_different_rides_with_same_text_both_fire(hass: HomeAssistant, aioclient_mock):
    events = async_capture_events(hass, EVENT_ALERT)
    entry = await setup_entry(hass, aioclient_mock, [])
    coordinator = entry.runtime_data
    base = "0400272 23:17:09 02-10-26 FLEX-A  GROUP  1600  A2 Ambulancerit UMCG"
    coordinator._handle_live_message(live(raw_alert("r1", minutes_ago=0, raw_text=f"{base} 011851")))
    coordinator._handle_live_message(live(raw_alert("r2", minutes_ago=0, raw_text=f"{base} 011999")))
    # Zelfde rit via ALPHA: wordt wel samengevoegd.
    alpha = "0400272 23:17:10 02-10-26 FLEX-A  ALPHA  1600  A2 Ambulancerit UMCG 011851"
    coordinator._handle_live_message(live(raw_alert("r3", minutes_ago=0, raw_text=alpha)))
    await hass.async_block_till_done()
    assert [e.data["id"] for e in events] == ["r1", "r2"]


async def test_alerts_url_constant_matches_client():
    assert ALERTS_URL == "https://grunnalert.nl/v1/alerts"


async def test_failed_poll_while_live_keeps_entities(hass: HomeAssistant, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock, [raw_alert("k1")])
    coordinator = entry.runtime_data
    coordinator._set_live(True)
    coordinator._last_fetch = 0.0
    aioclient_mock.clear_requests()
    aioclient_mock.get(ALERTS_URL, status=500)
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert coordinator.data[0]["id"] == "k1"
