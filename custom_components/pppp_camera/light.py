"""PPPP lights for controlling cameras."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.light import ColorMode, LightEntity, LightEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_LAMP, LAMP_STATE_PROPERTY
from .device import PPPPDevice
from .entity import PPPPLampEntity
from .config_helpers import get_platform_config


@dataclass(frozen=True, kw_only=True)
class PPPPLightEntityDescription(LightEntityDescription):
    """Describes PPPP light entity."""

    turn_on_fn: Callable[
        [PPPPDevice], Callable[[Any], Coroutine[Any, Any, None]]
    ]
    turn_off_fn: Callable[
        [PPPPDevice], Callable[[Any], Coroutine[Any, Any, None]]
    ]
    turn_on_data: Any
    turn_off_data: Any
    supported_fn: Callable[[PPPPDevice, HomeAssistant], bool]


LIGHTS: tuple[PPPPLightEntityDescription, ...] = (
    PPPPLightEntityDescription(
        key="white_lamp",
        translation_key="white_lamp",
        turn_on_data=None,
        turn_off_data=None,
        turn_on_fn=lambda device: device.async_white_light_on,
        turn_off_fn=lambda device: device.async_white_light_off,
        supported_fn=lambda device, hass: LAMP_STATE_PROPERTY["white_lamp"] in device.device.properties and get_platform_config(hass)[CONF_LAMP] == Platform.LIGHT,
        icon="mdi:flashlight"
    ),
    PPPPLightEntityDescription(
        key="ir_lamp",
        translation_key="ir_lamp",
        turn_on_data=None,
        turn_off_data=None,
        turn_on_fn=lambda device: device.async_ir_light_on,
        turn_off_fn=lambda device: device.async_ir_light_off,
        supported_fn=lambda device, hass: LAMP_STATE_PROPERTY["ir_lamp"] in device.device.properties and get_platform_config(hass)[CONF_LAMP] == Platform.LIGHT,
        icon="mdi:lightbulb-night",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a PPPP light platform."""
    device = hass.data[DOMAIN][config_entry.unique_id]

    async_add_entities(
        PPPPLight(device, description)
        for description in LIGHTS
        if description.supported_fn(device, hass)
    )


class PPPPLight(PPPPLampEntity, LightEntity):
    """A PPPP lamp exposed as a light.

    State handling (seeding, live tracking where the camera reports it, and the
    turn_on/turn_off write path) lives in PPPPLampEntity, shared with the switch
    platform.
    """

    entity_description: PPPPLightEntityDescription
    # Set supported color modes for on/off lights
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF
