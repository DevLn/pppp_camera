from __future__ import annotations

from typing import Any

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import (
    DOMAIN,
    LAMP_REPORTED_PROPERTY,
    LAMP_STATE_PROPERTY,
    POLL_GROUP_STATUS,
)
from .device import PPPPDevice


def format_device_type(properties: dict[str, Any]) -> str | None:
    """Render the camera's type as "DevType/ChipType", e.g. "XR_PTZ/TX_817_810".

    Names only. aiopppp's enums are transcribed from the vendor apps and are
    incomplete, so a half it can't name (PTZA's chip 2) is dropped rather than
    shown as a bare number -- "XR_PTZ". Returns None when neither half has a
    name, including for JSON cameras, which report no type at all. The raw
    numbers stay available on the device_type sensor's attributes.
    """
    names = [properties.get("devTypeName"), properties.get("chipTypeName")]
    return "/".join(name for name in names if name) or None


class PPPPBaseEntity(Entity):
    """Base class common to all PPPP entities."""

    # These entities push state via the dispatcher / are assumed-state; none of
    # them implement async_update, so polling would just be wasted no-op calls.
    _attr_should_poll = False

    def __init__(self, device: PPPPDevice) -> None:
        """Initialize the PPPP entity."""
        self.device: PPPPDevice = device

    async def async_added_to_hass(self) -> None:
        """Refresh state when the device's data or availability changes."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, self.device.signal_available, self._handle_device_update
            )
        )

    @callback
    def _handle_device_update(self) -> None:
        """Handle a refresh of the device's properties or availability.

        Subclasses that cache state override this to adopt the new reading
        before writing; the signal also fires after each poll, not only on an
        availability change.
        """
        self.async_write_ha_state()

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
            # No real manufacturer is discoverable over PPPP, so the field is
            # reused for the camera's type, e.g. "XR_PTZ/TX_817_810". None
            # (leaving it unset) for cameras that report no named type.
            manufacturer=format_device_type(camera_properties),
            model_id=camera_properties.get('sensor'),
            serial_number=self.device.dev_id,
            hw_version=camera_properties.get('mcuver'),
            # The camera has no web UI (so a configuration_url "Visit" link is
            # useless) and reports its own ipAddr as zeros. Surface the
            # configured IP in the Firmware field instead: not strictly
            # accurate, but it makes the address visible as plain text.
            sw_version=self.device.host,
        )


class PPPPLampEntity(PPPPBaseEntity):
    """Shared on/off behaviour for the white and IR lamps.

    Cameras whose status block populates the function bitmap report real lamp
    state (confirmed on FTYC): those entities follow the status poll, so a
    change made from the vendor app shows up here. The rest can only be
    assumed, and keep the previous behaviour of remembering what we last sent.
    """

    _attr_has_entity_name = True

    def __init__(self, device: PPPPDevice, description) -> None:
        """Initialize the lamp."""
        super().__init__(device)

        self.entity_description = description
        self._attr_unique_id = f"{device.dev_id}_{description.key}"
        self._reported_property = LAMP_REPORTED_PROPERTY.get(description.key)
        reported = (
            device.device.properties.get(self._reported_property)
            if self._reported_property
            else None
        )
        self._reports_state = reported is not None
        self._attr_assumed_state = not self._reports_state

        if self._reports_state:
            self._attr_is_on = bool(reported)
        else:
            prop = LAMP_STATE_PROPERTY.get(description.key)
            self._attr_is_on = bool(device.device.properties.get(prop)) if prop else False

    async def async_added_to_hass(self) -> None:
        """Claim the status poll, but only where it carries a real reading."""
        await super().async_added_to_hass()
        if self._reports_state:
            self.async_on_remove(self.device.register_poll_group(POLL_GROUP_STATUS))

    @callback
    def _handle_device_update(self) -> None:
        """Adopt the camera's own reading after a refresh.

        State is cached in _attr_is_on rather than read live so that a just-sent
        command shows immediately and is corrected here on the next poll,
        instead of flickering back to a stale reading in between.
        """
        if self._reports_state:
            reported = self.device.device.properties.get(self._reported_property)
            if reported is not None:
                self._attr_is_on = bool(reported)
        super()._handle_device_update()

    async def _async_set_lamp(self, is_on: bool) -> None:
        description = self.entity_description
        if is_on:
            await description.turn_on_fn(self.device)(description.turn_on_data)
        else:
            await description.turn_off_fn(self.device)(description.turn_off_data)
        # Commit state only after the command succeeds, so a failed command
        # doesn't leave the UI showing the wrong state.
        self._attr_is_on = is_on
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the lamp on."""
        await self._async_set_lamp(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the lamp off."""
        await self._async_set_lamp(False)
