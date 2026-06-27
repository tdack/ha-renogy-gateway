"""Constants for the Renogy Gateway integration."""

import logging
import re

DOMAIN = "renogy_gateway"

CONF_GATEWAY_ID = "gateway_id"
CONF_GATEWAY_NAME = "gateway_name"

# Token keys stored in config entry data
CONF_REFRESH_TOKEN = "refresh_token"
CONF_RTM_TOKEN = "rtm_token"
CONF_RTM_DID = "rtm_did"
CONF_DEVICE_UUID = "device_uuid"

RTM_RECONNECT_DELAY_MIN = 2  # seconds
RTM_RECONNECT_DELAY_MAX = 30  # seconds

LOGGER = logging.getLogger(__name__)

# Leaves that are protocol internals or maintenance commands rather than
# user-facing settings, even though the schema marks them writable.
HIDE_LEAVES = frozenset(
    {
        "inverter_switch",
        "di_mapping",
        "di_mapping2",
        "ctrl_sp_blacklist",
        "alarmList",
        "clean_history_data",
        "save_config",
        "tp_bind_list",
        "config",
        "addr",
        "coef",
        # Schema-internal channel-count bookkeeping (distribution_box),
        # confirmed via captures/*.har in the sibling renogy-gateway repo —
        # not user-meaningful telemetry, just "how many dc_10a_N slots exist".
        "dc_10a_count",
        "dc_20a_count",
        "dc_voltage_count",
        "di_count",
        "relay_count",
        "ai_count",
    }
)

# Patterns identifying read-only status/alarm/version fields that belong in
# HA's Diagnostic section rather than mixed into the main entity list.
# Mirrors apps/hass-bridge/src/filter.ts diagnosticPatterns in the sibling
# renogy-gateway repo.
_DIAGNOSTIC_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"\.online$",
        r"alarm",
        r"fault",
        r"\berror",
        r"warning",
        r"_status$",
        r"\.status$",
        r"_state$",
        r"_code$",
        r"protocol",
        r"firmware",
        r"_version$",
        r"heartbeat",
    )
)


def is_diagnostic_field(sp: str) -> bool:
    """Return True if the field's path matches a diagnostic pattern.

    `sp` is the full topic path ("<did>/<namespace>.<field_path>"); matching
    is done against the namespace+field-path portion, same as the dashboard's
    fieldPath ("<ns>.<path>").
    """
    field_path = sp.split("/", 1)[-1]
    return any(p.search(field_path) for p in _DIAGNOSTIC_PATTERNS)
