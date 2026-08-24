"""Configuration selects for PPPP cameras."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import PPPPDevice
from .entity import PPPPBaseEntity

# Order matches aiopppp's VideoResolution enum, so the index is the wire value.
RESOLUTION_OPTIONS = ["qvga", "vga", "hd", "fd", "ud"]

RESOLUTION_DESCRIPTION = SelectEntityDescription(
    key="resolution",
    translation_key="resolution",
    entity_category=EntityCategory.CONFIG,
    options=RESOLUTION_OPTIONS,
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the PPPP select platform."""
    device: PPPPDevice = hass.data[DOMAIN][config_entry.unique_id]
    # Binary-protocol cameras only; JSON sessions don't implement video params.
    if not hasattr(device.device.session, "set_resolution"):
        return
    async_add_entities([PPPPResolutionSelect(device)])


class PPPPResolutionSelect(PPPPBaseEntity, SelectEntity):
    """Video resolution of the camera stream."""

    entity_description: SelectEntityDescription
    _attr_has_entity_name = True

    def __init__(self, device: PPPPDevice) -> None:
        """Initialize the select."""
        super().__init__(device)
        self.entity_description = RESOLUTION_DESCRIPTION
        self._attr_unique_id = f"{self.device.dev_id}_resolution"

    @property
    def current_option(self) -> str | None:
        """Return the resolution the camera last reported (or we last set)."""
        value = self.device.extra_info.get("resolution")
        if isinstance(value, int) and 0 <= value < len(RESOLUTION_OPTIONS):
            return RESOLUTION_OPTIONS[value]
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the camera's video resolution."""
        await self.device.async_set_resolution(option)
        self.async_write_ha_state()
