"""PPPP Buttons."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, CONF_LAMP, LAMP_STATE_PROPERTY
from .device import PPPPDevice
from .entity import PPPPBaseEntity
from .config_helpers import get_config, get_platform_config


@dataclass(frozen=True, kw_only=True)
class PPPPButtonEntityDescription(ButtonEntityDescription):
    """Describes PPPP button entity."""

    press_fn: Callable[
        [PPPPDevice], Callable[[Any], Coroutine[Any, Any, None]]
    ]
    press_data: Any
    supported_fn: Callable[[PPPPDevice, HomeAssistant], bool]


BUTTONS: tuple[PPPPButtonEntityDescription, ...] = (
    PPPPButtonEntityDescription(
        key="reboot",
        translation_key="reboot",
        press_fn=lambda device: device.async_reboot,
        press_data=None,
        # Reboot is always available on a set-up camera; it was previously gated
        # on the unrelated "auth" login flag, which hid it whenever login failed
        # even though reboot works without auth.
        supported_fn=lambda device, _: True,
        device_class = ButtonDeviceClass.RESTART,
        entity_category = EntityCategory.CONFIG,
    ),
    PPPPButtonEntityDescription(
        key="white_lamp",
        translation_key="white_lamp",
        press_fn=lambda device: device.async_white_light_toggle,
        press_data=None,
        supported_fn=lambda device, hass: LAMP_STATE_PROPERTY["white_lamp"] in device.device.properties and get_platform_config(hass)[CONF_LAMP] == Platform.BUTTON,
        icon="mdi:lightbulb"
    ),
    PPPPButtonEntityDescription(
        key="ir_lamp",
        translation_key="ir_lamp",
        press_fn=lambda device: device.async_ir_light_toggle,
        press_data=None,
        supported_fn=lambda device, hass: LAMP_STATE_PROPERTY["ir_lamp"] in device.device.properties and get_platform_config(hass)[CONF_LAMP] == Platform.BUTTON,
        icon="mdi:lightbulb-night"
    ),
    PPPPButtonEntityDescription(
        key="sync_time",
        translation_key="sync_time",
        press_fn=lambda device: device.async_sync_datetime,
        press_data=None,
        # Only binary cameras expose a set-time command in the library.
        supported_fn=lambda device, _: not device.device.descriptor.is_json,
        icon="mdi:clock-check",
        entity_category=EntityCategory.CONFIG,
    ),
)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a PPPP button platform."""
    device = hass.data[DOMAIN][config_entry.unique_id]

    async_add_entities(
        PPPPButton(device, description)
        for description in BUTTONS
        if description.supported_fn(device, hass)
    )

class PPPPButton(PPPPBaseEntity, ButtonEntity):
    """A PPPP button."""

    entity_description: PPPPButtonEntityDescription
    _attr_has_entity_name = True

    def __init__(
        self, device: PPPPDevice, description: PPPPButtonEntityDescription
    ) -> None:
        """Initialize the button."""
        super().__init__(device)

        self._attr_unique_id = f"{self.device.dev_id}_{description.key}"
        self.entity_description = description

    async def async_press(self) -> None:
        """Handle button press."""
        await self.entity_description.press_fn(self.device)(
            self.entity_description.press_data
        )



# class SetSystemDateAndTimeButton(PPPPBaseEntity, ButtonEntity):
#     """Defines a PPPP SetSystemDateAndTime button."""
#
#     _attr_entity_category = EntityCategory.CONFIG
#
#     def __init__(self, device: PPPPDevice) -> None:
#         """Initialize the button entity."""
#         super().__init__(device)
#         self._attr_name = f"{self.device.dev_id} Set System Date and Time"
#         self._attr_unique_id = f"{self.device.dev_id}_setsystemdatetime"
#
#     async def async_press(self) -> None:
#         """Send out a SetSystemDateAndTime command."""
#         await self.device.async_manually_set_date_and_time()
