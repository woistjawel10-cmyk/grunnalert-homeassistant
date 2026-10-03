"""Tests voor de GrunnAlert-integratie."""

from __future__ import annotations

import json
import time

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.grunnalert.api import (
    clean_message,
    matches_selection,
    normalize_alert,
)
from custom_components.grunnalert.const import (
    CONF_AREA,
    CONF_DISCIPLINES,
    CONF_PLACES,
    DOMAIN,
    EVENT_ALERT,
    INSTALL_HEADER,
)

ALERTS_URL = "https://grunnalert.nl/v1/alerts"
PLACES_URL = "https://grunnalert.nl/v1/filter-options"
PLACES = ["Groningen", "Hoogezand", "Ten Boer", "Ter Apel"]
RAW = (
    "0400272 23:17:09 02-10-26 FLEX-A  GROUP  1600  P 2 BNN-01 Brandgerucht "
    "Eyssoniusplein Groningen 011831"
)
CLEAN = "P 2 BNN-01 Brandgerucht Eyssoniusplein Groningen"
ALL = ["fire", "ambulance", "police", "other"]


def raw_alert(alert_id: str, minutes_ago: float = 1, **extra):
    base = {
        "id": alert_id,
        "raw_text": RAW,
        "priority": 2,
        "region": "Groningen",
        "city": "Groningen",
        "discipline": "fire",
        "received_at": int((time.time() - minutes_ago * 60) * 1000),
        "created_at": int(time.time() * 1000),
        "street": "Eyssoniusplein",
        "lat": 53.2268,
        "lon": 6.5664,
        "geocode_confidence": "weg",
        "targets": [{"capcode": "0400272", "label": "Groningen-Sontweg - TS-745"}],
    }
    base.update(extra)
    return base


def feed(*alerts):
    return {"ok": True, "alerts": list(alerts), "filter": "groningen"}


def live(alert) -> str:
    return json.dumps({"type": "alert", "alert": alert})


def test_clean_message():
    assert clean_message(RAW) == CLEAN
    assert clean_message("iets zonder kop") == "iets zonder kop"


def test_clean_message_strips_multiple_trailers():
    raw = "0400272 23:17:09 02-10-26 FLEX-A  GROUP  1600  A1 Rit 01-18-817 011851 013593 011832"
    assert clean_message(raw) == "A1 Rit 01-18-817"


def test_normalize_rejects_dangerous_values():
    for bad_time in (float("nan"), float("inf"), "nan", "Infinity", 1e20, -5, 0):
        assert normalize_alert(raw_alert("t", received_at=bad_time)) is None
    assert normalize_alert(raw_alert("x" * 65)) is None
    huge = normalize_alert(
        raw_alert(
            "h",
            raw_text="A" * 10_000,
            city="C" * 5000,
            targets=[{"label": "U" * 500}] * 500,
            lat=float("nan"),
        )
    )
    assert len(huge["raw_text"]) <= 500 and len(huge["city"]) <= 100
    assert len(huge["units"]) == 30 and all(len(u) <= 100 for u in huge["units"])
    assert huge["latitude"] is None
    assert normalize_alert(raw_alert("o", lat=200, lon=6.5))["latitude"] is None


def test_normalize_rejects_garbage():
    assert normalize_alert(None) is None
    assert normalize_alert({"id": "x"}) is None
    assert normalize_alert({"id": "x", "raw_text": "t", "received_at": "nee"}) is None
    alert = normalize_alert(raw_alert("a", discipline="<script>", lat="abc"))
    assert alert["discipline"] == "other"
    assert alert["latitude"] is None and alert["street"] == ""
    assert alert["source"] == "GrunnAlert"


def test_matches_selection():
    alert = normalize_alert(raw_alert("a", city="Ter Apel", region="Veendam & Omstreken"))
    assert matches_selection(alert, "groningen", [], ["fire"])
    assert not matches_selection(alert, "groningen", [], ["police"])
    assert matches_selection(alert, "places", ["ter apel"], ["fire"])
    assert not matches_selection(alert, "places", ["Hoogezand"], ["fire"])
    landelijk = normalize_alert(raw_alert("b", region="Onbekend", city="Utrecht"))
    assert not matches_selection(landelijk, "groningen", [], ["fire"])


async def test_config_flow_province(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(PLACES_URL, json={"ok": True, "places": PLACES})
    aioclient_mock.get(ALERTS_URL, json=feed())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AREA: "groningen", CONF_DISCIPLINES: ["fire", "ambulance"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "GrunnAlert (provincie Groningen)"
    assert result["data"] == {
        CONF_AREA: "groningen",
        CONF_DISCIPLINES: ["fire", "ambulance"],
        CONF_PLACES: [],
    }
    await hass.async_block_till_done()


async def test_config_flow_places_and_errors(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(PLACES_URL, json={"ok": True, "places": PLACES})
    aioclient_mock.get(ALERTS_URL, json=feed())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AREA: "places", CONF_DISCIPLINES: []}
    )
    assert result["errors"] == {"base": "no_disciplines"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AREA: "places", CONF_DISCIPLINES: ["fire"]}
    )
    assert result["step_id"] == "places"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PLACES: []}
    )
    assert result["errors"] == {"base": "no_places"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PLACES: ["Ten Boer", "Ter Apel"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "GrunnAlert (Ten Boer, Ter Apel)"
    await hass.async_block_till_done()


async def test_config_flow_cannot_connect(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(PLACES_URL, status=500)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_AREA: "groningen", CONF_DISCIPLINES: ["fire"]}
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def setup_entry(hass, aioclient_mock, alerts, **data):
    aioclient_mock.get(ALERTS_URL, json=feed(*alerts))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GrunnAlert (provincie Groningen)",
        data={CONF_AREA: "groningen", CONF_DISCIPLINES: ALL, CONF_PLACES: [], **data},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities_events_and_live(hass: HomeAssistant, aioclient_mock):
    events = async_capture_events(hass, EVENT_ALERT)
    entry = await setup_entry(hass, aioclient_mock, [raw_alert("a1")])
    latest = "sensor.grunnalert_provincie_groningen_latest_alert"
    state = hass.states.get(latest)
    assert state is not None, [s.entity_id for s in hass.states.async_all()]
    assert state.state == CLEAN
    assert state.attributes["source"] == "GrunnAlert"
    assert "GrunnAlert" in state.attributes["attribution"]
    assert state.attributes["units"] == ["Groningen-Sontweg - TS-745"]
    assert "play.google.com" in state.attributes["app_url"]
    assert (
        hass.states.get("sensor.grunnalert_provincie_groningen_alerts_last_hour").state
        == "1"
    )
    geo = hass.states.async_all("geo_location")
    assert len(geo) == 1 and geo[0].attributes["source"] == "grunnalert"
    # Backlog bij opstarten geeft geen events.
    assert events == []

    # Anonieme installatie-ID gaat mee als header.
    headers = aioclient_mock.mock_calls[-1][3]
    assert len(headers[INSTALL_HEADER]) == 64

    # Nieuwe melding via polling: precies een event.
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        ALERTS_URL,
        json=feed(raw_alert("a2", minutes_ago=0.1, discipline="ambulance"), raw_alert("a1")),
    )
    coordinator = entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert [e.data["id"] for e in events] == ["a2"]
    assert events[0].data["discipline_label"] == "Ambulance"
    assert events[0].data["source_url"] == "https://grunnalert.nl"

    # Dezelfde melding nog eens live: geen dubbel event.
    coordinator._handle_live_message(live(raw_alert("a2", minutes_ago=0.1)))
    await hass.async_block_till_done()
    assert len(events) == 1

    # Nieuwe live melding: direct event en sensor bijgewerkt.
    coordinator._handle_live_message(
        live(raw_alert("a3", minutes_ago=0, raw_text="P 1 Woningbrand Hoofdstraat Hoogezand"))
    )
    await hass.async_block_till_done()
    assert len(events) == 2
    assert hass.states.get(latest).state == "P 1 Woningbrand Hoofdstraat Hoogezand"
    assert len(hass.states.async_all("geo_location")) == 3

    # Rommel en landelijke meldingen worden genegeerd.
    coordinator._handle_live_message("geen json")
    coordinator._handle_live_message(json.dumps({"type": "pong"}))
    coordinator._handle_live_message(json.dumps([1, 2]))
    coordinator._handle_live_message(live(raw_alert("x9", region="Onbekend")))
    coordinator._handle_live_message(live("kapot"))
    await hass.async_block_till_done()
    assert len(events) == 2

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_old_alert_found_late_is_not_fired(hass: HomeAssistant, aioclient_mock):
    events = async_capture_events(hass, EVENT_ALERT)
    entry = await setup_entry(hass, aioclient_mock, [])
    aioclient_mock.clear_requests()
    aioclient_mock.get(ALERTS_URL, json=feed(raw_alert("old", minutes_ago=120)))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert events == []


async def test_places_filter_live(hass: HomeAssistant, aioclient_mock):
    events = async_capture_events(hass, EVENT_ALERT)
    entry = await setup_entry(
        hass,
        aioclient_mock,
        [raw_alert("g0"), raw_alert("t0", city="Ten Boer", raw_text="P 2 Ten Boer test")],
        area="places",
        places=["Ten Boer"],
    )
    # Privacy: de server krijgt nooit te horen welke plaatsen iemand volgt.
    request_url = aioclient_mock.mock_calls[-1][1]
    assert request_url.query["filter"] == "groningen"
    assert "places" not in request_url.query
    assert [a["id"] for a in entry.runtime_data.data] == ["t0"]
    coordinator = entry.runtime_data
    coordinator._handle_live_message(live(raw_alert("g1", minutes_ago=0)))
    coordinator._handle_live_message(live(raw_alert("t1", minutes_ago=0, city="Ten Boer")))
    await hass.async_block_till_done()
    assert [e.data["id"] for e in events] == ["t1"]


async def test_options_flow(hass: HomeAssistant, aioclient_mock):
    entry = await setup_entry(hass, aioclient_mock, [])
    aioclient_mock.get(PLACES_URL, json={"ok": True, "places": PLACES})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_AREA: "places", CONF_DISCIPLINES: ["police"], "scan_interval": 300, "map_minutes": 0},
    )
    assert result["step_id"] == "places"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_PLACES: ["Hoogezand"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert coordinator.area == "places" and coordinator.places == ["Hoogezand"]
    assert coordinator.disciplines == ["police"] and coordinator.map_minutes == 0
    assert entry.title == "GrunnAlert (Hoogezand)"


async def test_setup_retries_when_offline(hass: HomeAssistant, aioclient_mock):
    aioclient_mock.get(ALERTS_URL, status=503)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_AREA: "groningen", CONF_DISCIPLINES: ["fire"], CONF_PLACES: []},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is config_entries.ConfigEntryState.SETUP_RETRY


async def test_live_survives_bad_messages_and_dedupes(hass: HomeAssistant, aioclient_mock):
    events = async_capture_events(hass, EVENT_ALERT)
    entry = await setup_entry(hass, aioclient_mock, [])
    coordinator = entry.runtime_data
    for bad in (float("nan"), 1e20, "Infinity"):
        coordinator._handle_live_message(live(raw_alert(f"bad{bad}", received_at=bad)))
    coordinator._handle_live_message("[" * 100_000)
    # GROUP en ALPHA van dezelfde melding: twee id's, een event.
    coordinator._handle_live_message(live(raw_alert("grp", minutes_ago=0)))
    coordinator._handle_live_message(live(raw_alert("alp", minutes_ago=0)))
    await hass.async_block_till_done()
    assert [e.data["id"] for e in events] == ["grp"]


async def test_event_flood_is_capped(hass: HomeAssistant, aioclient_mock):
    events = async_capture_events(hass, EVENT_ALERT)
    entry = await setup_entry(hass, aioclient_mock, [])
    coordinator = entry.runtime_data
    for index in range(100):
        coordinator._handle_live_message(
            live(raw_alert(f"f{index}", minutes_ago=0, raw_text=f"P 1 melding {index}"))
        )
    await hass.async_block_till_done()
    assert len(events) == 30
