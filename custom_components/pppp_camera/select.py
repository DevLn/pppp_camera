"""Configuration selects for PPPP cameras."""

from __future__ import annotations

import asyncio

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, LOGGER
from .device import PPPPDevice
from .entity import PPPPBaseEntity

# Order matches aiopppp's VideoResolution enum, so the index is the wire value.
RESOLUTION_OPTIONS = ["qvga", "vga", "hd", "fd", "ud"]

# Grace period after the stream starts before the camera reports real video
# parameters. Measured on FTYC: an immediate read still returns zeros.
RESOLUTION_SETTLE_SECONDS = 2.5

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
        self._refresh_task: asyncio.Task | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to availability (base) and streaming-state changes."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self.device.signal_streaming, self._handle_streaming
            )
        )
        # The camera may already be streaming when this entity is added.
        self._schedule_refresh()

    @callback
    def _handle_streaming(self) -> None:
        """The stream started or stopped; the reported value only exists while
        it runs, so re-read it now."""
        self._schedule_refresh()

    @callback
    def _schedule_refresh(self) -> None:
        if self._refresh_task and not self._refresh_task.done():
            return
        self._refresh_task = self.hass.async_create_task(self._async_refresh())
        self.async_on_remove(self._refresh_task.cancel)

    async def _async_refresh(self) -> None:
        """Re-read the resolution, writing state only if it actually changed."""
        try:
            # The camera needs a moment after the stream comes up before it
            # reports real video parameters (it still answers with zeros
            # immediately after LIVEVIDEO_START).
            await asyncio.sleep(RESOLUTION_SETTLE_SECONDS)
            if await self.device.async_refresh_resolution():
                self.async_write_ha_state()
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001 - diagnostic only
            LOGGER.debug("%s: resolution refresh failed: %s", self.device.dev_id, err)

    @property
    def current_option(self) -> str | None:
        """Return the resolution the camera last reported (or we last set).

        None until the camera has actually reported one: an idle camera
        answers with an all-zero parameter table, and trusting that would
        show QVGA on every camera regardless of its real resolution.
        """
        value = self.device.extra_info.get("resolution")
        if isinstance(value, int) and 0 <= value < len(RESOLUTION_OPTIONS):
            return RESOLUTION_OPTIONS[value]
        return None

    async def async_select_option(self, option: str) -> None:
        """Change the camera's video resolution."""
        await self.device.async_set_resolution(option)
        self.async_write_ha_state()
