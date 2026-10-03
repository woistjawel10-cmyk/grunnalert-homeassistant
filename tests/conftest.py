"""Gedeelde fixtures."""

from unittest.mock import patch

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def no_live_socket():
    """Geen echte WebSocket naar grunnalert.nl tijdens tests."""
    with patch(
        "custom_components.grunnalert.coordinator.GrunnAlertCoordinator.async_start_live"
    ):
        yield
