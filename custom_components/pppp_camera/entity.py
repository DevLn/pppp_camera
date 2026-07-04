from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .device import PPPPDevice


class PPPPBaseEntity(Entity):
    """Base class common to all PPPP entities."""

    def __init__(self, device: PPPPDevice) -> None:
        """Initialize the PPPP entity."""
        self.device: PPPPDevice = device

    async def async_added_to_hass(self) -> None:
        """Refresh state when the device's availability changes."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self.device.signal_available, self.async_write_ha_state
            )
        )

    @property
    def available(self):
        """Return True if device is available."""
        return self.device.available

    @property
    def device_info(self) -> DeviceInfo:
        """Return a device description for device registry."""

        camera_properties = self.device.device.properties
        return DeviceInfo(
            identifiers={(DOMAIN, self.device.dev_id)},
            model=self.device.dev_id,
            model_id=camera_properties.get('sensor'),
            serial_number=self.device.dev_id,
            hw_version=camera_properties.get('mcuver'),
            # The camera has no web UI (so a configuration_url "Visit" link is
            # useless) and reports its own ipAddr as zeros. Surface the
            # configured IP in the Firmware field instead: not strictly
            # accurate, but it makes the address visible as plain text.
            sw_version=self.device.host,
        )
