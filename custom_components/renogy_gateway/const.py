"""Constants for the Renogy Gateway integration."""

import logging

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
    }
)
