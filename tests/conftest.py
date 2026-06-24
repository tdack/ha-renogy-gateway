"""Fixtures for Renogy Gateway tests."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.renogy_gateway.api.models import (
    FieldSpec,
    RenogyDevice,
    TokenSet,
)
from custom_components.renogy_gateway.const import (
    CONF_DEVICE_UUID,
    CONF_GATEWAY_ID,
    CONF_GATEWAY_NAME,
    CONF_REFRESH_TOKEN,
    CONF_RTM_DID,
    CONF_RTM_TOKEN,
    DOMAIN,
)
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_EMAIL, CONF_PASSWORD

from pytest_homeassistant_custom_component.common import MockConfigEntry

MOCK_EMAIL = "test@example.com"
MOCK_PASSWORD = "password123"
MOCK_GATEWAY_ID = "227162568538456065"
MOCK_GATEWAY_NAME = "My Renogy Gateway"
MOCK_DEVICE_UUID = "aaaabbbb-cccc-dddd-eeee-ffffgggghhhh"

MOCK_TOKENS = TokenSet(
    access_token="eyJhbGciOiJIUzUxMiJ9.mock_access",
    refresh_token="mock_refresh_token",
    rtm_token="mock_rtm_token",
    rtm_did="257470607149498369",
    device_uuid=MOCK_DEVICE_UUID,
)

# Sensor field (read-only float)
FIELD_SOC = FieldSpec(
    sp="4838812556313808772/shunt.main_battery_soc",
    name="main_battery_soc",
    field_type=3,
    ops=6,  # read + subscribe
    unit="%",
    precision=1,
)

# Switch field (writable bool, no ratio sibling)
FIELD_RELAY = FieldSpec(
    sp="4623589794012005944/distribution_box.relay_3.state",
    name="relay_3.state",
    field_type=1,
    ops=7,  # write + read + subscribe
    user_label="Cooling Fan",
)

# Dimmable light state field
FIELD_LIGHT_STATE = FieldSpec(
    sp="4623589794012005944/distribution_box.dc_10a_1.state",
    name="dc_10a_1.state",
    field_type=1,
    ops=7,
    user_label="Bedroom Light",
)

# Dimmable light ratio field (makes the state field a light, not a switch)
FIELD_LIGHT_RATIO = FieldSpec(
    sp="4623589794012005944/distribution_box.dc_10a_1.ratio",
    name="dc_10a_1.ratio",
    field_type=2,
    ops=7,
    min_value=0,
    max_value=100,
    user_label="Bedroom Light",
)

# Number field (writable float with bounds)
FIELD_CHARGE_VOLTAGE = FieldSpec(
    sp="4774953285866299397/charger_params.boost_voltage",
    name="boost_voltage",
    field_type=3,
    ops=7,
    unit="V",
    min_value=12.0,
    max_value=15.0,
    precision=1,
)

# Select field (writable enum)
FIELD_SOC_RULE = FieldSpec(
    sp="4623589794012005944/gwmConfig.socRule",
    name="socRule",
    field_type=2,
    ops=7,
    options=[{"key": 0, "value": "Low (20%)"}, {"key": 1, "value": "Medium (50%)"}],
)

# Binary sensor field (read-only bool)
FIELD_ONLINE = FieldSpec(
    sp="4623589794012005944/thing.online",
    name="online",
    field_type=1,
    ops=6,  # read + subscribe only
)

MOCK_SHUNT_DEVICE = RenogyDevice(
    did_str="4838812556313808772",
    pid="SmartShunt300",
    sku="RSHST-B02P300-G1",
    name="Shunt 300A",
    online=True,
    fields=[FIELD_SOC],
)

MOCK_BOX_DEVICE = RenogyDevice(
    did_str="4623589794012005944",
    pid="smartDistributionBox",
    sku="RSHCB-C02P-G2",
    name="Smart Distribution Box",
    online=True,
    fields=[
        FIELD_RELAY,
        FIELD_LIGHT_STATE,
        FIELD_LIGHT_RATIO,
        FIELD_SOC_RULE,
        FIELD_ONLINE,
    ],
)

MOCK_CHARGER_DEVICE = RenogyDevice(
    did_str="4774953285866299397",
    pid="000E002E",
    sku="RCC60REGO-G2",
    name="PV Charger",
    online=True,
    fields=[FIELD_CHARGE_VOLTAGE],
)

CONFIG_ENTRY_DATA = {
    CONF_EMAIL: MOCK_EMAIL,
    CONF_PASSWORD: MOCK_PASSWORD,
    CONF_GATEWAY_ID: MOCK_GATEWAY_ID,
    CONF_GATEWAY_NAME: MOCK_GATEWAY_NAME,
    CONF_ACCESS_TOKEN: MOCK_TOKENS.access_token,
    CONF_REFRESH_TOKEN: MOCK_TOKENS.refresh_token,
    CONF_RTM_TOKEN: MOCK_TOKENS.rtm_token,
    CONF_RTM_DID: MOCK_TOKENS.rtm_did,
    CONF_DEVICE_UUID: MOCK_TOKENS.device_uuid,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow Home Assistant to load this custom integration during tests."""


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Return a mock RenogyCoordinator with pre-populated devices."""
    coord = MagicMock()
    coord.devices = {
        MOCK_SHUNT_DEVICE.did_str: MOCK_SHUNT_DEVICE,
        MOCK_BOX_DEVICE.did_str: MOCK_BOX_DEVICE,
        MOCK_CHARGER_DEVICE.did_str: MOCK_CHARGER_DEVICE,
    }
    coord.async_write = AsyncMock()
    coord.get_value = MagicMock(return_value=None)
    coord.register_telemetry_callback = MagicMock()
    coord.unregister_telemetry_callback = MagicMock()
    coord.register_availability_callback = MagicMock()
    coord.unregister_availability_callback = MagicMock()
    return coord


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Patch async_setup_entry to prevent real integration startup."""
    with patch(
        "custom_components.renogy_gateway.async_setup_entry",
        return_value=True,
    ) as mock_setup:
        yield mock_setup


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=MOCK_GATEWAY_NAME,
        data=CONFIG_ENTRY_DATA,
        unique_id=f"{MOCK_EMAIL}_{MOCK_GATEWAY_ID}",
    )
