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
            # Device type, e.g. "XR_PTZ", falling back to the device id for
            # cameras whose type aiopppp can't name (or doesn't get told).
            model=camera_properties.get('devTypeName') or self.device.dev_id,
            # Chip type, e.g. "TX_817_810". No numeric fallback: an unnamed
            # chip leaves this unset rather than showing a bare number, and the
            # number is on the device_type sensor. JSON cameras report no chip
            # at all but do report an image sensor, which is the same idea.
            model_id=camera_properties.get('chipTypeName') or camera_properties.get('sensor'),
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
    assumed, and remember what we last sent instead.
    """

    _attr_has_entity_name = True
    # Assumed on every camera, including the ones that do report a reading.
    # These are cheap devices whose status block has repeatedly turned out to
    # carry fields that look populated but aren't -- PTZA's `icut` sits at 1
    # whatever the IR does, and its whole powerSupply word reads zero -- so a
    # firmware we haven't tested could just as easily report a lamp state that
    # is quietly wrong. A toggle would claim a certainty we don't have, and it
    # also keeps every camera's controls looking the same.
    _attr_assumed_state = True

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
