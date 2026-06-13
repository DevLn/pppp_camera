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
from .entity import PPPPBaseEntity
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
    supported_fn: Callable[[PPPPDevice], bool]


LIGHTS: tuple[PPPPLightEntityDescription, ...] = (
    PPPPLightEntityDescription(
        key="white_lamp",
        translation_key="white_lamp",
        turn_on_data=None,
        turn_off_data=None,
        turn_on_fn=lambda device: device.async_white_light_on,
        turn_off_fn=lambda device: device.async_white_light_off,
        supported_fn=lambda device, hass: CONF_LAMP in device.device.properties and get_platform_config(hass)[CONF_LAMP] == Platform.LIGHT,
        icon="mdi:flashlight"
    ),
    PPPPLightEntityDescription(
        key="ir_lamp",
        translation_key="ir_lamp",
        turn_on_data=None,
        turn_off_data=None,
        turn_on_fn=lambda device: device.async_ir_light_on,
        turn_off_fn=lambda device: device.async_ir_light_off,
        supported_fn=lambda device, hass: CONF_LAMP in device.device.properties and get_platform_config(hass)[CONF_LAMP] == Platform.LIGHT,
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


class PPPPLight(PPPPBaseEntity, LightEntity):
    """A PPPP light."""

    entity_description: PPPPLightEntityDescription
    _attr_has_entity_name = True
    # Set supported color modes for on/off lights
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF
    # These cameras can't reliably report lamp state, so it is assumed.
    _attr_assumed_state = True

    def __init__(
        self, device: PPPPDevice, description: PPPPLightEntityDescription
    ) -> None:
        """Initialize the light."""
        super().__init__(device)

        self._attr_unique_id = f"{self.device.dev_id}_{description.key}"
        #self._attr_name = description.translation_key
        self.entity_description = description
        # Seed from the camera's reported state instead of always starting off.
        prop = LAMP_STATE_PROPERTY.get(description.key)
        self._attr_is_on = bool(device.device.properties.get(prop)) if prop else False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on light."""
        await self.entity_description.turn_on_fn(self.device)(
            self.entity_description.turn_on_data
        )
        # Commit state only after the command succeeds, so a failed command
        # doesn't leave the UI showing the wrong state.
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off light."""
        await self.entity_description.turn_off_fn(self.device)(
            self.entity_description.turn_off_data
        )
        self._attr_is_on = False
        self.async_write_ha_state()
