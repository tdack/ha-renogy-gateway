"""Tests for the Renogy Gateway config flow."""

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.renogy_gateway.api.auth import (
    RenogyAuthError,
    RenogyConnectionError,
)
from custom_components.renogy_gateway.api.models import GatewayInfo
from custom_components.renogy_gateway.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import (
    MOCK_EMAIL,
    MOCK_GATEWAY_ID,
    MOCK_GATEWAY_NAME,
    MOCK_PASSWORD,
    MOCK_TOKENS,
)

SINGLE_GATEWAY = [
    GatewayInfo(did_str=MOCK_GATEWAY_ID, name=MOCK_GATEWAY_NAME, online=True)
]

MULTI_GATEWAYS = [
    GatewayInfo(did_str=MOCK_GATEWAY_ID, name=MOCK_GATEWAY_NAME, online=True),
    GatewayInfo(did_str="999888777666555444", name="Second Gateway", online=False),
]


@pytest.fixture(autouse=True)
def mock_auth_and_rest() -> Generator[tuple]:
    """Patch RenogyAuth.login and RenogyREST.get_gateways for all tests."""
    with (
        patch(
            "custom_components.renogy_gateway.config_flow.RenogyAuth"
        ) as mock_auth_cls,
        patch(
            "custom_components.renogy_gateway.config_flow.RenogyREST"
        ) as mock_rest_cls,
    ):
        mock_auth = mock_auth_cls.return_value
        mock_auth.login = AsyncMock(return_value=MOCK_TOKENS)
        mock_auth._headers = MagicMock(return_value={})

        mock_rest = mock_rest_cls.return_value
        mock_rest.get_gateways = AsyncMock(return_value=SINGLE_GATEWAY)

        yield mock_auth, mock_rest


@pytest.mark.usefixtures("mock_setup_entry")
async def test_single_gateway_creates_entry(
    hass: HomeAssistant,
    mock_auth_and_rest: tuple,
) -> None:
    """Happy path: one gateway → entry created without selection step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"email": MOCK_EMAIL, "password": MOCK_PASSWORD},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == MOCK_GATEWAY_NAME
    assert result["data"]["email"] == MOCK_EMAIL
    assert result["data"]["gateway_id"] == MOCK_GATEWAY_ID
    assert "password" not in result["data"]


@pytest.mark.usefixtures("mock_setup_entry")
async def test_multiple_gateways_shows_selection(
    hass: HomeAssistant,
    mock_auth_and_rest: tuple,
) -> None:
    """Multiple gateways → selection step shown."""
    _, mock_rest = mock_auth_and_rest
    mock_rest.get_gateways = AsyncMock(return_value=MULTI_GATEWAYS)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"email": MOCK_EMAIL, "password": MOCK_PASSWORD},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_gateway"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"gateway_id": MOCK_GATEWAY_ID},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["gateway_id"] == MOCK_GATEWAY_ID


async def test_invalid_credentials_shows_error(
    hass: HomeAssistant,
    mock_auth_and_rest: tuple,
) -> None:
    """Bad credentials → error on user step."""
    mock_auth, _ = mock_auth_and_rest
    mock_auth.login = AsyncMock(side_effect=RenogyAuthError("bad creds"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"email": MOCK_EMAIL, "password": "wrong"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "invalid_auth"


async def test_connection_error_shows_error(
    hass: HomeAssistant,
    mock_auth_and_rest: tuple,
) -> None:
    """Connection failure → cannot_connect error."""
    mock_auth, _ = mock_auth_and_rest
    mock_auth.login = AsyncMock(side_effect=RenogyConnectionError("timeout"))

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"email": MOCK_EMAIL, "password": MOCK_PASSWORD},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"]["base"] == "cannot_connect"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_duplicate_entry_aborted(
    hass: HomeAssistant,
    mock_auth_and_rest: tuple,
) -> None:
    """Duplicate unique_id → abort."""
    # First entry
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"email": MOCK_EMAIL, "password": MOCK_PASSWORD},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Second attempt with same credentials
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"email": MOCK_EMAIL, "password": MOCK_PASSWORD},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_does_not_persist_password(
    hass: HomeAssistant,
    mock_config_entry,
    mock_auth_and_rest: tuple,
) -> None:
    """Reauth must update tokens without ever writing the password back to the entry."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"email": MOCK_EMAIL, "password": MOCK_PASSWORD},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert "password" not in mock_config_entry.data
