"""Helpers for configuration handling."""

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import CONF_DISCOVERY, CONF_PLATFORM

from .const import (
    CONF_DEFAULTS,
    CONF_IDLE_DISCONNECT_DELAY,
    DEFAULT_IDLE_DISCONNECT_DELAY,
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
