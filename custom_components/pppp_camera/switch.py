"""PPPP switches for controlling cameras."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_LAMP, LAMP_STATE_PROPERTY
from .device import PPPPDevice
from .entity import PPPPLampEntity
from .config_helpers import get_platform_config


@dataclass(frozen=True, kw_only=True)
class PPPPSwitchEntityDescription(SwitchEntityDescription):
    """Describes PPPP switch entity."""

    turn_on_fn: Callable[
        [PPPPDevice], Callable[[Any], Coroutine[Any, Any, None]]
    ]
    turn_off_fn: Callable[
        [PPPPDevice], Callable[[Any], Coroutine[Any, Any, None]]
    ]
    turn_on_data: Any
    turn_off_data: Any
    supported_fn: Callable[[PPPPDevice, HomeAssistant], bool]


SWITCHES: tuple[PPPPSwitchEntityDescription, ...] = (
    PPPPSwitchEntityDescription(
        key="white_lamp",
        translation_key="white_lamp",
        turn_on_data=None,
        turn_off_data=None,
        turn_on_fn=lambda device: device.async_white_light_on,
        turn_off_fn=lambda device: device.async_white_light_off,
        supported_fn=lambda device, hass: LAMP_STATE_PROPERTY["white_lamp"] in device.device.properties and get_platform_config(hass)[CONF_LAMP] == Platform.SWITCH,
        icon="mdi:lightbulb"
    ),
    PPPPSwitchEntityDescription(
        key="ir_lamp",
        translation_key="ir_lamp",
        turn_on_data=None,
        turn_off_data=None,
        turn_on_fn=lambda device: device.async_ir_light_on,
        turn_off_fn=lambda device: device.async_ir_light_off,
        supported_fn=lambda device, hass: LAMP_STATE_PROPERTY["ir_lamp"] in device.device.properties and get_platform_config(hass)[CONF_LAMP] == Platform.SWITCH,
        icon="mdi:lightbulb-night",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a PPPP switch platform."""
    device = hass.data[DOMAIN][config_entry.unique_id]

    async_add_entities(
        PPPPSwitch(device, description)
        for description in SWITCHES
        if description.supported_fn(device, hass)
    )


class PPPPSwitch(PPPPLampEntity, SwitchEntity):
    """A PPPP lamp exposed as a switch.

    State handling (seeding, live tracking where the camera reports it, and the
    turn_on/turn_off write path) lives in PPPPLampEntity, shared with the light
    platform.
    """

    entity_description: PPPPSwitchEntityDescription
