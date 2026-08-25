"""Helpers for configuration handling."""

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_DISCOVERY, CONF_PLATFORM

from .const import (
    CONF_DEFAULTS,
    CONF_IDLE_DISCONNECT_DELAY,
    CONF_INFO_POLL_INTERVAL,
    CONF_STATUS_POLL_INTERVAL,
    DEFAULT_IDLE_DISCONNECT_DELAY,
    DEFAULT_INFO_POLL_INTERVAL,
    DEFAULT_STATUS_POLL_INTERVAL,
    DOMAIN,
)


def get_config(hass: HomeAssistant) -> dict[str, Any]:
    """Get configuration for DOMAIN."""
    return hass.data.get(DOMAIN, {}).get("config", {})

def get_defaults(hass: HomeAssistant) -> dict[str, Any]:
    """Get configuration for DOMAIN."""
    return get_config(hass).get(CONF_DEFAULTS, {})

def get_discovery_config(hass: HomeAssistant) -> dict[str, Any]:
    """Get configuration for DOMAIN."""
    return get_config(hass).get(CONF_DISCOVERY, {})

def get_platform_config(hass: HomeAssistant) -> dict[str, Any]:
    """Get configuration for DOMAIN."""
    return get_config(hass).get(CONF_PLATFORM, {})

def get_idle_disconnect_delay(
    hass: HomeAssistant, config_entry: ConfigEntry | None = None
) -> int:
    """Seconds to keep a camera session warm after the last operation.

    A per-entry options value (set via the options flow) overrides the YAML
    global default when present.
    """
    if config_entry is not None and CONF_IDLE_DISCONNECT_DELAY in config_entry.options:
        return config_entry.options[CONF_IDLE_DISCONNECT_DELAY]
    return get_config(hass).get(
        CONF_IDLE_DISCONNECT_DELAY, DEFAULT_IDLE_DISCONNECT_DELAY
    )


def _get_interval(
    hass: HomeAssistant,
    config_entry: ConfigEntry | None,
    option: str,
    default: int,
) -> int:
    """Read an interval option, preferring the per-entry value."""
    if config_entry is not None and option in config_entry.options:
        return int(config_entry.options[option])
    return int(get_config(hass).get(option, default))


def get_status_poll_interval(
    hass: HomeAssistant, config_entry: ConfigEntry | None = None
) -> int:
    """Seconds between status-block refreshes (0 disables polling)."""
    return _get_interval(
        hass, config_entry, CONF_STATUS_POLL_INTERVAL, DEFAULT_STATUS_POLL_INTERVAL
    )


def get_info_poll_interval(
    hass: HomeAssistant, config_entry: ConfigEntry | None = None
) -> int:
    """Seconds between clock/SSID refreshes (0 disables polling)."""
    return _get_interval(
        hass, config_entry, CONF_INFO_POLL_INTERVAL, DEFAULT_INFO_POLL_INTERVAL
    )
