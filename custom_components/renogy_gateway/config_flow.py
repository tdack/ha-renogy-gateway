"""Config flow for the Renogy Gateway integration."""

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers import aiohttp_client

from .api.auth import RenogyAuth, RenogyAuthError, RenogyConnectionError
from .api.models import GatewayInfo, TokenSet
from .api.rest import RenogyREST
from .const import (
    CONF_DEVICE_UUID,
    CONF_GATEWAY_ID,
    CONF_GATEWAY_NAME,
    CONF_REFRESH_TOKEN,
    CONF_RTM_DID,
    CONF_RTM_TOKEN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class RenogyGatewayConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Renogy Gateway."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._email: str = ""
        self._password: str = ""
        self._tokens: TokenSet | None = None
        self._gateways: list[GatewayInfo] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial credential entry step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._email = user_input[CONF_EMAIL]
            self._password = user_input[CONF_PASSWORD]

            tokens, gateways, error = await self._try_login(self._email, self._password)
            if error:
                errors["base"] = error
            else:
                assert tokens is not None
                assert gateways is not None
                self._tokens = tokens
                self._gateways = gateways

                if len(gateways) == 1:
                    return await self._create_entry(gateways[0])
                return await self.async_step_select_gateway()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    async def async_step_select_gateway(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user choose which gateway to add when multiple are present."""
        if user_input is not None:
            selected_id = user_input[CONF_GATEWAY_ID]
            gateway = next(
                (g for g in self._gateways if g.did_str == selected_id), None
            )
            if gateway:
                return await self._create_entry(gateway)

        gateway_options = {g.did_str: g.name for g in self._gateways}
        return self.async_show_form(
            step_id="select_gateway",
            data_schema=vol.Schema(
                {vol.Required(CONF_GATEWAY_ID): vol.In(gateway_options)}
            ),
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication (e.g. after token expiry)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm re-authentication with new credentials."""
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            password = user_input[CONF_PASSWORD]

            tokens, _, error = await self._try_login(email, password)
            if error:
                errors["base"] = error
            else:
                assert tokens is not None
                entry = self._get_reauth_entry()
                new_data = {
                    **entry.data,
                    CONF_EMAIL: email,
                    CONF_ACCESS_TOKEN: tokens.access_token,
                    CONF_REFRESH_TOKEN: tokens.refresh_token,
                    CONF_RTM_TOKEN: tokens.rtm_token,
                    CONF_RTM_DID: tokens.rtm_did,
                    CONF_DEVICE_UUID: tokens.device_uuid,
                }
                new_data.pop(CONF_PASSWORD, None)
                self.hass.config_entries.async_update_entry(entry, data=new_data)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _try_login(
        self, email: str, password: str
    ) -> tuple[TokenSet | None, list[GatewayInfo] | None, str | None]:
        """Attempt login and gateway discovery. Returns (tokens, gateways, error_key)."""
        session = aiohttp_client.async_get_clientsession(self.hass)
        tokens_holder: list[TokenSet] = []

        async def _noop_persist(t: TokenSet) -> None:
            tokens_holder.append(t)

        auth = RenogyAuth(session, _noop_persist)
        try:
            tokens = await auth.login(email, password)
        except RenogyAuthError as err:
            _LOGGER.debug("Renogy auth error: %s", err)
            return None, None, "invalid_auth"
        except RenogyConnectionError as err:
            _LOGGER.error("Renogy connection error during login: %s", err)
            return None, None, "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error during Renogy login")
            return None, None, "unknown"

        rest = RenogyREST(session, auth)
        try:
            gateways = await rest.get_gateways()
        except RenogyConnectionError as err:
            _LOGGER.error("Renogy connection error fetching gateways: %s", err)
            return None, None, "cannot_connect"
        except Exception:
            _LOGGER.exception("Unexpected error fetching gateways")
            return None, None, "unknown"

        if not gateways:
            return None, None, "cannot_connect"

        return tokens, gateways, None

    async def _create_entry(self, gateway: GatewayInfo) -> ConfigFlowResult:
        """Create the config entry for the selected gateway."""
        assert self._tokens is not None

        unique_id = f"{self._email}_{gateway.did_str}"
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=gateway.name,
            data={
                CONF_EMAIL: self._email,
                CONF_GATEWAY_ID: gateway.did_str,
                CONF_GATEWAY_NAME: gateway.name,
                CONF_ACCESS_TOKEN: self._tokens.access_token,
                CONF_REFRESH_TOKEN: self._tokens.refresh_token,
                CONF_RTM_TOKEN: self._tokens.rtm_token,
                CONF_RTM_DID: self._tokens.rtm_did,
                CONF_DEVICE_UUID: self._tokens.device_uuid,
            },
        )
